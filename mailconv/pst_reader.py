"""Citac .pst / .ost fajlova.

1) preko `pypff` (pip install libpff-python) - preporuceno
2) fallback: `readpst` alat (paket pst-utils / libpst) -> EML fajlovi
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
from typing import Iterator

from .mapi import (PR_ATTACH_METHOD, PR_ATTACH_DATA, PR_INTERNET_CPID,
                   PR_MESSAGE_CODEPAGE, PR_MESSAGE_CLASS, ATTACH_EMBEDDED_MSG,
                   Attachment, PropBag, decode_mapi_string)

try:
    import pypff  # type: ignore
except ImportError:  # pragma: no cover
    pypff = None

# PST sistemski folderi koje ne treba prenositi
SYSTEM_FOLDERS = {
    "search root", "spam search folder 2", "ipm_common_views", "ipm_views",
    "freebusy data", "finder", "itemprocsearch", "reminders", "tracked mail processing",
    "deferred action", "schedule", "shortcuts", "views", "common views",
    "conversation action settings", "quick step settings", "recoverable items",
    "sync issues", "conflicts", "local failures", "server failures", "yammer root",
    "externalcontacts", "personmetadata", "files", "conversation history",
    "recipient cache", "gal contacts", "organizational contacts", "photos",
    "social activity notifications", "allcategorizeditems", "allcontacts",
    "allitems", "allpersonmetadata", "allphotos", "favorites",
}
TOP_NAMES = {"top of personal folders", "top of outlook data file",
             "top of information store", "root - mailbox", "ipm_subtree",
             "vrh ličnih fascikli", "vrh licnih fascikli"}


def available() -> str | None:
    if pypff is not None:
        return "pypff"
    if shutil.which("readpst"):
        return "readpst"
    return None


def _props_from_record_sets(item) -> dict:
    raw: list[tuple[int, int, bytes | None]] = []
    try:
        n = item.number_of_record_sets
    except Exception:
        return {}
    for i in range(n):
        try:
            rs = item.get_record_set(i)
        except Exception:
            continue
        for j in range(rs.number_of_entries):
            try:
                e = rs.get_entry(j)
                raw.append((e.entry_type, e.value_type, e.data))
            except Exception:
                continue
    return _decode_entries(raw)


def _decode_entries(raw) -> dict:
    props: dict = {}
    # codepage prvo
    cp = None
    for pid, vt, data in raw:
        if pid in (PR_INTERNET_CPID, PR_MESSAGE_CODEPAGE) and vt == 0x0003 and data:
            cp = cp or struct.unpack("<i", data[:4])[0]
    for pid, vt, data in raw:
        if data is None or pid in props:
            continue
        try:
            if vt in (0x001F, 0x001E):
                props[pid] = decode_mapi_string(data, vt, cp)
            elif vt == 0x0003:
                props[pid] = struct.unpack("<i", data[:4])[0]
            elif vt == 0x0002:
                props[pid] = struct.unpack("<h", data[:2])[0]
            elif vt == 0x000B:
                props[pid] = bool(data[0]) if data else False
            elif vt in (0x0040, 0x0014):
                props[pid] = struct.unpack("<q", data[:8])[0]
            elif vt == 0x0102:
                props[pid] = data
        except Exception:
            continue
    return props


def _message_to_bag(msg, depth: int = 0) -> PropBag:
    bag = PropBag(props=_props_from_record_sets(msg))
    # tela: ako nisu u record set-u, uzmi preko getera
    for pid, getter in ((0x1000, "get_plain_text_body"), (0x1013, "get_html_body"),
                        (0x007D, "get_transport_headers")):
        if not bag.props.get(pid):
            try:
                v = getattr(msg, getter)()
                if v:
                    bag.props[pid] = v.decode("utf-8", "replace") if pid != 0x1013 and isinstance(v, bytes) else v
            except Exception:
                pass
    if not bag.props.get(0x1009) and not bag.props.get(0x1013):
        try:
            rtf = msg.get_rtf_body()
            if rtf:
                bag.props[0x1009] = rtf  # vec dekompresovan; decompress_rtf to prepoznaje
        except Exception:
            pass
    # primaoci
    try:
        rec = msg.recipients
        if rec is not None:
            for i in range(rec.number_of_record_sets):
                rs = rec.get_record_set(i)
                raw = []
                for j in range(rs.number_of_entries):
                    try:
                        e = rs.get_entry(j)
                        raw.append((e.entry_type, e.value_type, e.data))
                    except Exception:
                        pass
                bag.recipients.append(_decode_entries(raw))
    except Exception:
        pass
    # prilozi
    try:
        natt = msg.number_of_attachments
    except Exception:
        natt = 0
    for i in range(natt):
        try:
            a = msg.get_attachment(i)
        except Exception:
            continue
        aprops = _props_from_record_sets(a)
        aprops.pop(PR_ATTACH_DATA, None)
        att = Attachment(props=aprops)
        try:
            if not aprops.get(0x3707) and a.long_filename:
                aprops[0x3707] = a.long_filename
        except Exception:
            pass
        embedded = None
        if aprops.get(PR_ATTACH_METHOD) == ATTACH_EMBEDDED_MSG and depth < 8:
            try:
                if a.number_of_sub_items:
                    embedded = _message_to_bag(a.get_sub_item(0), depth + 1)
            except Exception:
                embedded = None
        if embedded is not None:
            att.embedded = embedded
        else:
            try:
                size = a.get_size()
                att.data = a.read_buffer(size) if size else b""
            except Exception:
                att.data = None
        bag.attachments.append(att)
    return bag


def iter_pst(path: str, include_nonmail: bool = False) -> Iterator[tuple[tuple[str, ...], PropBag | Exception]]:
    """Vraca (putanja_foldera, PropBag ili Exception) za svaku poruku."""
    f = pypff.file()
    f.open(path)
    try:
        root = f.get_root_folder()
        top = root
        for i in range(root.number_of_sub_folders):
            sf = root.get_sub_folder(i)
            if (sf.name or "").strip().lower() in TOP_NAMES:
                top = sf
                break
        yield from _walk(top, (), include_nonmail, top is root)
    finally:
        f.close()


def _walk(folder, path, include_nonmail, is_root):
    try:
        nmsg = folder.number_of_sub_messages
    except Exception:
        nmsg = 0
    for i in range(nmsg):
        try:
            m = folder.get_sub_message(i)
            bag = _message_to_bag(m)
            from .mapi import is_mail_class
            if not include_nonmail and not is_mail_class(bag.props.get(PR_MESSAGE_CLASS)):
                continue
            yield path, bag
        except Exception as exc:  # pokvarena poruka - nastavi dalje
            yield path, exc
    try:
        nsub = folder.number_of_sub_folders
    except Exception:
        nsub = 0
    for i in range(nsub):
        try:
            sf = folder.get_sub_folder(i)
        except Exception as exc:
            yield path, exc
            continue
        name = (sf.name or f"Folder{i}").strip()
        if is_root and name.lower() in SYSTEM_FOLDERS:
            continue
        if name.lower() in SYSTEM_FOLDERS and not path:
            continue
        yield from _walk(sf, path + (name,), include_nonmail, False)


def readpst_extract(path: str) -> str:
    """Raspakuje PST preko readpst u privremeni direktorijum sa .eml fajlovima."""
    out = tempfile.mkdtemp(prefix="mailconv_pst_")
    cmd = ["readpst", "-e", "-b", "-q", "-o", out, path]
    subprocess.run(cmd, check=True)
    return out


def cleanup(path: str):
    shutil.rmtree(path, ignore_errors=True)
