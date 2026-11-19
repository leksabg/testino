"""OAuth2 tokeni za Exchange Online IMAP (MSAL)."""
from __future__ import annotations

import os
import threading
import time

IMAP_DELEGATED_SCOPE = ["https://outlook.office.com/IMAP.AccessAsUser.All"]
IMAP_APP_SCOPE = ["https://outlook.office365.com/.default"]


class TokenProvider:
    """mode: 'device' (prijava korisnika sa Full Access pravom na shared mailbox)
             'app'    (aplikacija + client secret, IMAP.AccessAsApp)"""

    def __init__(self, mode: str, client_id: str, tenant: str, secret: str | None = None,
                 cache_path: str = ".mailconv_token_cache.json", login_hint: str | None = None,
                 log=print):
        try:
            import msal
        except ImportError as e:
            raise SystemExit("Nedostaje msal: pip install msal") from e
        self.mode = mode
        self.log = log
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
                if not res:
                    flow = self.app.initiate_device_flow(scopes=IMAP_DELEGATED_SCOPE)
                    if "user_code" not in flow:
                        raise SystemExit(f"Ne mogu da pokrenem prijavu: {flow.get('error_description', flow)}")
                    self.log("\n" + "=" * 70 + "\nPRIJAVA: " + flow["message"] + "\n" + "=" * 70 + "\n")
                    res = self.app.acquire_token_by_device_flow(flow)
                self._save()
            if not res or "access_token" not in res:
                err = (res or {}).get("error_description") or (res or {}).get("error") or res
                raise SystemExit(f"Neuspela prijava: {err}")
            self._token = res["access_token"]
            self._exp = time.time() + int(res.get("expires_in", 3600))
            return self._token
