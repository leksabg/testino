"""MAPI property bag (MSG / PST) -> RFC 822 / MIME poruka.

Zajednicki kod za MSG i PST: oba formata su u sustini kolekcija MAPI
svojstava. Ovde su:
  * dekompresija "Compressed RTF" (MS-OXRTFCP)
  * izvlacenje HTML-a iz RTF-a (MS-OXRTFEX, \\fromhtml1)
  * pravljenje MIME poruke od svojstava, primalaca i priloga
"""
from __future__ import annotations

import datetime as _dt
import email.utils
import hashlib
import mimetypes
import re
import struct
from dataclasses import dataclass, field
from email.header import Header
from email.message import EmailMessage
from email.policy import SMTP

# --- MAPI property IDs -------------------------------------------------------
PR_MESSAGE_CLASS = 0x001A
PR_SUBJECT = 0x0037
PR_CLIENT_SUBMIT_TIME = 0x0039
PR_SENT_REPRESENTING_NAME = 0x0042
PR_SENT_REPRESENTING_EMAIL = 0x0065
PR_SENT_REPRESENTING_ADDRTYPE = 0x0064
PR_TRANSPORT_MESSAGE_HEADERS = 0x007D
PR_SENDER_NAME = 0x0C1A
PR_SENDER_ADDRTYPE = 0x0C1E
PR_SENDER_EMAIL = 0x0C1F
PR_RECIPIENT_TYPE = 0x0C15
PR_DISPLAY_BCC = 0x0E02
PR_DISPLAY_CC = 0x0E03
PR_DISPLAY_TO = 0x0E04
PR_MESSAGE_DELIVERY_TIME = 0x0E06
PR_MESSAGE_FLAGS = 0x0E07
PR_FLAG_STATUS = 0x1090
PR_BODY = 0x1000
PR_RTF_COMPRESSED = 0x1009
PR_HTML = 0x1013
PR_INTERNET_MESSAGE_ID = 0x1035
PR_IN_REPLY_TO = 0x1042
PR_REFERENCES = 0x1039
PR_CREATION_TIME = 0x3007
PR_DISPLAY_NAME = 0x3001
PR_ADDRTYPE = 0x3002
PR_EMAIL_ADDRESS = 0x3003
PR_SMTP_ADDRESS = 0x39FE
PR_ATTACH_DATA = 0x3701
PR_ATTACH_FILENAME = 0x3704
PR_ATTACH_METHOD = 0x3705
PR_ATTACH_LONG_FILENAME = 0x3707
PR_ATTACH_MIME_TAG = 0x370E
PR_ATTACH_CONTENT_ID = 0x3712
PR_ATTACH_FLAGS = 0x3714
PR_ATTACHMENT_HIDDEN = 0x7FFE
PR_INTERNET_CPID = 0x3FDE
PR_MESSAGE_CODEPAGE = 0x3FFD
PR_SENDER_SMTP_ADDRESS = 0x5D01
PR_SENT_REPRESENTING_SMTP_ADDRESS = 0x5D02

MSGFLAG_READ = 0x0001
MSGFLAG_UNSENT = 0x0008

ATTACH_EMBEDDED_MSG = 5

# Klase poruka koje nisu mejl (kontakti, kalendar, zadaci, beleske...)
NON_MAIL_CLASSES = (
    "IPM.APPOINTMENT", "IPM.CONTACT", "IPM.DISTLIST", "IPM.TASK",
    "IPM.STICKYNOTE", "IPM.ACTIVITY", "IPM.CONFIGURATION", "IPM.MICROSOFT",
    "IPM.AGGREGATION", "IPM.ABCHPERSON",
)


def is_mail_class(message_class: str | None) -> bool:
    if not message_class:
        return True
    mc = message_class.upper()
    return not any(mc == c or mc.startswith(c + ".") for c in NON_MAIL_CLASSES)


# --- Datatypes ---------------------------------------------------------------
@dataclass
class Attachment:
    props: dict
    data: bytes | None = None
    embedded: "PropBag | None" = None


@dataclass
class PropBag:
    props: dict = field(default_factory=dict)
    recipients: list = field(default_factory=list)  # list[dict]
    attachments: list = field(default_factory=list)  # list[Attachment]

    def get(self, pid, default=None):
        v = self.props.get(pid)
        return default if v is None or v == "" else v


def filetime_to_dt(value) -> _dt.datetime | None:
    if isinstance(value, _dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)
    if not isinstance(value, int) or value <= 0:
        return None
    try:
        dt = _dt.datetime(1601, 1, 1, tzinfo=_dt.timezone.utc) + _dt.timedelta(
            microseconds=value // 10
        )
    except OverflowError:
        return None
    if dt.year < 1980 or dt.year > 2100:
        return None
    return dt


def decode_mapi_string(raw: bytes, prop_type: int, codepage: int | None) -> str:
    if prop_type == 0x001F:
        return raw.decode("utf-16-le", "replace").rstrip("\x00")
    enc = codepage_to_encoding(codepage)
    try:
        return raw.decode(enc).rstrip("\x00")
    except (UnicodeDecodeError, LookupError):
        return raw.decode("cp1252", "replace").rstrip("\x00")


def codepage_to_encoding(cp: int | None) -> str:
    if not cp:
        return "cp1252"
    special = {65001: "utf-8", 20127: "ascii", 28591: "latin-1", 28592: "iso8859-2",
               28595: "iso8859-5", 1200: "utf-16-le", 50220: "iso2022_jp",
               51932: "euc_jp", 936: "gbk", 949: "cp949", 950: "big5"}
    return special.get(cp, f"cp{cp}")


# --- Compressed RTF (MS-OXRTFCP) ---------------------------------------------
_RTF_PREBUF = (
    b"{\\rtf1\\ansi\\mac\\deff0\\deftab720{\\fonttbl;}{\\f0\\fnil \\froman "
    b"\\fswiss \\fmodern \\fscript \\fdecor MS Sans SerifSymbolArialTimes New "
    b"RomanCourier{\\colortbl\\red0\\green0\\blue0\r\n\\par \\pard\\plain\\f0"
    b"\\fs20\\b\\i\\u\\tab\\tx"
)


def decompress_rtf(data: bytes) -> bytes:
    if not data or len(data) < 16:
        return b""
    comp_size, raw_size, magic, _crc = struct.unpack_from("<IIII", data, 0)
    if magic == 0x414C454D:  # "MELA" - nekompresovano
        return data[16:16 + raw_size]
    if magic != 0x75465A4C:  # "LZFu"
        # vec je cist RTF?
        return data if data.lstrip().startswith(b"{\\rtf") else b""
    dic = bytearray(4096)
    dic[: len(_RTF_PREBUF)] = _RTF_PREBUF
    wpos = len(_RTF_PREBUF)
    out = bytearray()
    pos = 16
    end = min(len(data), comp_size + 4)
    while pos < end:
        control = data[pos]
        pos += 1
        for bit in range(8):
            if pos >= end:
                break
            if control & (1 << bit):
                if pos + 1 >= end:
                    pos = end
                    break
                token = (data[pos] << 8) | data[pos + 1]
                pos += 2
                offset = token >> 4
                length = (token & 0xF) + 2
                if offset == wpos:
                    return bytes(out)
                for i in range(length):
                    b = dic[(offset + i) % 4096]
                    out.append(b)
                    dic[wpos] = b
                    wpos = (wpos + 1) % 4096
            else:
                b = data[pos]
                pos += 1
                out.append(b)
                dic[wpos] = b
                wpos = (wpos + 1) % 4096
    return bytes(out)


# --- RTF -> HTML / text ------------------------------------------------------
_RTF_TOKEN = re.compile(
    rb"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\([^a-zA-Z])|([{}])|([^\\{}\r\n]+)|[\r\n]+"
)
_SKIP_DESTS = {
    b"fonttbl", b"colortbl", b"stylesheet", b"info", b"pict", b"object",
    b"header", b"footer", b"xmlnstbl", b"listtable", b"listoverridetable",
    b"rsidtbl", b"generator", b"themedata", b"colorschememapping",
    b"latentstyles", b"datastore", b"filetbl", b"revtbl", b"pgdsctbl",
}


def rtf_to_html_or_text(rtf: bytes) -> tuple[str | None, str]:
    """Vraca (html, tekst). html je None ako RTF nije enkapsulirani HTML."""
    is_html = b"\\fromhtml" in rtf[:2048]
    m = re.search(rb"\\ansicpg(\d+)", rtf[:4096])
    enc = codepage_to_encoding(int(m.group(1))) if m else "cp1252"

    out: list[str] = []
    pending = bytearray()

    def flush():
        if pending:
            try:
                out.append(pending.decode(enc, "replace"))
            except LookupError:
                out.append(pending.decode("cp1252", "replace"))
            pending.clear()

    # state: (skip, in_htmltag, htmlrtf, uc)
    stack: list[list] = []
    state = [False, False, False, 1]
    skip_chars = 0
    new_group = False

    for m in _RTF_TOKEN.finditer(rtf):
        word, param, hexv, sym, brace, text = m.groups()
        if brace == b"{":
            stack.append(list(state))
            new_group = True
            continue
        if brace == b"}":
            flush()
            if stack:
                state = stack.pop()
            new_group = False
            continue
        first_in_group = new_group
        new_group = False

        if word is not None:
            if first_in_group and word in _SKIP_DESTS:
                state[0] = True
                continue
            if word == b"htmltag":
                state[1] = True
                continue
            if word == b"mhtmltag":
                state[0] = True
                continue
            if word == b"htmlrtf":
                state[2] = param != b"0"
                continue
            if word == b"uc":
                state[3] = int(param or 1)
                continue
            if state[0]:
                continue
            emit = (not is_html) or state[1] or not state[2]
            if word == b"u" and param is not None:
                if emit:
                    flush()
                    cp = int(param)
                    if cp < 0:
                        cp += 65536
                    out.append(chr(cp))
                skip_chars = state[3]
                continue
            if not emit:
                continue
            if word in (b"par", b"line"):
                flush()
                out.append("\r\n")
            elif word == b"tab":
                flush()
                out.append("\t")
            elif word in (b"emdash",):
                flush(); out.append("\u2014")
            elif word in (b"endash",):
                flush(); out.append("\u2013")
            elif word == b"bullet":
                flush(); out.append("\u2022")
            elif word in (b"lquote", b"rquote"):
                flush(); out.append("'")
            elif word in (b"ldblquote", b"rdblquote"):
                flush(); out.append('"')
            continue

        if sym is not None:
            if sym == b"*":
                if first_in_group:
                    # {\* ... } - nepoznata destinacija, osim htmltag
                    nxt = rtf[m.end():m.end() + 12]
                    if not (nxt.startswith(b"\\htmltag") or nxt.startswith(b"\\mhtmltag")):
                        state[0] = True
                    else:
                        new_group = True
                continue
            if state[0]:
                continue
            emit = (not is_html) or state[1] or not state[2]
            if not emit:
                continue
            if skip_chars:
                skip_chars -= 1
                continue
            if sym in (b"\\", b"{", b"}"):
                pending.extend(sym)
            elif sym == b"~":
                flush(); out.append("\u00a0")
            elif sym == b"-":
                pass
            elif sym == b"_":
                pending.extend(b"-")
            continue

        if hexv is not None:
            if state[0]:
                continue
            emit = (not is_html) or state[1] or not state[2]
            if skip_chars:
                skip_chars -= 1
                continue
            if emit:
                pending.append(int(hexv, 16))
            continue

        if text is not None:
            if state[0]:
                continue
            emit = (not is_html) or state[1] or not state[2]
            if skip_chars:
                n = min(skip_chars, len(text))
                text = text[n:]
                skip_chars -= n
            if emit and text:
                pending.extend(text)
            continue
    flush()
    result = "".join(out)
    if is_html:
        return result, html_to_text(result)
    return None, result.strip()


def html_to_text(html: str) -> str:
    import html as _h

    t = re.sub(r"(?is)<(script|style|head).*?</\1>", "", html)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</(p|div|tr|li|h\d)>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = _h.unescape(t)
    t = re.sub(r"[ \t\r\f\v]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


# --- Address helpers ---------------------------------------------------------
_X500_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-.=")


def x500_to_imceaex(legacy_dn: str, domain: str) -> str:
    """Isto kao Exchange: neresivu X500 adresu pretvara u IMCEAEX-...@domain.
    Exchange Online je cesto razresi nazad na pravog korisnika (x500 proxy)."""
    enc = []
    for ch in legacy_dn:
        if ch == "/":
            enc.append("_")
        elif ch in _X500_SAFE:
            enc.append(ch)
        else:
            for b in ch.encode("utf-8"):
                enc.append("+%02X" % b)
    return "IMCEAEX-" + "".join(enc) + "@" + domain


def pick_smtp(addrtype: str | None, addr: str | None, smtp: str | None, x500_domain: str) -> str:
    if smtp and "@" in smtp:
        return smtp.strip()
    if addr and "@" in addr and (addrtype or "SMTP").upper() in ("SMTP", ""):
        return addr.strip()
    if addr and addr.startswith("/"):
        return x500_to_imceaex(addr.strip(), x500_domain)
    if addr and "@" in addr:
        return addr.strip()
    return ""


def fmt_addr(name: str | None, addr: str) -> str:
    name = (name or "").strip().strip("'\"")
    if name and addr and name.lower() == addr.lower():
        name = ""
    if not addr:
        # Samo ime bez adrese - i dalje validna "group" sintaksa nije potrebna
        return email.utils.formataddr((name, "unknown@unknown.invalid"), charset="utf-8") if name else ""
    return email.utils.formataddr((name, addr), charset="utf-8")


def fold_address_list(name: str, addrs: list[str]) -> bytes:
    addrs = [a for a in addrs if a]
    if not addrs:
        return b""
    return (name + ": " + ",\r\n ".join(addrs) + "\r\n").encode("ascii", "replace")


def encode_header(name: str, value: str) -> bytes:
    value = re.sub(r"[\r\n]+", " ", value or "").strip()
    try:
        value.encode("ascii")
        h = Header(value, header_name=name)
    except UnicodeEncodeError:
        h = Header(value, "utf-8", header_name=name)
    return (name + ": " + h.encode(linesep="\r\n") + "\r\n").encode("ascii", "replace")


# --- Building MIME -----------------------------------------------------------
_STRIP_TRANSPORT = {
    "content-type", "content-transfer-encoding", "mime-version",
    "content-disposition", "content-id", "content-description",
    "content-language", "content-class",
}


def _transport_header_block(raw_headers: str) -> bytes:
    """Zadrzava originalne transportne zaglavlja (Received, From, To, Date...)
    ali uklanja MIME zaglavlja jer telo pravimo iznova."""
    raw_headers = raw_headers.replace("\r\n", "\n").replace("\r", "\n")
    # transportna zaglavlja ponekad sadrze i telo/MIME granice - uzmi do prve prazne linije
    raw_headers = raw_headers.split("\n\n", 1)[0]
    lines = raw_headers.split("\n")
    out: list[str] = []
    keep = False
    for line in lines:
        if not line:
            continue
        if line[0] in " \t":
            if keep:
                out.append(line)
            continue
        name = line.split(":", 1)[0].strip().lower()
        if ":" not in line or not re.fullmatch(r"[!-9;-~]+", name):
            keep = False
            continue
        keep = name not in _STRIP_TRANSPORT
        if keep:
            out.append(line)
    data = "\r\n".join(out)
    if data:
        data += "\r\n"
    try:
        return data.encode("ascii")
    except UnicodeEncodeError:
        return data.encode("utf-8")


def _has_header(block: bytes, name: str) -> bool:
    return re.search(rb"(?im)^" + re.escape(name.encode()) + rb"\s*:", block) is not None


def _attachment_filename(att: Attachment, idx: int) -> str:
    p = att.props
    name = p.get(PR_ATTACH_LONG_FILENAME) or p.get(PR_ATTACH_FILENAME) or p.get(PR_DISPLAY_NAME)
    if not name:
        ext = ""
        mt = p.get(PR_ATTACH_MIME_TAG)
        if mt:
            ext = mimetypes.guess_extension(mt) or ""
        name = f"attachment{idx}{ext}"
    return str(name).replace("\x00", "").strip() or f"attachment{idx}"


def build_mime(bag: PropBag, x500_domain: str = "unknown.invalid", _depth: int = 0) -> bytes:
    p = bag.props
    cp = p.get(PR_INTERNET_CPID) or p.get(PR_MESSAGE_CODEPAGE)

    # --- telo
    text = p.get(PR_BODY)
    html = p.get(PR_HTML)
    if isinstance(html, bytes):
        html = _decode_html_bytes(html, cp)
    if not html:
        rtf = p.get(PR_RTF_COMPRESSED)
        if isinstance(rtf, (bytes, bytearray)) and rtf:
            raw_rtf = decompress_rtf(bytes(rtf))
            if raw_rtf:
                try:
                    h, t = rtf_to_html_or_text(raw_rtf)
                except Exception:
                    h, t = None, ""
                if h:
                    html = h
                if not text and t:
                    text = t
    if isinstance(text, bytes):
        text = decode_mapi_string(text, 0x001E, cp)
    if not text and html:
        text = html_to_text(html)
    text = (text or "").replace("\r\n", "\n").replace("\x00", "")

    body = EmailMessage(policy=SMTP)
    body.set_content(text, charset="utf-8", cte="quoted-printable" if text.isascii() else "base64")
    html_part = None
    if html:
        body.add_alternative(html.replace("\x00", ""), subtype="html", charset="utf-8",
                             cte="base64")
        html_part = body.get_payload()[1]

    # --- prilozi
    for idx, att in enumerate(bag.attachments, 1):
        fname = _attachment_filename(att, idx)
        if att.embedded is not None:
            if _depth > 8:
                continue
            try:
                inner = build_mime(att.embedded, x500_domain, _depth + 1)
            except Exception:
                continue
            from email import message_from_bytes
            from email.policy import compat32
            ename = re.sub(r"\.msg$", "", fname, flags=re.I)
            if not ename.lower().endswith(".eml"):
                ename += ".eml"
            try:
                inner_msg = message_from_bytes(inner, policy=compat32)
                body.add_attachment(inner_msg, filename=ename,
                                    cte="8bit" if not inner.isascii() else None)
            except Exception:
                body.add_attachment(inner, maintype="application", subtype="octet-stream",
                                    filename=ename)
            continue
        data = att.data
        if data is None:
            continue
        mime = att.props.get(PR_ATTACH_MIME_TAG) or mimetypes.guess_type(fname)[0] or "application/octet-stream"
        if "/" not in mime:
            mime = "application/octet-stream"
        maintype, subtype = mime.lower().split("/", 1)
        cid = att.props.get(PR_ATTACH_CONTENT_ID)
        cid = str(cid).strip("<> \x00") if cid else None
        if cid and html_part is not None and cid in html:
            html_part.add_related(data, maintype=maintype, subtype=subtype, cid=f"<{cid}>",
                                  filename=fname, disposition="inline")
        else:
            body.add_attachment(data, maintype=maintype, subtype=subtype, filename=fname)

    seed = repr(sorted((k, v if not isinstance(v, bytes) else hashlib.sha1(v).hexdigest())
                       for k, v in p.items() if k < 0x8000)) + str(_depth)
    fix_boundaries(body, seed)
    body_bytes = body.as_bytes(policy=SMTP)
    # body_bytes vec ima MIME zaglavlja (Content-Type...) + telo

    # --- zaglavlja
    hdr = b""
    transport = p.get(PR_TRANSPORT_MESSAGE_HEADERS)
    if isinstance(transport, bytes):
        transport = transport.decode("utf-8", "replace")
    if transport and ":" in transport:
        hdr = _transport_header_block(transport)
    synth = synth_headers(bag, x500_domain)
    # dopuni sta fali (npr. draft ili Sent Items bez transportnih zaglavlja)
    for name, line in synth:
        if not _has_header(hdr, name):
            hdr += line
    # izbaci MIME-Version iz tela (bice dodat jednom)
    body_bytes = re.sub(rb"(?im)^MIME-Version:.*\r\n", b"", body_bytes, count=1)
    return hdr + b"MIME-Version: 1.0\r\n" + body_bytes


def fix_boundaries(msg, seed: str):
    """Deterministicke MIME granice: ista ulazna poruka -> identicni bajtovi,
    pa ponovno pokretanje ne pravi duplikate."""
    h = hashlib.sha1(seed.encode("utf-8", "replace")).hexdigest()[:24]
    for i, part in enumerate(msg.walk()):
        if part.is_multipart():
            part.set_boundary(f"----=_mc_{h}_{i}")


def _decode_html_bytes(data: bytes, cp) -> str:
    head = data[:2048].decode("ascii", "ignore")
    m = re.search(r"""charset\s*=\s*["']?([A-Za-z0-9_\-]+)""", head, re.I)
    candidates = []
    if m:
        candidates.append(m.group(1))
    if cp:
        candidates.append(codepage_to_encoding(cp))
    candidates += ["utf-8", "cp1252"]
    for enc in candidates:
        try:
            s = data.decode(enc)
            # meta charset vise nije tacan jer cuvamo kao utf-8
            return re.sub(r"""(charset\s*=\s*["']?)[A-Za-z0-9_\-]+""", r"\1utf-8", s, count=1, flags=re.I)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def synth_headers(bag: PropBag, x500_domain: str) -> list[tuple[str, bytes]]:
    p = bag.props
    res: list[tuple[str, bytes]] = []

    # From
    s_name = p.get(PR_SENT_REPRESENTING_NAME) or p.get(PR_SENDER_NAME)
    s_addr = pick_smtp(p.get(PR_SENT_REPRESENTING_ADDRTYPE), p.get(PR_SENT_REPRESENTING_EMAIL),
                       p.get(PR_SENT_REPRESENTING_SMTP_ADDRESS), x500_domain)
    if not s_addr:
        s_addr = pick_smtp(p.get(PR_SENDER_ADDRTYPE), p.get(PR_SENDER_EMAIL),
                           p.get(PR_SENDER_SMTP_ADDRESS), x500_domain)
    if s_name or s_addr:
        res.append(("From", b"From: " + fmt_addr(s_name, s_addr).encode("ascii", "replace") + b"\r\n"))

    # Recipients
    groups = {1: [], 2: [], 3: []}
    for r in bag.recipients:
        rtype = r.get(PR_RECIPIENT_TYPE, 1)
        try:
            rtype = int(rtype) & 0xF
        except (TypeError, ValueError):
            rtype = 1
        addr = pick_smtp(r.get(PR_ADDRTYPE), r.get(PR_EMAIL_ADDRESS), r.get(PR_SMTP_ADDRESS), x500_domain)
        formatted = fmt_addr(r.get(PR_DISPLAY_NAME), addr)
        if formatted:
            groups.setdefault(rtype, []).append(formatted)
    if not bag.recipients:
        # samo prikazna imena
        for rtype, pid in ((1, PR_DISPLAY_TO), (2, PR_DISPLAY_CC)):
            disp = p.get(pid)
            if disp:
                groups[rtype] = [fmt_addr(n.strip(), "") for n in str(disp).split(";") if n.strip()]
    for rtype, name in ((1, "To"), (2, "Cc"), (3, "Bcc")):
        line = fold_address_list(name, groups.get(rtype, []))
        if line:
            res.append((name, line))

    subj = p.get(PR_SUBJECT)
    if subj is not None:
        res.append(("Subject", encode_header("Subject", str(subj))))

    dt = (filetime_to_dt(p.get(PR_CLIENT_SUBMIT_TIME))
          or filetime_to_dt(p.get(PR_MESSAGE_DELIVERY_TIME))
          or filetime_to_dt(p.get(PR_CREATION_TIME)))
    if dt:
        res.append(("Date", b"Date: " + email.utils.format_datetime(dt).encode() + b"\r\n"))

    mid = p.get(PR_INTERNET_MESSAGE_ID)
    if mid:
        mid = str(mid).strip()
        if not mid.startswith("<"):
            mid = "<" + mid.strip("<>") + ">"
        res.append(("Message-ID", b"Message-ID: " + mid.encode("ascii", "replace") + b"\r\n"))
    irt = p.get(PR_IN_REPLY_TO)
    if irt:
        res.append(("In-Reply-To", b"In-Reply-To: " + str(irt).strip().encode("ascii", "replace") + b"\r\n"))
    refs = p.get(PR_REFERENCES)
    if refs:
        refs = " ".join(str(refs).split())
        res.append(("References", b"References: " + refs.encode("ascii", "replace") + b"\r\n"))
    return res


def bag_flags(bag: PropBag) -> tuple[bool, bool]:
    """(procitano, oznaceno zastavicom)"""
    flags = bag.props.get(PR_MESSAGE_FLAGS)
    seen = True
    if isinstance(flags, int):
        seen = bool(flags & MSGFLAG_READ)
    fs = bag.props.get(PR_FLAG_STATUS)
    flagged = isinstance(fs, int) and fs == 2
    return seen, flagged


def bag_date(bag: PropBag) -> _dt.datetime | None:
    p = bag.props
    return (filetime_to_dt(p.get(PR_MESSAGE_DELIVERY_TIME))
            or filetime_to_dt(p.get(PR_CLIENT_SUBMIT_TIME))
            or filetime_to_dt(p.get(PR_CREATION_TIME)))


def stable_id(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()
