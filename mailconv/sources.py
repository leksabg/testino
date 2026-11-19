"""Pronalazenje i citanje poruka iz svih podrzanih formata.

Podrzano: .eml, .msg, .mbox (i Thunderbird/Gmail Takeout mbox bez ekstenzije),
Maildir / Maildir++, Apple Mail .emlx, .pst/.ost, Outlook for Mac .olm,
.zip / .tar(.gz) arhive koje sadrze bilo sta od navedenog.
Format se prepoznaje i po sadrzaju, ne samo po ekstenziji.
"""
from __future__ import annotations

import datetime as _dt
import mailbox
import os
import re
import shutil
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from typing import Iterator

from . import mapi, msg_reader, olm_reader, pst_reader
from .normalize import NotAnEmail, looks_like_email, normalize_ex, message_date


@dataclass
class Item:
    folder: tuple[str, ...]
    raw: bytes
    origin: str
    seen: bool = True
    flagged: bool = False
    date: _dt.datetime | None = None
    fmt: str = ""
    content_hash: str = ""


@dataclass
class Error:
    origin: str
    error: str
    folder: tuple[str, ...] = ()
    fmt: str = ""


@dataclass
class Options:
    include_nonmail: bool = False
    gmail_labels: bool = True
    x500_domain: str = "unknown.invalid"
    include_deleted: bool = False
    stats: dict = field(default_factory=dict)  # preskoceni fajlovi itd.


OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
IGNORE_EXT = {".msf", ".dat", ".json", ".sqlite", ".db", ".ini", ".log", ".plist",
              ".ds_store", ".lock", ".html", ".htm", ".css", ".js", ".png", ".jpg",
              ".jpeg", ".gif", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv",
              ".vcf", ".ics", ".exe", ".dll", ".sqlite-wal", ".sqlite-shm", ".py"}


def _bump(opts: Options, key: str, n: int = 1):
    opts.stats[key] = opts.stats.get(key, 0) + n


def detect(path: str) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    by_ext = {".eml": "eml", ".msg": "msg", ".mbox": "mbox", ".mbx": "mbox",
              ".mbs": "mbox", ".emlx": "emlx", ".pst": "pst", ".ost": "pst",
              ".olm": "olm", ".zip": "zip", ".tgz": "tar", ".tar": "tar",
              ".nws": "eml", ".mht": None, ".mhtml": None}
    if path.lower().endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        return "tar"
    if ext in by_ext and by_ext[ext]:
        return by_ext[ext]
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
    except OSError:
        return None
    if head.startswith(OLE_MAGIC):
        return "msg"
    if head.startswith(b"!BDN"):
        return "pst"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if ext in IGNORE_EXT:
        return None
    if re.match(rb"\d+\s*\n", head[:12]) and b"\n" in head:
        rest = head.split(b"\n", 1)[1]
        if looks_like_email(rest):
            return "emlx"
    stripped = head.lstrip(b"\xef\xbb\xbf\r\n")
    if stripped.startswith(b"From ") and looks_like_email(stripped):
        # jedna poruka sa "From " linijom ili mbox
        return "mbox"
    if looks_like_email(stripped):
        return "eml"
    return None


# --- Folder naming -----------------------------------------------------------
def _clean_component(name: str) -> str:
    for suf in (".sbd", ".mbox", ".mbx"):
        if name.lower().endswith(suf):
            name = name[: -len(suf)]
    name = name.replace("/", "-").replace("\\", "-").strip()
    return name or "_"


_APPLE_SKIP = re.compile(r"^(Messages|Data|Attachments|\d+|[0-9A-F]{8}-[0-9A-F-]{27,})$", re.I)


def dir_folder(rel_parts: tuple[str, ...], apple: bool = False) -> tuple[str, ...]:
    out = []
    for p in rel_parts:
        if apple:
            if not p.lower().endswith(".mbox") and _APPLE_SKIP.match(p):
                continue
        out.append(_clean_component(p))
    return tuple(out)


# --- Readers -----------------------------------------------------------------
def _mk(raw: bytes, folder, origin, fmt, seen=True, flagged=False, fallback=None):
    try:
        norm, h = normalize_ex(raw, fallback)
    except NotAnEmail as e:
        return Error(origin, f"nije mejl: {e}", folder, fmt)
    return Item(folder, norm, origin, seen, flagged, message_date(norm, fallback), fmt, h)


def _mtime(path) -> _dt.datetime | None:
    try:
        return _dt.datetime.fromtimestamp(os.path.getmtime(path), _dt.timezone.utc)
    except OSError:
        return None


def read_eml(path, folder, opts):
    with open(path, "rb") as f:
        raw = f.read()
    yield _mk(raw, folder, path, "eml", fallback=_mtime(path))


def read_emlx(path, folder, opts):
    with open(path, "rb") as f:
        data = f.read()
    first, rest = data.split(b"\n", 1)
    try:
        n = int(first.strip())
        raw, plist = rest[:n], rest[n:]
    except ValueError:
        raw, plist = rest, b""
    seen, flagged = True, False
    m = re.search(rb"<key>flags</key>\s*<integer>(\d+)</integer>", plist)
    if m:
        fl = int(m.group(1))
        seen = bool(fl & 1)
        flagged = bool(fl & (1 << 4))
        if fl & (1 << 1) and not opts.include_deleted:
            _bump(opts, "preskoceno_obrisano")
            return
    yield _mk(raw, folder, path, "emlx", seen, flagged, _mtime(path))


def read_msg(path, folder, opts):
    bag = msg_reader.read_msg(path)
    if not opts.include_nonmail and not mapi.is_mail_class(bag.props.get(mapi.PR_MESSAGE_CLASS)):
        _bump(opts, "preskoceno_nije_mejl")
        return
    raw = mapi.build_mime(bag, opts.x500_domain)
    seen, flagged = mapi.bag_flags(bag)
    yield _mk(raw, folder, path, "msg", seen, flagged, mapi.bag_date(bag) or _mtime(path))


_GMAIL_SYSTEM = {"important", "opened", "unread", "starred", "archived", "category personal",
                 "category social", "category promotions", "category updates",
                 "category forums", "inbox", "sent", "spam", "trash", "drafts", "chat"}


def _gmail_folder(labels: str) -> tuple[tuple[str, ...] | None, bool, bool]:
    labs = [l.strip().strip('"') for l in re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', labels) if l.strip()]
    low = [l.lower() for l in labs]
    seen = "unread" not in low
    flagged = "starred" in low
    if "chat" in low:
        return None, seen, flagged
    for sysname, target in (("trash", "Trash"), ("spam", "Junk"), ("drafts", "Drafts"),
                            ("inbox", "Inbox"), ("sent", "Sent")):
        if sysname in low:
            return (target,), seen, flagged
    for l in labs:
        if l.lower() not in _GMAIL_SYSTEM and not l.lower().startswith("category "):
            return tuple(_clean_component(p) for p in l.split("/")), seen, flagged
    return ("Archive",), seen, flagged


def read_mbox(path, folder, opts):
    mb = mailbox.mbox(path, create=False)
    try:
        for i, key in enumerate(mb.iterkeys()):
            origin = f"{path}#{i + 1}"
            try:
                raw = mb.get_bytes(key, from_=False)
            except Exception as exc:
                yield Error(origin, str(exc), folder, "mbox")
                continue
            hdr = raw[:raw.find(b"\n\n") if b"\n\n" in raw else 8192]
            seen, flagged, f = True, False, folder
            m = re.search(rb"(?im)^X-Mozilla-Status:\s*([0-9a-f]{4})", hdr)
            if m:
                st = int(m.group(1), 16)
                if st & 0x0008 and not opts.include_deleted:
                    _bump(opts, "preskoceno_obrisano")
                    continue
                seen = bool(st & 0x0001)
                flagged = bool(st & 0x0004)
            else:
                m = re.search(rb"(?im)^Status:\s*(\w+)", hdr)
                if m:
                    seen = b"R" in m.group(1)
                m2 = re.search(rb"(?im)^X-Status:\s*(\w+)", hdr)
                if m2:
                    flagged = b"F" in m2.group(1)
                    if b"D" in m2.group(1) and not opts.include_deleted:
                        _bump(opts, "preskoceno_obrisano")
                        continue
            if opts.gmail_labels:
                m = re.search(rb"(?im)^X-Gmail-Labels:(.*(?:\r?\n[ \t].*)*)", hdr)
                if m:
                    labels = re.sub(rb"\r?\n[ \t]+", b" ", m.group(1)).decode("utf-8", "replace")
                    gf, seen, flagged = _gmail_folder(labels)
                    if gf is None:
                        _bump(opts, "preskoceno_gmail_chat")
                        continue
                    f = folder[:-1] + gf if folder else gf
            raw = re.sub(rb"(?m)^>(>*From )", rb"\1", raw)  # mboxrd un-escape
            yield _mk(raw, f, origin, "mbox", seen, flagged)
    finally:
        mb.close()


def read_maildir(path, folder, opts):
    for sub, is_new in (("cur", False), ("new", True)):
        d = os.path.join(path, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            fp = os.path.join(d, name)
            if not os.path.isfile(fp):
                continue
            m = re.search(r"[:!;]2,([A-Za-z]*)$", name)  # Windows alati koriste "!" umesto ":"
            flags = m.group(1) if m else ""
            if "T" in flags and not opts.include_deleted:
                _bump(opts, "preskoceno_obrisano")
                continue
            seen = "S" in flags and not is_new
            with open(fp, "rb") as f:
                raw = f.read()
            yield _mk(raw, folder, fp, "maildir", seen, "F" in flags, _mtime(fp))


def read_pst(path, folder, opts):
    eng = pst_reader.available()
    if eng == "pypff":
        for sub, bag in pst_reader.iter_pst(path, opts.include_nonmail):
            f = folder + tuple(_clean_component(s) for s in sub)
            if isinstance(bag, Exception):
                yield Error(path, f"PST poruka: {bag}", f, "pst")
                continue
            origin = f"{path}:{'/'.join(sub)}"
            try:
                raw = mapi.build_mime(bag, opts.x500_domain)
            except Exception as exc:
                yield Error(origin, f"konverzija: {exc}", f, "pst")
                continue
            seen, flagged = mapi.bag_flags(bag)
            yield _mk(raw, f, origin, "pst", seen, flagged, mapi.bag_date(bag))
    elif eng == "readpst":
        tmp = pst_reader.readpst_extract(path)
        try:
            tops = [d for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))]
            base = os.path.join(tmp, tops[0]) if len(tops) == 1 else tmp
            yield from walk_dir(base, folder, opts)
        finally:
            pst_reader.cleanup(tmp)
    else:
        yield Error(path, "za PST/OST instaliraj: pip install libpff-python  (ili readpst / pst-utils)",
                    folder, "pst")


def read_olm(path, folder, opts):
    for sub, res in olm_reader.iter_olm(path):
        f = folder + tuple(_clean_component(s) for s in sub)
        if isinstance(res, Exception):
            yield Error(path, f"OLM poruka: {res}", f, "olm")
            continue
        raw, seen, flagged, d = res
        yield _mk(raw, f, f"{path}:{'/'.join(sub)}", "olm", seen, flagged, d)


def _safe_extract_zip(path) -> str:
    tmp = tempfile.mkdtemp(prefix="mailconv_zip_")
    root = os.path.realpath(tmp)
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            name = info.filename
            try:
                if info.flag_bits & 0x800 == 0:
                    name = name.encode("cp437").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
            target = os.path.realpath(os.path.join(tmp, name))
            if not target.startswith(root + os.sep):
                continue
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return tmp


def read_zip(path, folder, opts):
    with zipfile.ZipFile(path) as zf:
        if olm_reader.is_olm(zf):
            yield from read_olm(path, folder, opts)
            return
    tmp = _safe_extract_zip(path)
    try:
        yield from walk_dir(tmp, folder, opts)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def read_tar(path, folder, opts):
    tmp = tempfile.mkdtemp(prefix="mailconv_tar_")
    try:
        with tarfile.open(path) as tf:
            try:
                tf.extractall(tmp, filter="data")
            except TypeError:  # stariji Python
                tf.extractall(tmp)
        yield from walk_dir(tmp, folder, opts)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


READERS = {"eml": read_eml, "emlx": read_emlx, "msg": read_msg, "mbox": read_mbox,
           "pst": read_pst, "olm": read_olm, "zip": read_zip, "tar": read_tar}


def _is_maildir(d: str) -> bool:
    return os.path.isdir(os.path.join(d, "cur")) and os.path.isdir(os.path.join(d, "new"))


def read_file(path: str, folder: tuple[str, ...], opts: Options, fmt: str | None = None):
    fmt = fmt or detect(path)
    if fmt is None:
        _bump(opts, "preskoceno_nepoznat_fajl")
        return
    _bump(opts, f"fajl_{fmt}")
    if fmt == "mbox":
        stem = _clean_component(os.path.basename(path))
        if os.path.splitext(stem)[1].lower() in (".txt",):
            stem = os.path.splitext(stem)[0]
        folder = folder + (stem,)
    try:
        yield from READERS[fmt](path, folder, opts)
    except Exception as exc:
        yield Error(path, f"{type(exc).__name__}: {exc}", folder, fmt)


def walk_dir(root: str, base: tuple[str, ...], opts: Options):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        rel = os.path.relpath(dirpath, root)
        rel_parts = () if rel == "." else tuple(rel.split(os.sep))
        apple = any(p.lower().endswith(".mbox") for p in rel_parts) or any(
            f.endswith(".emlx") for f in filenames)

        if _is_maildir(dirpath):
            folder = base + dir_folder(rel_parts)
            _bump(opts, "fajl_maildir")
            yield from read_maildir(dirpath, folder, opts)
            # Maildir++ podfolderi: .Sent, .Posao.Klijenti
            plus = [d for d in dirnames if d.startswith(".") and _is_maildir(os.path.join(dirpath, d))]
            for d in plus:
                parts = tuple(_clean_component(x) for x in d[1:].split(".") if x)
                yield from read_maildir(os.path.join(dirpath, d), folder + parts, opts)
            dirnames[:] = [d for d in dirnames if d not in ("cur", "new", "tmp") and d not in plus]
            filenames = [f for f in filenames if f not in ("maildirfolder", "maildirsize", "subscriptions")
                         and not f.startswith("dovecot")]

        folder = base + dir_folder(rel_parts, apple)
        for fn in sorted(filenames):
            if fn.startswith(".") or fn.lower() in ("thumbs.db", "desktop.ini"):
                continue
            yield from read_file(os.path.join(dirpath, fn), folder, opts)


def iter_inputs(paths: list[str], opts: Options) -> Iterator[Item | Error]:
    for p in paths:
        if os.path.isdir(p):
            yield from walk_dir(p, (), opts)
        elif os.path.isfile(p):
            yield from read_file(p, (), opts)
        else:
            yield Error(p, "ne postoji")
