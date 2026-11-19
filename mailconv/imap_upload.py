"""Uvoz poruka u (shared) mailbox preko IMAP APPEND.

Zasto IMAP a ne Graph/PST:
  * APPEND cuva originalnu MIME poruku bajt-za-bajt (potpisi, prilozi, zaglavlja)
  * poruke NISU "draft" (Graph MIME upload pravi draftove)
  * datum prijema (INTERNALDATE) i procitano/zastavica se cuvaju
  * nema PST-a, nema Purview import job-a, nema Azure storage-a
"""
from __future__ import annotations

import base64
import datetime as _dt
import imaplib
import queue
import re
import socket
import ssl
import threading
import time

from .sources import Error, Item
from .state import State

imaplib._MAXLINE = 10_000_000  # Exchange ume da vrati dugacke LIST odgovore


# --- modified UTF-7 (RFC 3501) za imena foldera sa č ć š ž đ -------------------
def imap_utf7_encode(s: str) -> str:
    out, buf = [], []

    def flush():
        if buf:
            b = base64.b64encode("".join(buf).encode("utf-16-be")).decode().rstrip("=")
            out.append("&" + b.replace("/", ",") + "-")
            buf.clear()

    for ch in s:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def imap_utf7_decode(s: str) -> str:
    def rep(m):
        b = m.group(1)
        if not b:
            return "&"
        b = b.replace(",", "/")
        b += "=" * (-len(b) % 4)
        return base64.b64decode(b).decode("utf-16-be", "replace")

    return re.sub(r"&([A-Za-z0-9+,]*)-", rep, s)


def quote(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


_LIST_RE = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?P<delim>"[^"]*"|NIL)\s+(?P<name>.+)$')


def parse_list(data) -> list[tuple[set, str, str]]:
    res = []
    items = list(data or [])
    i = 0
    while i < len(items):
        it = items[i]
        if isinstance(it, tuple):  # literal ime
            line, lit = it
            m = _LIST_RE.match(line.strip())
            if m:
                res.append((set(m.group("flags").decode().lower().split()),
                            m.group("delim").decode().strip('"'), lit.decode("utf-8", "replace")))
        elif it:
            m = _LIST_RE.match(it.strip())
            if m:
                name = m.group("name").decode("utf-8", "replace").strip()
                if name.startswith('"'):
                    name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
                res.append((set(m.group("flags").decode().lower().split()),
                            m.group("delim").decode().strip('"'), name))
        i += 1
    return res


SPECIAL_ALIASES = {
    "\\inbox": {"inbox", "primljeno", "primljena pošta", "primljena posta", "ulazna pošta",
                "ulazna posta", "prijemno sanduče", "prijemno sanduce", "dolazna pošta", "dolazna posta"},
    "\\sent": {"sent", "sent items", "sent mail", "sent messages", "poslato", "poslate stavke",
               "poslata pošta", "poslata posta", "poslano", "poslate poruke", "odlazna pošta"},
    "\\drafts": {"drafts", "draft", "nacrti", "radne verzije", "skice"},
    "\\trash": {"trash", "deleted items", "deleted messages", "deleted", "bin", "otpad",
                "izbrisane stavke", "obrisane stavke", "obrisano", "korpa", "smeće", "smece"},
    "\\junk": {"junk", "spam", "junk email", "junk e-mail", "bulk mail", "neželjena pošta",
               "nezeljena posta", "neželjena e-pošta", "neželjeno"},
    "\\archive": {"archive", "arhiva", "archives"},
}
DEFAULT_SPECIAL_NAMES = {"\\inbox": "INBOX", "\\sent": "Sent Items", "\\drafts": "Drafts",
                         "\\trash": "Deleted Items", "\\junk": "Junk Email", "\\archive": "Archive"}


class Connection:
    def __init__(self, cfg, token_provider=None):
        self.cfg = cfg
        self.tp = token_provider
        self.conn: imaplib.IMAP4 | None = None
        self.since = 0.0

    def open(self, force_token=False):
        self.close()
        c = self.cfg
        ctx = ssl.create_default_context()
        if c.starttls or not c.ssl:
            conn = imaplib.IMAP4(c.host, c.port, timeout=c.timeout)
            if c.starttls:
                conn.starttls(ctx)
        else:
            conn = imaplib.IMAP4_SSL(c.host, c.port, ssl_context=ctx, timeout=c.timeout)
        if c.auth == "password":
            if not c.password:
                raise SystemExit("Za --auth password treba --password ili env MAILCONV_PASSWORD")
            user = c.login_user or c.mailbox
            conn.login(user, c.password)
        else:
            token = self.tp.get(force=force_token)
            auth = f"user={c.mailbox}\x01auth=Bearer {token}\x01\x01".encode()
            conn.authenticate("XOAUTH2", lambda _: auth)
        self.conn = conn
        self.since = time.time()
        return conn

    def close(self):
        if self.conn is not None:
            try:
                self.conn.logout()
            except Exception:
                pass
        self.conn = None

    def ensure(self):
        # tokeni traju ~60-90 min; osvezi konekciju na 45 min
        if self.conn is None or (self.cfg.auth != "password" and time.time() - self.since > 45 * 60):
            self.open()
        return self.conn


class FolderMap:
    def __init__(self, root: str, special_map: bool, log):
        self.root = tuple(p for p in re.split(r"[/\\]", root or "") if p)
        self.special_map = special_map
        self.log = log
        self.delim = "/"
        self.existing: dict[str, str] = {}  # lower(unicode path) -> imap ime (utf7)
        self.special: dict[str, str] = {}   # \sent -> unicode path
        self.cache: dict[tuple, str] = {}
        self.lock = threading.Lock()

    def load(self, conn: imaplib.IMAP4):
        typ, data = conn.list('""', "*")
        if typ != "OK":
            raise RuntimeError(f"LIST nije uspeo: {data}")
        for flags, delim, name in parse_list(data):
            if delim and delim != "NIL":
                self.delim = delim
            uni = imap_utf7_decode(name)
            self.existing[uni.lower()] = name
            for f in flags:
                if f in DEFAULT_SPECIAL_NAMES and f not in self.special:
                    self.special[f] = uni
            if uni.upper() == "INBOX":
                self.special["\\inbox"] = uni
        # bez SPECIAL-USE flagova: prepoznaj po engleskom imenu
        for key, default in DEFAULT_SPECIAL_NAMES.items():
            if key not in self.special and default.lower() in self.existing:
                self.special[key] = imap_utf7_decode(self.existing[default.lower()])

    def logical(self, folder: tuple[str, ...]) -> tuple[str, ...]:
        parts = [p.replace(self.delim, "-").strip() or "_" for p in folder]
        if not self.root and self.special_map and parts:
            first = parts[0].lower()
            for key, aliases in SPECIAL_ALIASES.items():
                if first in aliases:
                    target = self.special.get(key) or DEFAULT_SPECIAL_NAMES[key]
                    parts = target.split(self.delim) + parts[1:]
                    break
        parts = list(self.root) + parts
        if not parts:
            parts = [self.special.get("\\inbox", "INBOX")]
        return tuple(parts)

    def display(self, folder: tuple[str, ...]) -> str:
        return self.delim.join(self.logical(folder))

    def resolve(self, conn: imaplib.IMAP4 | None, folder: tuple[str, ...], dry_run=False) -> str:
        """Vraca IMAP ime (modified UTF-7) i pravi foldere koji ne postoje."""
        key = tuple(folder)
        if key in self.cache:
            return self.cache[key]
        with self.lock:
            if key in self.cache:
                return self.cache[key]
            parts = self.logical(folder)
            path_parts: list[str] = []
            imap_name = ""
            for p in parts:
                path_parts.append(p)
                uni = self.delim.join(path_parts)
                ex = self.existing.get(uni.lower())
                if ex is not None:
                    imap_name = ex
                    # zadrzi tacno ime postojeceg foldera (velika/mala slova)
                    path_parts = imap_utf7_decode(ex).split(self.delim)
                    continue
                imap_name = imap_utf7_encode(uni)
                if not dry_run:
                    typ, data = conn.create(quote(imap_name))
                    if typ != "OK" and b"exist" not in b" ".join(d or b"" for d in data).lower():
                        raise RuntimeError(f"ne mogu da napravim folder '{uni}': {data}")
                    try:
                        conn.subscribe(quote(imap_name))
                    except Exception:
                        pass
                    self.log(f"  + napravljen folder: {uni}")
                self.existing[uni.lower()] = imap_name
            self.cache[key] = imap_name
            return imap_name


def _flags(item: Item) -> str | None:
    f = []
    if item.seen:
        f.append("\\Seen")
    if item.flagged:
        f.append("\\Flagged")
    return "(" + " ".join(f) + ")" if f else None


_RETRYABLE = re.compile(r"throttl|try again|unavailable|server busy|timeout|temporar|"
                        r"backoff|too many|limit|internal error|\[UNAVAILABLE\]", re.I)


class Uploader:
    def __init__(self, cfg, token_provider, state: State, folders: FolderMap, log, report):
        self.cfg = cfg
        self.tp = token_provider
        self.state = state
        self.folders = folders
        self.log = log
        self.report = report
        self.stats = {"uvezeno": 0, "preskoceno_vec_uvezeno": 0, "greska": 0, "bajtova": 0}
        self.slock = threading.Lock()
        self.inflight: set[str] = set()

    def _inc(self, k, n=1):
        with self.slock:
            self.stats[k] = self.stats.get(k, 0) + n

    def connect_and_list(self):
        c = Connection(self.cfg, self.tp)
        conn = c.open()
        self.folders.load(conn)
        return c

    def _worker(self, q: "queue.Queue"):
        c = Connection(self.cfg, self.tp)
        try:
            while True:
                it = q.get()
                if it is None:
                    return
                try:
                    self._upload_one(c, it)
                except Exception as exc:  # ne sme da ubije worker
                    self._fail(it, f"{type(exc).__name__}: {exc}")
                finally:
                    q.task_done()
        finally:
            c.close()

    def _fail(self, it: Item, msg: str):
        self._inc("greska")
        self.report(it.origin, self.folders.display(it.folder), msg)
        self.log(f"  ! GRESKA {it.origin}: {msg}")

    def _upload_one(self, c: Connection, it: Item):
        target_disp = self.folders.display(it.folder)
        key = self.state.key(it.content_hash, target_disp)
        with self.slock:
            if key in self.inflight or self.state.done(key):
                self.stats["preskoceno_vec_uvezeno"] += 1
                return
            self.inflight.add(key)
        try:
            self._append(c, it, key, target_disp)
        finally:
            with self.slock:
                self.inflight.discard(key)

    def _append(self, c: "Connection", it: Item, key: str, target_disp: str):
        if len(it.raw) > self.cfg.max_size:
            self._fail(it, f"poruka je {len(it.raw) / 1048576:.1f} MB, preko limita "
                           f"{self.cfg.max_size / 1048576:.0f} MB (Set-Mailbox -MaxReceiveSize)")
            return
        date = imaplib.Time2Internaldate(it.date or _dt.datetime.now(_dt.timezone.utc))
        attempt = 0
        while True:
            attempt += 1
            try:
                conn = c.ensure()
                name = self.folders.resolve(conn, it.folder)
                typ, data = conn.append(quote(name), _flags(it), date, it.raw)
                if typ == "OK":
                    self.state.mark(key, target_disp, it.origin, len(it.raw))
                    self._inc("uvezeno")
                    self._inc("bajtova", len(it.raw))
                    return
                text = b" ".join(d if isinstance(d, bytes) else b"" for d in (data or [])).decode("utf-8", "replace")
                if "TRYCREATE" in text.upper():
                    with self.folders.lock:
                        self.folders.cache.pop(tuple(it.folder), None)
                        for k in list(self.folders.existing):
                            if self.folders.existing[k] == name:
                                del self.folders.existing[k]
                    raise imaplib.IMAP4.abort("TRYCREATE: " + text)
                if _RETRYABLE.search(text) and attempt <= self.cfg.retries:
                    raise imaplib.IMAP4.abort(text)
                self._fail(it, f"server odbio: {text}")
                return
            except (imaplib.IMAP4.abort, OSError, socket.timeout, ssl.SSLError, EOFError) as exc:
                if attempt > self.cfg.retries:
                    self._fail(it, f"posle {attempt - 1} pokusaja: {exc}")
                    return
                wait = min(120, 2 ** attempt)
                self.log(f"  ~ {type(exc).__name__}: {str(exc)[:150]} -> ponovo za {wait}s")
                c.close()
                time.sleep(wait)
                if "AUTHENTICATE" in str(exc).upper():
                    try:
                        c.open(force_token=True)
                    except Exception:
                        pass
            except imaplib.IMAP4.error as exc:
                msg = str(exc)
                if attempt <= self.cfg.retries and (_RETRYABLE.search(msg) or "AUTHENTICATE" in msg.upper()):
                    c.close()
                    time.sleep(min(120, 2 ** attempt))
                    continue
                self._fail(it, msg)
                return

    def run(self, items, on_error):
        q: "queue.Queue" = queue.Queue(maxsize=self.cfg.workers * 4)
        threads = [threading.Thread(target=self._worker, args=(q,), daemon=True)
                   for _ in range(self.cfg.workers)]
        for t in threads:
            t.start()
        n = 0
        last = time.time()
        t0 = time.time()
        try:
            for it in items:
                if isinstance(it, Error):
                    on_error(it)
                    continue
                q.put(it)
                n += 1
                if time.time() - last > 10:
                    last = time.time()
                    s = self.stats
                    rate = s["uvezeno"] / max(1, time.time() - t0)
                    self.log(f"[napredak] procitano {n}, uvezeno {s['uvezeno']}, "
                             f"preskoceno {s['preskoceno_vec_uvezeno']}, greske {s['greska']}, "
                             f"{rate:.1f} poruka/s, {s['bajtova'] / 1048576:.0f} MB")
        finally:
            for _ in threads:
                q.put(None)
            for t in threads:
                t.join()
        return n
