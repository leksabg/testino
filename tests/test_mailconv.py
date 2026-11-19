import datetime as dt
import email
import os
from email import policy

from mailconv import imap_upload as iu
from mailconv import mapi
from mailconv.normalize import normalize, normalize_ex, message_date
from mailconv.sources import Options, iter_inputs, Item


def test_utf7_roundtrip():
    for s in ["Neželjena pošta", "Poslate stavke", "A&B", "Ђорђе Ćirić", "INBOX"]:
        enc = iu.imap_utf7_encode(s)
        assert enc.isascii()
        assert iu.imap_utf7_decode(enc) == s
    assert iu.imap_utf7_encode("Neželjena pošta") == "Ne&AX4-eljena po&AWE-ta"


def test_normalize_fixes():
    raw = b"\xef\xbb\xbfFrom foo@bar Mon Jan  1 00:00:00 2024\nFrom: a@b.c\nSubject: x\nbroken line\n\nbody\n"
    out = normalize(raw, dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc))
    assert b"\n" not in out.replace(b"\r\n", b"")
    assert out.startswith(b"From: a@b.c\r\n")
    assert b"Subject: x\r\n broken line\r\n" in out
    assert b"\r\nDate: Wed, 01 Jan 2020" in out
    assert b"Message-ID: <" in out


def test_content_hash_ignores_synthetic_headers():
    raw = b"From: a@b.c\nSubject: x\n\nbody\n"
    _, h1 = normalize_ex(raw, dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc))
    _, h2 = normalize_ex(raw, dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc))
    assert h1 == h2


def test_message_date_prefers_received():
    raw = normalize(b"Received: from x by y; Tue, 4 Nov 2025 10:00:00 +0000\nDate: Mon, 3 Nov 2025 10:00:00 +0000\nFrom: a@b.c\n\nx\n")
    assert message_date(raw).day == 4


def test_rtf_deencapsulation():
    rtf = (rb"{\rtf1\ansi\ansicpg1250\fromhtml1 {\fonttbl{\f0 Arial;}}"
           rb"{\*\htmltag64 <html>}{\*\htmltag <body>}\htmlrtf {\htmlrtf0 Zdravo \'9aefe\par}"
           rb"{\*\htmltag </body></html>}}")
    html, text = mapi.rtf_to_html_or_text(rtf)
    assert html.startswith("<html><body>")
    assert "Zdravo šefe" in html
    assert html.rstrip().endswith("</body></html>")


def test_rtf_mela_uncompressed():
    import struct
    payload = b"{\\rtf1 hello}"
    data = struct.pack("<IIII", len(payload) + 12, len(payload), 0x414C454D, 0) + payload
    assert mapi.decompress_rtf(data) == payload


def test_build_mime_from_propbag():
    bag = mapi.PropBag(props={
        mapi.PR_SUBJECT: "Račun", mapi.PR_BODY: "telo", mapi.PR_SENDER_NAME: "Pera",
        mapi.PR_SENDER_EMAIL: "pera@x.rs", mapi.PR_SENDER_ADDRTYPE: "SMTP",
        mapi.PR_CLIENT_SUBMIT_TIME: 133000000000000000, mapi.PR_MESSAGE_FLAGS: 1,
    }, recipients=[{mapi.PR_DISPLAY_NAME: "Ana", mapi.PR_SMTP_ADDRESS: "ana@x.rs", mapi.PR_RECIPIENT_TYPE: 1}],
       attachments=[mapi.Attachment(props={mapi.PR_ATTACH_LONG_FILENAME: "a.pdf"}, data=b"%PDF")])
    raw = mapi.build_mime(bag)
    assert raw == mapi.build_mime(bag)  # deterministicno
    m = email.message_from_bytes(raw, policy=policy.default)
    assert m["Subject"] == "Račun"
    assert m["To"] == "Ana <ana@x.rs>"
    assert "pera@x.rs" in m["From"]
    assert [p.get_filename() for p in m.iter_attachments()] == ["a.pdf"]
    assert mapi.bag_flags(bag) == (True, False)


def test_x500_address():
    a = mapi.pick_smtp("EX", "/O=ORG/OU=X/CN=RECIPIENTS/CN=pera", None, "firma.rs")
    assert a == "IMCEAEX-_O=ORG_OU=X_CN=RECIPIENTS_CN=pera@firma.rs"


def _write(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


def test_sources_all_formats(tmp_path):
    t = str(tmp_path)
    _write(f"{t}/A/B/x.eml", b"From: a@b.c\nSubject: eml\n\nx\n")
    _write(f"{t}/tb/Inbox", b"From - x\nX-Mozilla-Status: 0001\nFrom: a@b.c\nSubject: r\n\nx\n\n"
                            b"From - x\nX-Mozilla-Status: 0009\nFrom: a@b.c\nSubject: del\n\nx\n")
    _write(f"{t}/tb/Inbox.sbd/Sub", b"From - x\nFrom: a@b.c\nSubject: s\n\nx\n")
    sep = "!" if os.name == "nt" else ":"
    _write(f"{t}/md/cur/1{sep}2,S", b"From: a@b.c\nSubject: md\n\nx\n")
    os.makedirs(f"{t}/md/new"); os.makedirs(f"{t}/md/tmp")
    m = b"From: a@b.c\nSubject: emlx\n\nx\n"
    _write(f"{t}/apple/Box.mbox/Messages/1.emlx", str(len(m)).encode() + b"\n" + m + b"<plist/>")
    _write(f"{t}/noext", b"Return-Path: <a@b.c>\nFrom: a@b.c\nSubject: noext\n\nx\n")
    _write(f"{t}/notes.txt", b"just text")
    opts = Options()
    items = [i for i in iter_inputs([t], opts) if isinstance(i, Item)]
    got = {(i.folder, i.raw.split(b"Subject: ")[1].split(b"\r\n")[0].decode(), i.seen) for i in items}
    assert got == {
        (("A", "B"), "eml", True), (("tb", "Inbox"), "r", True), (("tb", "Inbox", "Sub"), "s", True),
        (("md",), "md", True), (("apple", "Box"), "emlx", True), ((), "noext", True),
    }
    assert opts.stats["preskoceno_obrisano"] == 1


def test_folder_map_special():
    fm = iu.FolderMap("", True, lambda *_: None)
    fm.special = {"\\sent": "Poslate stavke", "\\inbox": "INBOX"}
    assert fm.logical(("Sent Items", "2020")) == ("Poslate stavke", "2020")
    assert fm.logical(("inbox",)) == ("INBOX",)
    assert fm.logical(()) == ("INBOX",)
    assert fm.logical(("a/b",)) == ("a-b",)
    fm2 = iu.FolderMap("Uvoz/2024", True, lambda *_: None)
    assert fm2.logical(("Sent",)) == ("Uvoz", "2024", "Sent")


def test_parse_list():
    data = [b'(\\HasNoChildren \\Sent) "/" "Sent Items"', b'(\\HasChildren) "/" INBOX',
            (b'(\\HasNoChildren) "/" {5}', b'Weird')]
    res = iu.parse_list(data)
    assert res[0][2] == "Sent Items" and "\\sent" in res[0][0]
    assert res[1][2] == "INBOX"
    assert res[2][2] == "Weird"
