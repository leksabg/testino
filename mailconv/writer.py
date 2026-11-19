"""Izlaz na disk: EML stablo foldera ili MBOX fajlovi po folderu."""
from __future__ import annotations

import os
import re
import time

from .normalize import get_header_str
from .sources import Item

_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}


def safe_name(s: str, maxlen: int = 60) -> str:
    s = _BAD.sub("_", s).strip(" .")
    s = re.sub(r"\s+", " ", s)[:maxlen].strip(" .")
    if not s or s.upper() in _RESERVED:
        s = "_" + s
    return s


class EmlWriter:
    def __init__(self, out_dir: str):
        self.out = out_dir
        self.counters: dict[str, int] = {}
        self.seen: set[str] = set()

    def write(self, it: Item) -> str:
        d = os.path.join(self.out, *[safe_name(p, 80) for p in it.folder]) if it.folder else self.out
        os.makedirs(d, exist_ok=True)
        n = self.counters.get(d, 0) + 1
        self.counters[d] = n
        subj = safe_name(get_header_str(it.raw, "Subject") or "bez naslova")
        path = os.path.join(d, f"{n:06d} {subj}.eml")
        with open(path, "wb") as f:
            f.write(it.raw)
        if it.date:
            ts = it.date.timestamp()
            os.utime(path, (ts, ts))
        return path

    def close(self):
        pass


class MboxWriter:
    def __init__(self, out_dir: str):
        self.out = out_dir
        self.files: dict[tuple, object] = {}

    def _fh(self, folder):
        if folder not in self.files:
            parts = [safe_name(p, 80) for p in folder] or ["INBOX"]
            d = os.path.join(self.out, *parts[:-1])
            os.makedirs(d, exist_ok=True)
            self.files[folder] = open(os.path.join(d, parts[-1] + ".mbox"), "ab")
        return self.files[folder]

    def write(self, it: Item) -> str:
        f = self._fh(it.folder)
        t = time.asctime(time.gmtime(it.date.timestamp() if it.date else time.time()))
        body = it.raw.replace(b"\r\n", b"\n")
        body = re.sub(rb"(?m)^(>*From )", rb">\1", body)  # mboxrd
        status = b"Status: RO\n" if it.seen else b"Status: O\n"
        hdr_end = body.find(b"\n\n")
        if hdr_end >= 0:
            body = body[:hdr_end + 1] + status + body[hdr_end + 1:]
        f.write(b"From MAILER-DAEMON " + t.encode() + b"\n" + body)
        if not body.endswith(b"\n"):
            f.write(b"\n")
        f.write(b"\n")
        return f.name

    def close(self):
        for f in self.files.values():
            f.close()
