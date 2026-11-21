"""Graficki interfejs za mailconv (tkinter - dolazi uz Python, nema dodatnih zavisnosti)."""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__

DATA_DIR = Path.home() / "mailconv"
SETTINGS = DATA_DIR / "podesavanja.json"

AUTH_MODES = [
    ("device", "Prijava korisnika sa Full Access pravom (preporučeno)"),
    ("app", "Aplikacija sa client secret-om (bez korisnika)"),
    ("password", "Drugi IMAP server (korisnik + lozinka)"),
]
SAVED_FIELDS = ["mailbox", "client_id", "tenant", "root", "auth", "host", "port", "login_user",
                "workers", "out_dir", "out_format", "mode", "special_map", "include_deleted",
                "include_nonmail", "gmail_labels", "x500_domain", "inputs"]


def open_path(path: str):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as exc:
        messagebox.showerror("Greška", f"Ne mogu da otvorim {path}:\n{exc}")


class DeviceCodeDialog(tk.Toplevel):
    def __init__(self, master, flow: dict):
        super().__init__(master)
        self.title("Prijava na Microsoft 365")
        self.resizable(False, False)
        self.transient(master)
        code = flow.get("user_code", "")
        url = flow.get("verification_uri", "https://microsoft.com/devicelogin")
        pad = {"padx": 16, "pady": 6}
        ttk.Label(self, text="1. Otvori stranicu za prijavu:", font=("", 10, "bold")).pack(anchor="w", **pad)
        link = ttk.Label(self, text=url, foreground="#0a64c8", cursor="hand2")
        link.pack(anchor="w", padx=32)
        link.bind("<Button-1>", lambda e: webbrowser.open(url))
        ttk.Label(self, text="2. Unesi ovaj kod:", font=("", 10, "bold")).pack(anchor="w", **pad)
        e = ttk.Entry(self, font=("Consolas", 22, "bold"), justify="center", width=14)
        e.insert(0, code)
        e.configure(state="readonly")
        e.pack(padx=32, pady=4)
        ttk.Label(self, text="3. Prijavi se nalogom koji ima Full Access na shared mailbox.\n"
                             "   Ovaj prozor se sam zatvara kad prijava uspe.",
                  justify="left").pack(anchor="w", **pad)
        b = ttk.Frame(self)
        b.pack(fill="x", padx=16, pady=(4, 14))

        def copy_open():
            self.clipboard_clear()
            self.clipboard_append(code)
            webbrowser.open(url)

        ttk.Button(b, text="Kopiraj kod i otvori stranicu", command=copy_open).pack(side="left")
        copy_open()  # odmah: kod je u clipboard-u, stranica otvorena
        self.protocol("WM_DELETE_WINDOW", lambda: None)  # zatvara se samo posle prijave


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"mailconv {__version__} – uvoz mejlova u Outlook 365")
        self.geometry("980x780")
        self.minsize(820, 640)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel = threading.Event()
        self.device_dialog: DeviceCodeDialog | None = None
        self._style()
        self._vars()
        self._build()
        self._load()
        self._on_mode()
        self._on_auth()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- UI ------------------------------------------------------------------
    def _style(self):
        st = ttk.Style(self)
        if sys.platform.startswith("win"):
            try:
                st.theme_use("vista")
            except tk.TclError:
                pass
        elif "clam" in st.theme_names():
            st.theme_use("clam")
        st.configure("Big.TButton", font=("", 11, "bold"), padding=(14, 8))
        st.configure("Head.TLabel", font=("", 10, "bold"))

    def _vars(self):
        S, B = tk.StringVar, tk.BooleanVar
        self.v = {
            "mode": S(value="upload"), "mailbox": S(), "client_id": S(), "tenant": S(),
            "client_secret": S(), "auth": S(value=AUTH_MODES[0][1]), "root": S(value="Uvoz"),
            "host": S(value="outlook.office365.com"), "port": S(value="993"), "login_user": S(),
            "password": S(), "workers": S(value="4"), "out_dir": S(value=str(DATA_DIR / "izlaz")),
            "out_format": S(value="eml"), "special_map": B(value=True), "include_deleted": B(value=False),
            "include_nonmail": B(value=False), "gmail_labels": B(value=True), "x500_domain": S(),
        }
        self.status = S(value="Spremno.")

    def _build(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)

        # 1. izvori
        f1 = ttk.LabelFrame(root, text=" 1. Šta uvozim – fajlovi i folderi (PST, MSG, EML, MBOX, OLM, ZIP, Maildir…) ",
                            padding=8)
        f1.grid(row=0, column=0, sticky="nsew")
        f1.columnconfigure(0, weight=1)
        self.lst = tk.Listbox(f1, height=5, selectmode="extended", activestyle="none")
        self.lst.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(f1, orient="vertical", command=self.lst.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.lst.configure(yscrollcommand=sb.set)
        bf = ttk.Frame(f1)
        bf.grid(row=0, column=2, sticky="n", padx=(8, 0))
        for txt, cmd in (("Dodaj fajlove…", self._add_files), ("Dodaj folder…", self._add_folder),
                         ("Ukloni izabrano", self._remove_sel), ("Očisti listu", self._clear)):
            ttk.Button(bf, text=txt, command=cmd, width=16).pack(fill="x", pady=1)

        # 2. odrediste
        f2 = ttk.LabelFrame(root, text=" 2. Gde ", padding=8)
        f2.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        f2.columnconfigure(0, weight=1)
        mf = ttk.Frame(f2)
        mf.grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(mf, text="Uvezi u Outlook 365 / Exchange mailbox (i shared)", value="upload",
                        variable=self.v["mode"], command=self._on_mode).pack(side="left")
        ttk.Radiobutton(mf, text="Samo konvertuj u folder na disku", value="convert",
                        variable=self.v["mode"], command=self._on_mode).pack(side="left", padx=(20, 0))

        # upload polja
        self.fu = ttk.Frame(f2)
        self.fu.columnconfigure(1, weight=1)
        self.fu.columnconfigure(3, weight=1)
        r = 0

        def row(label, widget, col=0, colspan=1, hint=None):
            lbl = ttk.Label(self.fu, text=label)
            lbl.grid(row=r, column=col, sticky="w", padx=(0, 6), pady=2)
            widget._lbl = lbl
            widget.grid(row=r, column=col + 1, columnspan=colspan, sticky="ew", pady=2,
                        padx=(0, 12) if col == 0 else 0)
            if hint:
                self._tip(widget, hint)
            return widget

        row("Mailbox:", ttk.Entry(self.fu, textvariable=self.v["mailbox"]),
            hint="Adresa (shared) mailbox-a u koji uvoziš, npr. office@firma.rs")
        row("Ciljni folder:", ttk.Entry(self.fu, textvariable=self.v["root"]), col=2,
            hint="Sve ide pod ovaj folder (npr. 'Uvoz 2024'). Prazno = spoji sa postojećim folderima.")
        r += 1
        ttk.Label(self.fu, text="Način prijave:").grid(row=r, column=0, sticky="w", pady=2)
        cb = ttk.Combobox(self.fu, textvariable=self.v["auth"], state="readonly",
                          values=[m[1] for m in AUTH_MODES])
        cb.grid(row=r, column=1, columnspan=3, sticky="ew", pady=2)
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_auth())
        r += 1
        self.w_cid = row("Client ID:", ttk.Entry(self.fu, textvariable=self.v["client_id"]),
                         hint="Application (client) ID iz Entra ID → App registrations")
        self.w_ten = row("Tenant:", ttk.Entry(self.fu, textvariable=self.v["tenant"]), col=2,
                         hint="Tenant ID ili domen, npr. firma.onmicrosoft.com")
        r += 1
        self.w_sec = row("Client secret:", ttk.Entry(self.fu, textvariable=self.v["client_secret"], show="•"),
                         hint="Samo za prijavu aplikacijom. Ne čuva se na disku.")
        r += 1
        self.w_host = row("IMAP server:", ttk.Entry(self.fu, textvariable=self.v["host"]))
        self.w_port = row("Port:", ttk.Entry(self.fu, textvariable=self.v["port"], width=8), col=2)
        r += 1
        self.w_user = row("Korisnik:", ttk.Entry(self.fu, textvariable=self.v["login_user"]),
                          hint="Prazno = isto kao Mailbox")
        self.w_pass = row("Lozinka:", ttk.Entry(self.fu, textvariable=self.v["password"], show="•"), col=2,
                          hint="Ne čuva se na disku.")
        self.pw_rows = [self.w_host, self.w_port, self.w_user, self.w_pass]
        self.oauth_rows = [self.w_cid, self.w_ten]
        r += 1
        hf = ttk.Frame(self.fu)
        hf.grid(row=r, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Button(hf, text="Uputstvo: podešavanje Microsoft 365…", command=self._help).pack(side="left")
        ttk.Button(hf, text="Test prijave", command=self._test_login).pack(side="left", padx=6)
        ttk.Button(hf, text="Odjavi se / promeni nalog", command=self._logout).pack(side="left")

        # convert polja
        self.fc = ttk.Frame(f2)
        self.fc.columnconfigure(1, weight=1)
        ttk.Label(self.fc, text="Izlazni folder:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(self.fc, textvariable=self.v["out_dir"]).grid(row=0, column=1, sticky="ew")
        ttk.Button(self.fc, text="Izaberi…", command=self._pick_out).grid(row=0, column=2, padx=6)
        ttk.Label(self.fc, text="Format:").grid(row=0, column=3, sticky="w")
        ttk.Combobox(self.fc, textvariable=self.v["out_format"], values=["eml", "mbox"], width=6,
                     state="readonly").grid(row=0, column=4, padx=(4, 0))

        # 3. opcije
        f3 = ttk.LabelFrame(root, text=" 3. Opcije ", padding=(8, 4))
        f3.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        opts = [("special_map", "Inbox/Sent/Trash… u sistemske foldere",
                 "Važi kad je ciljni folder prazan: 'Sent', 'Poslato'… idu u 'Sent Items' itd."),
                ("gmail_labels", "Gmail Takeout: rasporedi po labelama", None),
                ("include_deleted", "Uključi obrisane poruke",
                 "Thunderbird/Maildir/Apple drže obrisane poruke dok se ne 'kompaktuje'"),
                ("include_nonmail", "Uključi kontakte/kalendar iz PST", None)]
        for i, (k, txt, tip) in enumerate(opts):
            c = ttk.Checkbutton(f3, text=txt, variable=self.v[k])
            c.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 24))
            if tip:
                self._tip(c, tip)
        wf = ttk.Frame(f3)
        wf.grid(row=0, column=2, rowspan=2, sticky="ne")
        ttk.Label(wf, text="Paralelnih konekcija:").pack(side="left")
        ttk.Spinbox(wf, from_=1, to=16, textvariable=self.v["workers"], width=4).pack(side="left", padx=4)

        # dugmad
        f4 = ttk.Frame(root)
        f4.grid(row=3, column=0, sticky="ew", pady=(10, 6))
        self.b_scan = ttk.Button(f4, text="Skeniraj", command=self._scan)
        self.b_scan.pack(side="left")
        self._tip(self.b_scan, "Samo pročitaj sve i prikaži koliko poruka ima po formatu i folderu")
        self.b_dry = ttk.Button(f4, text="Proba (bez slanja)", command=self._dry)
        self.b_dry.pack(side="left", padx=6)
        self._tip(self.b_dry, "Prikaži u koji folder bi išlo koliko poruka – ništa se ne šalje")
        self.b_run = ttk.Button(f4, text="▶  POKRENI UVOZ", style="Big.TButton", command=self._run)
        self.b_run.pack(side="left", padx=(12, 6))
        self.b_stop = ttk.Button(f4, text="■  Zaustavi", command=self._stop, state="disabled")
        self.b_stop.pack(side="left")
        ttk.Button(f4, text="Folder sa izveštajima", command=lambda: open_path(str(DATA_DIR))).pack(side="right")
        ttk.Button(f4, text="Greške (CSV)", command=self._open_errors).pack(side="right", padx=6)

        # log
        f5 = ttk.Frame(root)
        f5.grid(row=4, column=0, sticky="nsew")
        f5.columnconfigure(0, weight=1)
        f5.rowconfigure(1, weight=1)
        top = ttk.Frame(f5)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        self.pb = ttk.Progressbar(top, mode="indeterminate", length=160)
        self.pb.grid(row=0, column=0, padx=(0, 8))
        ttk.Label(top, textvariable=self.status, style="Head.TLabel").grid(row=0, column=1, sticky="w")
        self.log = ScrolledText(f5, height=12, wrap="word", font=("Consolas", 9), state="disabled")
        self.log.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self.log.tag_configure("err", foreground="#c62828")
        self.log.tag_configure("ok", foreground="#2e7d32", font=("Consolas", 9, "bold"))
        self.log.tag_configure("warn", foreground="#b26a00")
        self.log.tag_configure("dim", foreground="#777777")

    def _tip(self, widget, text):
        tip = {"w": None}

        def show(_e):
            if tip["w"]:
                return
            x = widget.winfo_rootx() + 10
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            t = tk.Toplevel(widget)
            t.wm_overrideredirect(True)
            t.wm_geometry(f"+{x}+{y}")
            tk.Label(t, text=text, background="#ffffe0", relief="solid", borderwidth=1,
                     justify="left", wraplength=380, padx=6, pady=3).pack()
            tip["w"] = t

        def hide(_e):
            if tip["w"]:
                tip["w"].destroy()
                tip["w"] = None

        widget.bind("<Enter>", show, add="+")
        widget.bind("<Leave>", hide, add="+")

    # --- handlers ------------------------------------------------------------
    def _add_files(self):
        files = filedialog.askopenfilenames(
            title="Izaberi fajlove sa mejlovima",
            filetypes=[("Mejl fajlovi", "*.pst *.ost *.msg *.eml *.emlx *.mbox *.mbx *.olm *.zip *.tar *.tgz *.gz"),
                       ("Svi fajlovi", "*.*")])
        for f in files:
            self._add(f)

    def _add_folder(self):
        d = filedialog.askdirectory(title="Izaberi folder (sve unutra se pretražuje)")
        if d:
            self._add(d)

    def _add(self, path):
        path = os.path.normpath(path)
        if path not in self.lst.get(0, "end"):
            self.lst.insert("end", path)

    def _remove_sel(self):
        for i in reversed(self.lst.curselection()):
            self.lst.delete(i)

    def _clear(self):
        self.lst.delete(0, "end")

    def _pick_out(self):
        d = filedialog.askdirectory(title="Izlazni folder")
        if d:
            self.v["out_dir"].set(os.path.normpath(d))

    def _auth_key(self) -> str:
        lbl = self.v["auth"].get()
        return next((k for k, l in AUTH_MODES if l == lbl), "device")

    def _on_mode(self):
        if self.v["mode"].get() == "upload":
            self.fc.grid_forget()
            self.fu.grid(row=1, column=0, sticky="ew", pady=(6, 0))
            self.b_run.configure(text="▶  POKRENI UVOZ")
            self.b_dry.configure(state="normal")
        else:
            self.fu.grid_forget()
            self.fc.grid(row=1, column=0, sticky="ew", pady=(6, 0))
            self.b_run.configure(text="▶  POKRENI KONVERZIJU")
            self.b_dry.configure(state="disabled")

    def _on_auth(self):
        k = self._auth_key()

        def show(widgets, on):
            for w in widgets:
                for x in (w, w._lbl):
                    if on:
                        x.grid()
                    else:
                        x.grid_remove()

        show(self.oauth_rows, k in ("device", "app"))
        show([self.w_sec], k == "app")
        show(self.pw_rows, k == "password")
        if k != "password" and not self.v["host"].get().strip():
            self.v["host"].set("outlook.office365.com")

    def _help(self):
        mb = self.v["mailbox"].get().strip() or "office@firma.rs"
        txt = f"""PODEŠAVANJE (jednom, radi admin, ~5 min)

A) Prijava korisnika (preporučeno)
1. entra.microsoft.com → App registrations → New registration
   Ime: mailconv, "Single tenant".
   Redirect URI: izaberi "Public client/native (mobile & desktop)" i upiši  http://localhost
   → Register.
   Prepiši "Application (client) ID" i "Directory (tenant) ID" u ovaj program.
2. (Ako je aplikacija već napravljena bez Redirect URI-ja:) Authentication → Add a platform →
   Mobile and desktop applications → upiši  http://localhost  → Configure.
   Na istoj strani: "Allow public client flows" = Yes → Save.
3. API permissions → Add a permission → Microsoft Graph → Delegated →
   IMAP.AccessAsUser.All i offline_access → "Grant admin consent".
4. Exchange Online PowerShell (Connect-ExchangeOnline):

Add-MailboxPermission -Identity {mb} -User TVOJ.NALOG@firma.rs -AccessRights FullAccess -AutoMapping $false
Set-CASMailbox -Identity {mb} -ImapEnabled $true
Set-Mailbox -Identity {mb} -MaxReceiveSize 150MB -MaxSendSize 150MB

(poslednja linija samo ako imaš poruke veće od 35 MB)

B) Aplikacija (bez korisnika)
1. App registration kao gore.
2. API permissions → APIs my organization uses → Office 365 Exchange Online →
   Application → IMAP.AccessAsApp → Grant admin consent.
3. Certificates & secrets → New client secret.
4. Enterprise applications → mailconv → prepiši Object ID, pa:

New-ServicePrincipal -AppId CLIENT_ID -ObjectId ENTERPRISE_OBJECT_ID
Add-MailboxPermission -Identity {mb} -User ENTERPRISE_OBJECT_ID -AccessRights FullAccess
Set-CASMailbox -Identity {mb} -ImapEnabled $true

Posle izmene prava sačekaj 15–60 min pre prvog pokušaja.
"""
        w = tk.Toplevel(self)
        w.title("Uputstvo – Microsoft 365")
        w.geometry("820x560")
        t = ScrolledText(w, wrap="word", font=("Consolas", 10))
        t.pack(fill="both", expand=True, padx=8, pady=8)
        t.insert("1.0", txt)
        bf = ttk.Frame(w)
        bf.pack(fill="x", padx=8, pady=(0, 8))

        def copy():
            self.clipboard_clear()
            self.clipboard_append(txt)

        ttk.Button(bf, text="Kopiraj sve", command=copy).pack(side="left")
        ttk.Button(bf, text="Otvori Entra admin center",
                   command=lambda: webbrowser.open("https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade")
                   ).pack(side="left", padx=6)
        ttk.Button(bf, text="Zatvori", command=w.destroy).pack(side="right")

    def _logout(self):
        p = DATA_DIR / "token_cache.json"
        if not p.exists():
            messagebox.showinfo("Odjava", "Nisi prijavljen – sledeća prijava će pitati za nalog.")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Zauzeto", "Sačekaj da se trenutni posao završi ili klikni Zaustavi.")
            return
        try:
            p.unlink()
        except OSError as exc:
            messagebox.showerror("Odjava", f"Ne mogu da obrišem {p}:\n{exc}")
            return
        self._append("Odjavljen. Sledeća prijava pita za nalog.\n", "ok")
        messagebox.showinfo("Odjava", "Odjavljen si.\nSledeći put (npr. 'Test prijave') biraš nalog ponovo.")

    def _open_errors(self):
        p = DATA_DIR / "greske.csv"
        if p.exists():
            open_path(str(p))
        else:
            messagebox.showinfo("Greške", "Još nema zabeleženih grešaka.")

    # --- validacija i pokretanje ----------------------------------------------
    def _common_args(self) -> list[str]:
        a = []
        if self.v["include_deleted"].get():
            a.append("--include-deleted")
        if self.v["include_nonmail"].get():
            a.append("--include-nonmail")
        if not self.v["gmail_labels"].get():
            a.append("--no-gmail-labels")
        if self.v["x500_domain"].get().strip():
            a += ["--x500-domain", self.v["x500_domain"].get().strip()]
        a += ["--report", str(DATA_DIR / "greske.csv"), "--log", str(DATA_DIR / "mailconv.log")]
        return a

    def _imap_args(self) -> list[str] | None:
        mb = self.v["mailbox"].get().strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", mb):
            messagebox.showwarning("Nedostaje podatak", "Unesi ispravnu adresu mailbox-a (npr. office@firma.rs).")
            return None
        k = self._auth_key()
        a = ["--mailbox", mb, "--auth", k, "--workers", str(self._int(self.v["workers"].get(), 4, 1, 16)),
             "--token-cache", str(DATA_DIR / "token_cache.json")]
        if k in ("device", "app"):
            cid = self.v["client_id"].get().strip()
            if not re.fullmatch(r"[0-9a-fA-F-]{36}", cid):
                messagebox.showwarning("Nedostaje podatak",
                                       "Unesi Client ID (Application ID, oblik xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx).\n\n"
                                       "Klikni 'Uputstvo: podešavanje Microsoft 365' ako ga još nemaš.")
                return None
            a += ["--client-id", cid]
            ten = self.v["tenant"].get().strip()
            if not ten and "@" in mb:
                ten = mb.split("@", 1)[1]  # domen mailbox-a radi kao tenant
            if ten:
                a += ["--tenant", ten]
        if k == "app":
            if not self.v["client_secret"].get():
                messagebox.showwarning("Nedostaje podatak", "Unesi client secret.")
                return None
            a += ["--client-secret", self.v["client_secret"].get()]
        if k == "password":
            if not self.v["password"].get():
                messagebox.showwarning("Nedostaje podatak", "Unesi lozinku.")
                return None
            a += ["--host", self.v["host"].get().strip(), "--port", str(self._int(self.v["port"].get(), 993, 1, 65535)),
                  "--password", self.v["password"].get()]
            if self.v["login_user"].get().strip():
                a += ["--login-user", self.v["login_user"].get().strip()]
        return a

    @staticmethod
    def _int(s, default, lo, hi):
        try:
            return max(lo, min(hi, int(str(s).strip())))
        except ValueError:
            return default

    def _inputs(self) -> list[str] | None:
        items = list(self.lst.get(0, "end"))
        if not items:
            messagebox.showwarning("Nema izvora", "Dodaj bar jedan fajl ili folder sa mejlovima (korak 1).")
            return None
        missing = [p for p in items if not os.path.exists(p)]
        if missing:
            messagebox.showwarning("Ne postoji", "Ovi izvori ne postoje:\n" + "\n".join(missing))
            return None
        return items

    def _state_path(self, mailbox: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9@._-]", "_", mailbox.lower())
        return str(DATA_DIR / f"stanje_{safe}.sqlite")

    def _scan(self):
        inp = self._inputs()
        if inp:
            self._start(["scan", *inp, *self._common_args()], "Skeniranje")

    def _dry(self):
        inp = self._inputs()
        if not inp:
            return
        imap = self._imap_args()
        if imap is None:
            return
        a = ["upload", *inp, *self._common_args(), *imap, "--dry-run", "--root", self.v["root"].get().strip()]
        if not self.v["special_map"].get():
            a.append("--no-special-map")
        self._start(a, "Proba")

    def _test_login(self):
        imap = self._imap_args()
        if imap is not None:
            self._start(["test-login", *imap, "--log", str(DATA_DIR / "mailconv.log")], "Test prijave")

    def _run(self):
        inp = self._inputs()
        if not inp:
            return
        if self.v["mode"].get() == "convert":
            out = self.v["out_dir"].get().strip()
            if not out:
                messagebox.showwarning("Nedostaje podatak", "Izaberi izlazni folder.")
                return
            self._start(["convert", *inp, *self._common_args(), "-o", out,
                         "--format", self.v["out_format"].get()], "Konverzija",
                        on_done=lambda: open_path(out))
            return
        imap = self._imap_args()
        if imap is None:
            return
        root = self.v["root"].get().strip()
        mb = self.v["mailbox"].get().strip()
        where = f"u folder „{root}“" if root else "direktno u postojeće foldere (Inbox, Sent Items…)"
        if not messagebox.askokcancel("Pokreni uvoz",
                                      f"Uvoz u {mb}\n{where}\n\nIzvora: {len(inp)}\n\n"
                                      "Ako se prekine, samo pokreni ponovo – već uvezene poruke se preskaču."):
            return
        a = ["upload", *inp, *self._common_args(), *imap, "--root", root,
             "--state", self._state_path(mb)]
        if not self.v["special_map"].get():
            a.append("--no-special-map")
        self._start(a, "Uvoz")

    def _stop(self):
        if self.worker and self.worker.is_alive():
            self.cancel.set()
            self.status.set("Zaustavljam… (završavam poruke koje su već u slanju)")
            self.b_stop.configure(state="disabled")

    def _busy(self, on: bool):
        for b in (self.b_scan, self.b_dry, self.b_run):
            b.configure(state="disabled" if on else "normal")
        if not on and self.v["mode"].get() == "convert":
            self.b_dry.configure(state="disabled")
        self.b_stop.configure(state="normal" if on else "disabled")
        if on:
            self.pb.start(12)
        else:
            self.pb.stop()

    def _start(self, argv: list[str], title: str, on_done=None):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Zauzeto", "Već radi jedan posao. Sačekaj ili klikni Zaustavi.")
            return
        self._save()
        self.cancel.clear()
        self._busy(True)
        self.status.set(f"{title} u toku…")
        self._append(f"\n===== {title} =====\n", "ok")
        self.worker = threading.Thread(target=self._work, args=(argv, title, on_done), daemon=True)
        self.worker.start()

    def _work(self, argv, title, on_done):
        from . import cli

        logf = None
        try:
            idx = argv.index("--log")
            logf = open(argv[idx + 1], "a", encoding="utf-8")
        except (ValueError, OSError):
            pass

        def log(msg: str):
            self.q.put(("log", msg))
            if logf:
                import datetime as _dt
                logf.write(f"{_dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
                logf.flush()

        rc = 1
        try:
            a = cli.build_parser().parse_args(argv)
            a.cancel = self.cancel
            a.progress = lambda d: self.q.put(("progress", d))
            a.device_callback = lambda flow: self.q.put(("device", flow))
            log(f"mailconv {__version__} – {a.cmd}")
            rc = a.func(a, log) or 0
        except KeyboardInterrupt:
            log("Zaustavljeno. Pokreni ponovo kad hoćeš – nastavlja gde je stalo.")
            rc = 130
        except SystemExit as e:
            msg = str(e.code) if e.code not in (None, 0) else ""
            if msg:
                log("GREŠKA: " + msg)
                self.q.put(("error", msg))
            rc = 1 if msg else 0
        except Exception as e:
            log("GREŠKA: " + "".join(traceback.format_exception_only(type(e), e)).strip())
            log(traceback.format_exc())
            self.q.put(("error", f"{type(e).__name__}: {e}"))
            rc = 1
        finally:
            if logf:
                logf.close()
            self.q.put(("done", (title, rc, on_done)))

    # --- glavna petlja --------------------------------------------------------
    def _append(self, text: str, tag: str | None = None):
        self.log.configure(state="normal")
        self.log.insert("end", text, tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    s = data
                    tag = None
                    if s.lstrip().startswith("!") or s.startswith("GREŠKA") or "GRESKA" in s:
                        tag = "err"
                    elif s.lstrip().startswith("~"):
                        tag = "warn"
                    elif s.startswith("GOTOVO") or s.startswith("Gotovo") or s.startswith("OK!"):
                        tag = "ok"
                    elif s.startswith("[napredak]"):
                        tag = "dim"
                    self._append(s + "\n", tag)
                elif kind == "progress":
                    d = data
                    parts = [f"Pročitano {d.get('procitano', 0)}"]
                    if "uvezeno" in d:
                        parts.append(f"uvezeno {d['uvezeno']} ({d.get('bajtova', 0) / 1048576:.0f} MB)")
                        parts.append(f"već ranije {d.get('preskoceno_vec_uvezeno', 0)}")
                        parts.append(f"greške {d.get('greska', 0)}")
                    self.status.set(" · ".join(parts))
                elif kind == "device":
                    if data:
                        self.device_dialog = DeviceCodeDialog(self, data)
                    elif self.device_dialog:
                        self.device_dialog.destroy()
                        self.device_dialog = None
                elif kind == "error":
                    messagebox.showerror("Greška", data)
                elif kind == "done":
                    title, rc, on_done = data
                    self._busy(False)
                    if self.device_dialog:
                        self.device_dialog.destroy()
                        self.device_dialog = None
                    cur = self.status.get()
                    if rc == 0:
                        self.status.set(f"✔ {title} završen. " + (cur if cur.startswith("Pročitano") else ""))
                        if on_done:
                            on_done()
                    elif rc == 2:
                        self.status.set(f"⚠ {title} završen uz greške – vidi „Greške (CSV)“. "
                                        + (cur if cur.startswith("Pročitano") else ""))
                    elif rc == 130:
                        self.status.set(f"■ {title} zaustavljen.")
                    else:
                        self.status.set(f"✖ {title} nije uspeo – vidi log.")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # --- podesavanja ---------------------------------------------------------
    def _load(self):
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for k in SAVED_FIELDS:
            if k == "inputs":
                for p in data.get("inputs", []):
                    self._add(p)
            elif k == "auth":
                key = data.get("auth")
                lbl = next((l for kk, l in AUTH_MODES if kk == key), None)
                if lbl:
                    self.v["auth"].set(lbl)
            elif k in data and k in self.v:
                try:
                    self.v[k].set(data[k])
                except tk.TclError:
                    pass

    def _save(self):
        data = {}
        for k in SAVED_FIELDS:
            if k == "inputs":
                data[k] = list(self.lst.get(0, "end"))
            elif k == "auth":
                data[k] = self._auth_key()
            else:
                data[k] = self.v[k].get()
        try:
            SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Izlaz", "Posao je u toku. Prekinuti i izaći?\n"
                                                "(Kasnije se nastavlja gde je stalo.)"):
                return
            self.cancel.set()
        self._save()
        self.destroy()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    app = App()
    if "--selftest" in argv:
        app.update()
        app._help()
        app.v["mode"].set("convert")
        app._on_mode()
        app.update()
        app.destroy()
        print("selftest ok")
        return 0
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
