"""Citac Outlook for Mac .olm arhiva (ZIP sa XML porukama)."""
from __future__ import annotations

import datetime as _dt
import email.utils
import mimetypes
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from email.message import EmailMessage
from email.policy import SMTP
from typing import Iterator

from .mapi import encode_header, fix_boundaries, fold_address_list, fmt_addr, html_to_text

_MSG_DIR = "com.microsoft.__Messages"


def is_olm(zf: zipfile.ZipFile) -> bool:
    return any(_MSG_DIR in n for n in zf.namelist()[:5000])


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(el, name):
    for c in el.iter():
        if _local(c.tag) == name:
            return c
    return None


def _addresses(el, name) -> list[str]:
    node = _find(el, name)
    if node is None:
        return []
    res = []
    for a in node.iter():
        attrs = {k.rsplit("}", 1)[-1]: v for k, v in a.attrib.items()}
        addr = attrs.get("OPFContactEmailAddressAddress")
        if addr:
            res.append(fmt_addr(attrs.get("OPFContactEmailAddressName"), addr))
    return res


def _text(el, name) -> str | None:
    n = _find(el, name)
    if n is None:
        return None
    return "".join(n.itertext())


def _parse_date(s: str | None) -> _dt.datetime | None:
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    try:
        d = _dt.datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return None


def iter_olm(path: str) -> Iterator[tuple[tuple[str, ...], tuple[bytes, bool, bool, _dt.datetime | None] | Exception]]:
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        nameset = set(names)
        for n in names:
            if _MSG_DIR not in n or not n.lower().endswith(".xml"):
                continue
            parts = n.split("/")
            try:
                i = parts.index(_MSG_DIR)
            except ValueError:
                continue
            folder = tuple(parts[i + 1:-1])
            try:
                root = ET.fromstring(zf.read(n))
                yield folder, _build(root, zf, nameset, n)
            except Exception as exc:
                yield folder, exc


def _build(root, zf, nameset, xml_name):
    email_el = _find(root, "email")
    if email_el is None:
        email_el = root
    subject = _text(email_el, "OPFMessageCopySubject") or ""
    html = _text(email_el, "OPFMessageCopyHTMLBody")
    text = _text(email_el, "OPFMessageCopyBody")
    sent = _parse_date(_text(email_el, "OPFMessageCopySentTime"))
    recv = _parse_date(_text(email_el, "OPFMessageCopyReceivedTime"))
    mid = _text(email_el, "OPFMessageCopyMessageID")
    read = (_text(email_el, "OPFMessageGetIsRead") or "1").strip() not in ("0", "false")
    flagged = (_text(email_el, "OPFMessageGetFlagStatus") or "0").strip() not in ("0", "")

    body = EmailMessage(policy=SMTP)
    if not text and html:
        text = html_to_text(html)
    body.set_content(text or "", charset="utf-8", cte="base64")
    html_part = None
    if html:
        body.add_alternative(html, subtype="html", charset="utf-8", cte="base64")
        html_part = body.get_payload()[1]
    att_list = _find(email_el, "OPFMessageCopyAttachmentList")
    if att_list is not None:
        for a in att_list:
            attrs = {k.rsplit("}", 1)[-1]: v for k, v in a.attrib.items()}
            url = attrs.get("OPFAttachmentURL")
            if not url:
                continue
            cand = [url, posixpath.normpath(posixpath.join(posixpath.dirname(xml_name), url))]
            data = None
            for c in cand:
                if c in nameset:
                    data = zf.read(c)
                    break
            if data is None:
                continue
            fname = attrs.get("OPFAttachmentName") or posixpath.basename(url)
            ctype = attrs.get("OPFAttachmentContentType") or mimetypes.guess_type(fname)[0] or "application/octet-stream"
            if "/" not in ctype:
                ctype = "application/octet-stream"
            mt, st = ctype.lower().split("/", 1)
            cid = (attrs.get("OPFAttachmentContentID") or "").strip("<>")
            if cid and html_part is not None and cid in (html or ""):
                html_part.add_related(data, maintype=mt, subtype=st, cid=f"<{cid}>", filename=fname)
            else:
                body.add_attachment(data, maintype=mt, subtype=st, filename=fname)

    hdr = b""
    frm = _addresses(email_el, "OPFMessageCopyFromAddresses") or _addresses(email_el, "OPFMessageCopySenderAddress")
    if frm:
        hdr += b"From: " + frm[0].encode("ascii", "replace") + b"\r\n"
    hdr += fold_address_list("To", _addresses(email_el, "OPFMessageCopyToAddresses"))
    hdr += fold_address_list("Cc", _addresses(email_el, "OPFMessageCopyCCAddresses"))
    hdr += fold_address_list("Bcc", _addresses(email_el, "OPFMessageCopyBCCAddresses"))
    hdr += encode_header("Subject", subject)
    d = sent or recv
    if d:
        hdr += b"Date: " + email.utils.format_datetime(d).encode() + b"\r\n"
    if mid:
        mid = mid.strip()
        if not mid.startswith("<"):
            mid = f"<{mid}>"
        hdr += b"Message-ID: " + mid.encode("ascii", "replace") + b"\r\n"
    fix_boundaries(body, xml_name + (mid or "") + subject)
    body_bytes = body.as_bytes(policy=SMTP)
    body_bytes = re.sub(rb"(?im)^MIME-Version:.*\r\n", b"", body_bytes, count=1)
    return hdr + b"MIME-Version: 1.0\r\n" + body_bytes, read, flagged, recv or sent
