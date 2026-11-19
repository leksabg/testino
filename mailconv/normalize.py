"""Popravka "sirove" RFC 822 poruke pre uvoza u Exchange Online.

Princip: sto manje diranja. Ne prepakujemo poruku kroz email biblioteku
(to cesto osteti potpise, kodiranja i priloge), vec radimo bajt-operacije:
  * CRLF zavrseci linija (IMAP to zahteva, Exchange odbija "gole" LF)
  * uklanjanje BOM-a, NUL bajtova, mbox "From " linije i mbox status zaglavlja
  * popravka neispravnih linija u zaglavlju
  * dodavanje Date / Message-ID ako fale (inace Outlook pogresno sortira)
"""
from __future__ import annotations

import datetime as _dt
import email.utils
import hashlib
import re
from email.header import decode_header, make_header

_HEADER_LINE = re.compile(rb"^[!-9;-~]+[ \t]*:")
_STRIP_HEADERS = {
    b"x-mozilla-status", b"x-mozilla-status2", b"x-mozilla-keys", b"status",
    b"x-status", b"x-uid", b"content-length", b"lines", b"x-keywords",
    b"x-gmail-labels", b"x-gm-thrid", b"x-apple-mail-remote-attachments",
}


class NotAnEmail(ValueError):
    pass


def looks_like_email(head: bytes) -> bool:
    head = head.lstrip(b"\xef\xbb\xbf\r\n\t ")
    if head.startswith(b"From "):
        head = head.split(b"\n", 1)[-1]
    lines = head.replace(b"\r\n", b"\n").split(b"\n")[:40]
    n_hdr = 0
    known = 0
    for ln in lines:
        if not ln.strip():
            break
        if ln[:1] in (b" ", b"\t"):
            continue
        if _HEADER_LINE.match(ln):
            n_hdr += 1
            name = ln.split(b":", 1)[0].strip().lower()
            if name in (b"from", b"to", b"subject", b"date", b"received", b"message-id",
                        b"return-path", b"mime-version", b"delivered-to", b"x-mailer",
                        b"content-type", b"reply-to", b"cc", b"sender"):
                known += 1
        else:
            return False
    return n_hdr >= 2 and known >= 1


def split_message(raw: bytes) -> tuple[bytes, bytes]:
    i = raw.find(b"\r\n\r\n")
    if i < 0:
        return raw, b""
    return raw[: i + 2], raw[i + 4:]


def normalize(raw: bytes, fallback_date: _dt.datetime | None = None) -> bytes:
    return normalize_ex(raw, fallback_date)[0]


def normalize_ex(raw: bytes, fallback_date: _dt.datetime | None = None) -> tuple[bytes, str]:
    """Vraca (poruka, hash_sadrzaja). Hash se racuna PRE dodavanja vestackih
    Date/Message-ID zaglavlja, pa ista poruka iz dva izvora ima isti hash."""
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    raw = raw.replace(b"\x00", b"")
    raw = raw.lstrip(b"\r\n\t ")
    if raw.startswith(b"From "):
        nl = raw.find(b"\n")
        raw = raw[nl + 1:] if nl >= 0 else b""
    raw = re.sub(rb"\r\n|\r|\n", b"\r\n", raw)
    if not raw.strip():
        raise NotAnEmail("prazna poruka")

    header, body = split_message(raw)
    if not body and not header.endswith(b"\r\n"):
        header += b"\r\n"

    lines = header.split(b"\r\n")
    if lines and lines[-1] == b"":
        lines.pop()
    out: list[bytes] = []
    skip = False
    for ln in lines:
        if ln[:1] in (b" ", b"\t"):
            if not skip and out:
                out.append(ln)
            continue
        if not ln.strip():
            continue
        if _HEADER_LINE.match(ln):
            name = ln.split(b":", 1)[0].strip().lower()
            skip = name in _STRIP_HEADERS
            if not skip:
                # "Name : value" -> "Name: value"
                n, v = ln.split(b":", 1)
                out.append(n.rstrip() + b":" + v)
            continue
        # neispravna linija u zaglavlju -> nastavak prethodnog
        if out:
            out.append(b" " + ln)
        else:
            raise NotAnEmail("ne pocinje zaglavljem")
    if not out:
        raise NotAnEmail("nema zaglavlja")

    hdr = b"\r\n".join(out) + b"\r\n"
    content_hash = hashlib.sha1(hdr + b"\r\n" + body.rstrip(b"\r\n")).hexdigest()
    if not _get_header(hdr, b"date"):
        d = received_date(hdr) or fallback_date
        if d is None:
            d = _dt.datetime.now(_dt.timezone.utc)
        hdr += b"Date: " + email.utils.format_datetime(_aware(d)).encode() + b"\r\n"
    if not _get_header(hdr, b"message-id"):
        h = hashlib.sha1(hdr + body[:65536]).hexdigest()
        hdr += b"Message-ID: <" + h.encode() + b"@mailconv.invalid>\r\n"
    if body and not body.endswith(b"\r\n"):
        body += b"\r\n"
    return hdr + b"\r\n" + body, content_hash


def _aware(d: _dt.datetime) -> _dt.datetime:
    return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)


def _get_header(hdr: bytes, name: bytes) -> bytes | None:
    m = re.search(rb"(?im)^" + re.escape(name) + rb"[ \t]*:(.*(?:\r\n[ \t].*)*)", hdr)
    if not m:
        return None
    return re.sub(rb"\r\n[ \t]+", b" ", m.group(1)).strip()


def get_header_str(raw: bytes, name: str) -> str:
    header, _ = split_message(raw)
    v = _get_header(header, name.lower().encode())
    if v is None:
        return ""
    s = v.decode("utf-8", "replace")
    try:
        return str(make_header(decode_header(s)))
    except Exception:
        return s


def _parse_date(v: bytes | str | None) -> _dt.datetime | None:
    if not v:
        return None
    if isinstance(v, bytes):
        v = v.decode("ascii", "replace")
    try:
        d = email.utils.parsedate_to_datetime(v.strip())
    except (TypeError, ValueError, IndexError):
        return None
    if d is None:
        return None
    d = _aware(d)
    if d.year < 1980 or d > _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=2):
        return None
    return d


def received_date(hdr: bytes) -> _dt.datetime | None:
    for m in re.finditer(rb"(?im)^received[ \t]*:((?:.*)(?:\r\n[ \t].*)*)", hdr):
        v = re.sub(rb"\r\n[ \t]+", b" ", m.group(1))
        if b";" in v:
            d = _parse_date(v.rsplit(b";", 1)[1])
            if d:
                return d  # prvi Received = poslednji hop = vreme prijema
    return None


def message_date(raw: bytes, fallback: _dt.datetime | None = None) -> _dt.datetime:
    header, _ = split_message(raw)
    return (received_date(header) or _parse_date(_get_header(header, b"date"))
            or (fallback and _aware(fallback)) or _dt.datetime.now(_dt.timezone.utc))
