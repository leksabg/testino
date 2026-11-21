"""OAuth2 tokeni za Exchange Online IMAP (MSAL)."""
from __future__ import annotations

import os
import threading
import time

IMAP_DELEGATED_SCOPE = ["https://outlook.office.com/IMAP.AccessAsUser.All"]
IMAP_APP_SCOPE = ["https://outlook.office365.com/.default"]


_SUCCESS_HTML = """<html><head><meta charset="utf-8"><title>mailconv</title></head>
<body style="font-family:Segoe UI,Arial;text-align:center;margin-top:80px">
<h2 style="color:#2e7d32">&#10004; Prijava uspela</h2>
<p>Možeš da zatvoriš ovaj tab i vratiš se u mailconv.</p></body></html>"""
_ERROR_HTML = """<html><head><meta charset="utf-8"><title>mailconv</title></head>
<body style="font-family:Segoe UI,Arial;text-align:center;margin-top:80px">
<h2 style="color:#c62828">Prijava nije uspela</h2><p>$error: $error_description</p>
<p>Vrati se u mailconv za detalje.</p></body></html>"""


class TokenProvider:
    """mode: 'device' (prijava korisnika sa Full Access pravom na shared mailbox)
             'app'    (aplikacija + client secret, IMAP.AccessAsApp)"""

    def __init__(self, mode: str, client_id: str, tenant: str, secret: str | None = None,
                 cache_path: str = ".mailconv_token_cache.json", login_hint: str | None = None,
                 log=print, device_callback=None, login: str = "browser"):
        try:
            import msal
        except ImportError as e:
            raise SystemExit("Nedostaje msal: pip install msal") from e
        self.mode = mode
        self.log = log
        self.device_callback = device_callback  # GUI: prozor sa kodom za prijavu
        self.login = login  # "browser" = obicna Microsoft prijava u browseru, "code" = kod
        self.lock = threading.Lock()
        self.login_hint = login_hint
        self.cache_path = cache_path
        self._token = None
        self._exp = 0.0
        authority = f"https://login.microsoftonline.com/{tenant}"
        if mode == "app":
            if not secret:
                raise SystemExit("Za --auth app potreban je --client-secret (ili env MAILCONV_CLIENT_SECRET)")
            self.app = msal.ConfidentialClientApplication(client_id, authority=authority,
                                                          client_credential=secret)
        else:
            self.cache = msal.SerializableTokenCache()
            if cache_path and os.path.exists(cache_path):
                with open(cache_path, "r", encoding="utf-8") as f:
                    self.cache.deserialize(f.read())
            self.app = msal.PublicClientApplication(client_id, authority=authority,
                                                    token_cache=self.cache)

    def _save(self):
        if self.mode != "app" and self.cache.has_state_changed and self.cache_path:
            fd = os.open(self.cache_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(self.cache.serialize())

    def _browser_login(self):
        """Otvara standardnu Microsoft stranicu za prijavu (email, lozinka, MFA).
        Vraca None ako browser ne moze da se otvori -> prelazi se na prijavu kodom."""
        self.log("Otvaram Microsoft prijavu u browseru... Prijavi se nalogom koji ima "
                 "Full Access na mailbox, pa se vrati ovde.")
        try:
            res = self.app.acquire_token_interactive(
                IMAP_DELEGATED_SCOPE, login_hint=self.login_hint, prompt="select_account",
                timeout=600, success_template=_SUCCESS_HTML, error_template=_ERROR_HTML)
        except Exception as exc:  # nema browsera / port zauzet itd.
            self.log(f"Prijava u browseru nije moguca ({exc}) - prelazim na prijavu kodom.")
            return None
        err = (res or {}).get("error_description") or ""
        if "AADSTS50011" in err or "AADSTS500113" in err or "reply address" in err.lower():
            raise SystemExit(
                "U registraciji aplikacije fali Redirect URI za prijavu u browseru.\n\n"
                "Entra admin center → App registrations → mailconv → Authentication → "
                "Add a platform → Mobile and desktop applications → upiši  http://localhost  → Configure.\n\n"
                "Sačekaj minut i pokušaj ponovo.")
        if res and "error" in res and res.get("error") in ("access_denied", "authorization_pending"):
            raise SystemExit("Prijava je otkazana.")
        return res

    def get(self, force: bool = False) -> str:
        with self.lock:
            if not force and self._token and time.time() < self._exp - 300:
                return self._token
            if self.mode == "app":
                res = self.app.acquire_token_for_client(scopes=IMAP_APP_SCOPE)
            else:
                res = None
                accounts = self.app.get_accounts(username=self.login_hint) or self.app.get_accounts()
                if accounts:
                    res = self.app.acquire_token_silent(IMAP_DELEGATED_SCOPE, account=accounts[0],
                                                        force_refresh=force)
                if not res and self.login == "browser":
                    res = self._browser_login()
                if not res:
                    flow = self.app.initiate_device_flow(scopes=IMAP_DELEGATED_SCOPE)
                    if "user_code" not in flow:
                        raise SystemExit(f"Ne mogu da pokrenem prijavu: {flow.get('error_description', flow)}")
                    self.log("\n" + "=" * 70 + "\nPRIJAVA: " + flow["message"] + "\n" + "=" * 70 + "\n")
                    if self.device_callback:
                        self.device_callback(flow)
                    try:
                        res = self.app.acquire_token_by_device_flow(flow)
                    finally:
                        if self.device_callback:
                            self.device_callback(None)
                self._save()
            if not res or "access_token" not in res:
                err = (res or {}).get("error_description") or (res or {}).get("error") or res
                raise SystemExit(f"Neuspela prijava: {err}")
            self._token = res["access_token"]
            self._exp = time.time() + int(res.get("expires_in", 3600))
            return self._token
