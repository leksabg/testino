"""Citac Outlook .msg fajlova (OLE compound file), bez extract-msg zavisnosti.

Potreban je samo `olefile` (cist Python).
"""
from __future__ import annotations

import struct

from .mapi import (PR_ATTACH_DATA, PR_ATTACH_METHOD, PR_INTERNET_CPID,
                   PR_MESSAGE_CODEPAGE, ATTACH_EMBEDDED_MSG, Attachment,
                   PropBag, decode_mapi_string)

try:
    import olefile
except ImportError:  # pragma: no cover
    olefile = None


def _read_storage(ole, prefix: list[str], header_size: int, entries: list[list[str]]) -> dict:
    """Ucitava sva svojstva jednog "storage" nivoa (poruka, primalac, prilog)."""
    props: dict = {}
    depth = len(prefix)
    # 1) fiksna svojstva iz __properties_version1.0
    ppath = prefix + ["__properties_version1.0"]
    if ole.exists("/".join(ppath)):
        data = ole.openstream(ppath).read()
        for off in range(header_size, len(data) - 15, 16):
            tag, _flags = struct.unpack_from("<II", data, off)
            ptype, pid = tag & 0xFFFF, tag >> 16
            val = data[off + 8: off + 16]
            if ptype == 0x0003:
                props[pid] = struct.unpack("<i", val[:4])[0]
            elif ptype == 0x0002:
                props[pid] = struct.unpack("<h", val[:2])[0]
            elif ptype == 0x000B:
                props[pid] = bool(val[0])
            elif ptype in (0x0040, 0x0014):
                props[pid] = struct.unpack("<q", val)[0]
            elif ptype == 0x0005:
                props[pid] = struct.unpack("<d", val)[0]

    # 2) codepage pre stringova
    cp = props.get(PR_INTERNET_CPID) or props.get(PR_MESSAGE_CODEPAGE)

    # 3) varijabilna svojstva iz __substg1.0_XXXXYYYY streamova
    for e in entries:
        if len(e) != depth + 1 or e[:depth] != prefix:
            continue
        name = e[-1]
        if not name.startswith("__substg1.0_") or len(name) < 20:
            continue
        try:
            pid = int(name[12:16], 16)
            ptype = int(name[16:20], 16)
        except ValueError:
            continue
        if ptype == 0x000D:
            continue
        if ole.get_type(e) != olefile.STGTY_STREAM:
            continue
        raw = ole.openstream(e).read()
        if ptype in (0x001F, 0x001E):
            props[pid] = decode_mapi_string(raw, ptype, cp)
        elif ptype == 0x0102:
            props[pid] = raw
        elif ptype in (0x101F, 0x101E):
            # multi-value string: nije bitno za mejl, preskoci
            continue
        else:
            props.setdefault(pid, raw)
    return props


def _read_message(ole, prefix: list[str], entries: list[list[str]], top: bool) -> PropBag:
    bag = PropBag()
    bag.props = _read_storage(ole, prefix, 32 if top else 24, entries)
    depth = len(prefix)
    children = sorted({e[depth] for e in entries if len(e) > depth and e[:depth] == prefix})
    for child in children:
        if child.startswith("__recip_version1.0_"):
            bag.recipients.append(_read_storage(ole, prefix + [child], 8, entries))
        elif child.startswith("__attach_version1.0_"):
            aprefix = prefix + [child]
            aprops = _read_storage(ole, aprefix, 8, entries)
            att = Attachment(props=aprops)
            emb = aprefix + ["__substg1.0_3701000D"]
            if aprops.get(PR_ATTACH_METHOD) == ATTACH_EMBEDDED_MSG and ole.exists("/".join(emb)):
                att.embedded = _read_message(ole, emb, entries, top=False)
            else:
                d = aprops.get(PR_ATTACH_DATA)
                att.data = d if isinstance(d, bytes) else None
            aprops.pop(PR_ATTACH_DATA, None)
            bag.attachments.append(att)
    return bag


def read_msg(path_or_bytes) -> PropBag:
    if olefile is None:
        raise RuntimeError("Za .msg fajlove instaliraj: pip install olefile")
    ole = olefile.OleFileIO(path_or_bytes)
    try:
        entries = ole.listdir(streams=True, storages=True)
        return _read_message(ole, [], entries, top=True)
    finally:
        ole.close()
