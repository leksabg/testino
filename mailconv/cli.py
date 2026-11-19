"""Komandna linija: scan / convert / upload / test-login."""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import os
import sys
import threading
from collections import Counter
from dataclasses import dataclass

from . import __version__
from .sources import Error, Item, Options, iter_inputs


class Logger:
    def __init__(self, path: str | None):
        self.lock = threading.Lock()
        self.f = open(path, "a", encoding="utf-8") if path else None

    def __call__(self, msg: str):
        with self.lock:
            try:
                print(msg, flush=True)
            except UnicodeEncodeError:
                print(msg.encode("ascii", "replace").decode(), flush=True)
            if self.f:
                self.f.write(f"{_dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
                self.f.flush()


class ErrorReport:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()
        self.n = 0
        self.f = None

    def __call__(self, origin: str, folder: str, error: str):
        with self.lock:
            if self.f is None:
                new = not os.path.exists(self.path)
                self.f = open(self.path, "a", newline="", encoding="utf-8-sig")
                self.w = csv.writer(self.f, delimiter=";")
                if new:
                    self.w.writerow(["vreme", "izvor", "folder", "greska"])
            self.w.writerow([f"{_dt.datetime.now():%Y-%m-%d %H:%M:%S}", origin, folder, error])
            self.f.flush()
            self.n += 1

    def close(self):
        if self.f:
            self.f.close()


def _opts(a) -> Options:
    dom = a.x500_domain
    if not dom and getattr(a, "mailbox", None) and "@" in a.mailbox:
        dom = a.mailbox.split("@", 1)[1]
    return Options(include_nonmail=a.include_nonmail, gmail_labels=not a.no_gmail_labels,
                   x500_domain=dom or "unknown.invalid", include_deleted=a.include_deleted)


def _iter(a, opts: Options, extra=None):
    """iter_inputs + podrska za GUI: prekid (a.cancel) i napredak (a.progress)."""
    import time as _t

    cancel = getattr(a, "cancel", None)
    progress = getattr(a, "progress", None)
    n = 0
    last = 0.0
    for it in iter_inputs(a.inputs, opts):
        if cancel is not None and cancel.is_set():
            raise KeyboardInterrupt
        if isinstance(it, Item):
            n += 1
        if progress and _t.time() - last > 0.3:
            last = _t.time()
            d = {"procitano": n}
            if extra:
                d.update(extra())
            progress(d)
        yield it
    if progress:
        d = {"procitano": n}
        if extra:
            d.update(extra())
        progress(d)


def _print_stats(log, opts: Options):
    if opts.stats:
        log("Fajlovi/izvori: " + ", ".join(f"{k}={v}" for k, v in sorted(opts.stats.items())))


# --- scan --------------------------------------------------------------------
def cmd_scan(a, log):
    opts = _opts(a)
    folders: Counter = Counter()
    fmts: Counter = Counter()
    errors = 0
    size = 0
    report = ErrorReport(a.report)
    for it in _iter(a, opts):
        if isinstance(it, Error):
            errors += 1
            report(it.origin, "/".join(it.folder), it.error)
            log(f"  ! {it.origin}: {it.error}")
            continue
        folders["/".join(it.folder) or "(koren -> INBOX)"] += 1
        fmts[it.fmt] += 1
        size += len(it.raw)
    report.close()
    log("\nPoruke po formatu:")
    for k, v in fmts.most_common():
        log(f"  {k:8s} {v}")
    log("\nPoruke po folderu:")
    for k, v in sorted(folders.items()):
        log(f"  {v:7d}  {k}")
    log(f"\nUkupno: {sum(fmts.values())} poruka, {size / 1048576:.1f} MB, gresaka: {errors}")
    _print_stats(log, opts)
    if errors:
        log(f"Greske su upisane u {a.report}")
    return 0


# --- convert -----------------------------------------------------------------
def cmd_convert(a, log):
    from .writer import EmlWriter, MboxWriter

    opts = _opts(a)
    os.makedirs(a.output, exist_ok=True)
    w = MboxWriter(a.output) if a.format == "mbox" else EmlWriter(a.output)
    report = ErrorReport(a.report)
    n = err = 0
    try:
        for it in _iter(a, opts):
            if isinstance(it, Error):
                err += 1
                report(it.origin, "/".join(it.folder), it.error)
                log(f"  ! {it.origin}: {it.error}")
                continue
            w.write(it)
            n += 1
            if n % 500 == 0:
                log(f"[napredak] {n} poruka")
    finally:
        w.close()
        report.close()
    log(f"\nGotovo: {n} poruka zapisano u {a.output} ({a.format}), gresaka: {err}")
    _print_stats(log, opts)
    return 0 if not err else 2


# --- upload ------------------------------------------------------------------
@dataclass
class ImapCfg:
    host: str
    port: int
    ssl: bool
    starttls: bool
    auth: str
    mailbox: str
    login_user: str | None
    password: str | None
    workers: int
    retries: int
    max_size: int
    timeout: int


def _imap_cfg(a) -> ImapCfg:
    return ImapCfg(host=a.host, port=a.port, ssl=not a.no_ssl, starttls=a.starttls, auth=a.auth,
                   mailbox=a.mailbox, login_user=a.login_user,
                   password=a.password or os.environ.get("MAILCONV_PASSWORD"),
                   workers=max(1, min(a.workers, 16)), retries=a.retries,
                   max_size=int(a.max_size_mb * 1048576), timeout=a.timeout)


def _token_provider(a, log):
    if a.auth == "password":
        return None
    from .auth import TokenProvider

    client_id = a.client_id or os.environ.get("MAILCONV_CLIENT_ID")
    tenant = a.tenant or os.environ.get("MAILCONV_TENANT") or "organizations"
    if not client_id:
        raise SystemExit("Potreban je --client-id (Application ID registrovane aplikacije, vidi README)")
    if a.auth == "app" and tenant in ("organizations", "common"):
        raise SystemExit("Za --auth app navedi --tenant (npr. firma.onmicrosoft.com)")
    return TokenProvider(a.auth, client_id, tenant,
                         secret=a.client_secret or os.environ.get("MAILCONV_CLIENT_SECRET"),
                         cache_path=a.token_cache, login_hint=a.login_user, log=log,
                         device_callback=getattr(a, "device_callback", None))


def cmd_test_login(a, log):
    from .imap_upload import FolderMap, Connection

    cfg = _imap_cfg(a)
    tp = _token_provider(a, log)
    c = Connection(cfg, tp)
    log(f"Povezujem se na {cfg.host}:{cfg.port} kao {cfg.mailbox} ...")
    conn = c.open()
    fm = FolderMap("", True, log)
    fm.load(conn)
    log("OK! Prijava uspela. Folderi u mailbox-u:")
    from .imap_upload import imap_utf7_decode
    for name in sorted(fm.existing.values()):
        log("  " + imap_utf7_decode(name))
    log("Specijalni folderi: " + ", ".join(f"{k}={v}" for k, v in fm.special.items()))
    c.close()
    return 0


def cmd_upload(a, log):
    from .imap_upload import FolderMap, Uploader
    from .state import State

    opts = _opts(a)
    cfg = _imap_cfg(a)
    report = ErrorReport(a.report)
    fm = FolderMap(a.root, not a.no_special_map, log)

    if a.dry_run:
        log("PROBA (--dry-run): nista se ne salje, samo prikaz gde bi sta islo.\n")
        cnt: Counter = Counter()
        err = 0
        for it in _iter(a, opts):
            if isinstance(it, Error):
                err += 1
                report(it.origin, "/".join(it.folder), it.error)
                continue
            cnt[fm.display(it.folder)] += 1
        for k, v in sorted(cnt.items()):
            log(f"  {v:7d}  -> {k}")
        log(f"\nUkupno {sum(cnt.values())} poruka, gresaka pri citanju: {err}")
        _print_stats(log, opts)
        report.close()
        return 0

    tp = _token_provider(a, log)
    state = State(a.state)
    up = Uploader(cfg, tp, state, fm, log, report)
    log(f"Povezujem se na {cfg.host} -> mailbox {cfg.mailbox} ({cfg.workers} paralelnih konekcija)")
    ctl = up.connect_and_list()
    ctl.close()
    log(f"Pronadjeno {len(fm.existing)} postojecih foldera. Krecem uvoz...\n")

    def on_error(e: Error):
        report(e.origin, "/".join(e.folder), e.error)
        up._inc("greska")
        log(f"  ! {e.origin}: {e.error}")

    t0 = _dt.datetime.now()
    try:
        n = up.run(_iter(a, opts, extra=lambda: dict(up.stats)), on_error)
    except KeyboardInterrupt:
        log("\nPrekinuto. Pokreni istu komandu ponovo - nastavlja gde je stalo.")
        state.close()
        report.close()
        return 130
    state.close()
    report.close()
    s = up.stats
    if getattr(a, "progress", None):
        a.progress(dict(s, procitano=n))
    log(f"\nGOTOVO za {(_dt.datetime.now() - t0)}: procitano {n}, uvezeno {s['uvezeno']} "
        f"({s['bajtova'] / 1048576:.1f} MB), vec ranije uvezeno {s['preskoceno_vec_uvezeno']}, "
        f"gresaka {s['greska']}")
    _print_stats(log, opts)
    if s["greska"]:
        log(f"Spisak gresaka: {a.report}  (popravi i pokreni ponovo - uvezene poruke se preskacu)")
    return 0 if not s["greska"] else 2


# --- argparse ----------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="mailconv",
        description="Konverter mejlova (EML, MSG, MBOX, PST/OST, OLM, Maildir, EMLX, ZIP) "
                    "i uvoz u Outlook 365 / Exchange Online (i shared) mailbox.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("inputs", nargs="+", help="fajlovi ili folderi (bilo koji podrzan format)")
        sp.add_argument("--include-nonmail", action="store_true",
                        help="ukljuci i kontakte/kalendar/zadatke iz PST/MSG (kao poruke)")
        sp.add_argument("--include-deleted", action="store_true",
                        help="ukljuci poruke oznacene kao obrisane (Thunderbird/Maildir/Apple)")
        sp.add_argument("--no-gmail-labels", action="store_true",
                        help="ne rasporedjuj Gmail Takeout poruke po labelama")
        sp.add_argument("--x500-domain", help="domen za interne Exchange (X500) adrese iz PST/MSG")
        sp.add_argument("--report", default="mailconv_greske.csv", help="CSV sa greskama")
        sp.add_argument("--log", default="mailconv.log", help="log fajl")

    def imap(sp, need_inputs=True):
        sp.add_argument("--mailbox", required=True, help="adresa (shared) mailbox-a, npr. office@firma.rs")
        sp.add_argument("--auth", choices=["device", "app", "password"], default="device",
                        help="device = prijava korisnika sa Full Access (podrazumevano); "
                             "app = aplikacija sa client secret; password = on-prem/drugi IMAP server")
        sp.add_argument("--client-id", help="Application (client) ID iz Entra ID (ili env MAILCONV_CLIENT_ID)")
        sp.add_argument("--tenant", help="tenant ID ili domen, npr. firma.onmicrosoft.com (env MAILCONV_TENANT)")
        sp.add_argument("--client-secret", help="za --auth app (bolje env MAILCONV_CLIENT_SECRET)")
        sp.add_argument("--login-user", help="za --auth password: korisnik za prijavu (ako nije --mailbox)")
        sp.add_argument("--password", help="za --auth password (bolje env MAILCONV_PASSWORD)")
        sp.add_argument("--host", default="outlook.office365.com")
        sp.add_argument("--port", type=int, default=993)
        sp.add_argument("--no-ssl", action="store_true", help=argparse.SUPPRESS)
        sp.add_argument("--starttls", action="store_true", help=argparse.SUPPRESS)
        sp.add_argument("--token-cache", default=".mailconv_token_cache.json")
        sp.add_argument("--timeout", type=int, default=180)
        sp.add_argument("--workers", type=int, default=4, help="paralelne IMAP konekcije (1-16)")
        sp.add_argument("--retries", type=int, default=6)
        sp.add_argument("--max-size-mb", type=float, default=150,
                        help="preskoci poruke vece od ovoga (EXO max 150 MB; default limit mailboxa je 35 MB)")

    s = sub.add_parser("scan", help="samo procitaj sve i prikazi sta je pronadjeno")
    common(s)
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("convert", help="konvertuj sve u .eml (ili .mbox) stablo foldera")
    common(s)
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--format", choices=["eml", "mbox"], default="eml")
    s.set_defaults(func=cmd_convert)

    s = sub.add_parser("upload", help="uvezi direktno u Outlook 365 (shared) mailbox")
    common(s)
    imap(s)
    s.add_argument("--root", default="",
                   help="stavi sve pod ovaj folder, npr. \"Uvoz 2024\" (podrazumevano: spaja sa postojecim)")
    s.add_argument("--no-special-map", action="store_true",
                   help="ne mapiraj Inbox/Sent/Trash... na postojece sistemske foldere")
    s.add_argument("--state", default="mailconv_state.sqlite",
                   help="baza uvezenih poruka (za nastavak i sprecavanje duplikata)")
    s.add_argument("--dry-run", action="store_true", help="prikazi raspored, bez slanja")
    s.set_defaults(func=cmd_upload)

    s = sub.add_parser("test-login", help="proveri prijavu i izlistaj foldere")
    imap(s)
    s.add_argument("--log", default="mailconv.log")
    s.add_argument("--x500-domain")
    s.set_defaults(func=cmd_test_login)
    return p


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    log = Logger(getattr(a, "log", None))
    log(f"mailconv {__version__} - {a.cmd}")
    try:
        return a.func(a, log) or 0
    except KeyboardInterrupt:
        log("Prekinuto.")
        return 130
    except Exception as exc:
        import imaplib
        if isinstance(exc, (imaplib.IMAP4.error, OSError)):
            log(f"\nGRESKA pri povezivanju/prijavi: {exc}")
            if "AUTHENTICATE" in str(exc).upper() or "AUTHENTICATIONFAILED" in str(exc).upper():
                log("Proveri: IMAP ukljucen na mailbox-u (Set-CASMailbox -ImapEnabled $true), "
                    "Full Access prava, API dozvole aplikacije i --tenant. Vidi README, odeljak 'Problemi'.")
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
