# mailconv — uvoz mejlova svih formata u Outlook 365 (shared) mailbox

Jedan alat koji **čita bilo koji format mejla** i **ubacuje ga direktno u Exchange Online / Outlook 365 mailbox**, uključujući i shared mailbox. Ne pravi PST, ne traži Purview import job ni Azure storage, i ne traži Outlook na računaru.

| Ulaz | Napomena |
|---|---|
| `.eml`, `.nws`, fajlovi bez ekstenzije | format se prepoznaje po sadržaju |
| `.msg` (Outlook) | sopstveni parser: tela (plain/HTML/RTF→HTML), prilozi, inline slike, ugnježdeni `.msg` |
| `.pst`, `.ost` | sa `libpff-python` (preporučeno) ili `readpst` alatom; struktura foldera se čuva |
| `.mbox` / `.mbx` | Thunderbird (i bez ekstenzije, `.sbd` podfolderi), Gmail Takeout (raspoređuje po labelama), Apple, Evolution… |
| Maildir / Maildir++ | Dovecot, Courier, cPanel… (`cur/new`, `.Folder.Podfolder`) |
| `.emlx` | Apple Mail (`*.mbox/…/Messages/*.emlx`) |
| `.olm` | Outlook for Mac |
| `.zip`, `.tar(.gz)` | arhive koje sadrže bilo šta od navedenog |

Šta se čuva: **struktura foldera**, **originalna MIME poruka** (zaglavlja, potpisi, prilozi), **datum prijema** (sortiranje u Outlooku je ispravno), **pročitano/nepročitano** i **zastavica**. Poruke **nisu** draftovi (kod Graph MIME uvoza jesu).

Zaštita od problema:
- **Nema duplikata**: svaka uvezena poruka se pamti (`mailconv_state.sqlite`). Ako se uvoz prekine, pokreneš istu komandu i nastavlja gde je stao. Ista poruka iz dva izvora (npr. PST i ZIP) ide samo jednom u isti folder.
- Popravlja poruke koje Exchange inače odbije: goli LF umesto CRLF, BOM, NUL bajtovi, pokvarene linije u zaglavlju, poruke bez `Date` / `Message-ID`.
- Obrisane poruke koje Thunderbird, Maildir i Apple Mail još drže na disku se preskaču (`--include-deleted` ih uključuje).
- Kontakti, kalendar i zadaci iz PST/MSG se preskaču (`--include-nonmail` ih uključuje).
- Ako Microsoft uspori slanje (throttling) ili prekine vezu, alat sam pokušava ponovo, a token se sam osvežava.
- Sve greške idu u `mailconv_greske.csv`, a log u `mailconv.log`.

---

## Najlakše: aplikacija na klik (GUI)

Ne moraš da kucaš komande.

| Sistem | Pokretanje |
|---|---|
| **Windows, bez Pythona** | Preuzmi `mailconv.exe`: GitHub → **Actions** → **Windows EXE** → poslednji uspešan run → *Artifacts* → `mailconv-windows`. Raspakuj ZIP i pokreni duplim klikom. |
| **Windows, sa Pythonom** | Dupli klik na **`Pokreni mailconv.bat`**. Pri prvom pokretanju sam instalira potrebne pakete. |
| **Mac / Linux** | Dupli klik na **`Pokreni mailconv (Mac-Linux).command`**. Na Linux-u treba paket `python3-tk`. |

U prozoru:
1. **Dodaj fajlove… / Dodaj folder…** – PST, MSG, EML, MBOX, OLM, ZIP ili ceo folder.
2. Upiši **Mailbox** (npr. `office@firma.rs`), **Client ID** i **Tenant**. Dugme **Uputstvo: podešavanje Microsoft 365…** pokazuje kako se dobijaju, sa gotovim PowerShell komandama.
3. **Test prijave** → otvara se obična Microsoft stranica za prijavu u browseru (email, lozinka, MFA). Prijaviš se nalogom koji ima Full Access i vratiš se u program. Prijava se pamti, pa je sledeći put ne ponavljaš.
4. **Proba (bez slanja)** pokazuje gde bi šta otišlo, a **▶ POKRENI UVOZ** pokreće uvoz.

**Zaustavi** može bilo kad: sledeće pokretanje nastavlja gde je stalo. Podešavanja (bez lozinki i secret-a), log, izveštaj grešaka i baza uvezenih poruka su u folderu `mailconv` u tvom korisničkom folderu. Do njega vodi dugme **Folder sa izveštajima**.

## 1. Instalacija (za komandnu liniju)

Treba ti Python 3.9 ili noviji (Windows, macOS ili Linux).

```bash
pip install -r requirements.txt
```

Za PST/OST dodatno:

```bash
pip install libpff-python
```

Ako `libpff-python` neće da se instalira na Windows-u, pokreni alat u WSL-u (`sudo apt install pst-utils`), pa će koristiti `readpst`.

Alat se pokreće iz foldera repozitorijuma kao `python -m mailconv …`.

## 2. Jednokratno podešavanje u Microsoft 365 (oko 5 minuta, radi admin)

### Varijanta A: prijava korisnika (preporučeno)

Prijavljuješ se nalogom koji ima **Full Access** na shared mailbox. Shared mailbox nema lozinku i to ovde ne smeta.

1. **Entra admin center → App registrations → New registration**
   - Name: `mailconv`, *Accounts in this organizational directory only*.
   - Redirect URI: izaberi **Public client/native (mobile & desktop)** i upiši `http://localhost` → **Register**.
   - Zapiši **Application (client) ID** i **Directory (tenant) ID**.
2. **Authentication** → *Advanced settings* → **Allow public client flows = Yes** → Save. Ako je aplikacija već napravljena bez Redirect URI-ja, ovde dodaj: **Add a platform → Mobile and desktop applications → `http://localhost`**.
3. **API permissions → Add a permission → Microsoft Graph → Delegated** → izaberi `IMAP.AccessAsUser.All` i `offline_access` → **Grant admin consent**.
4. Exchange Online PowerShell (`Connect-ExchangeOnline`):

```powershell
Add-MailboxPermission -Identity office@firma.rs -User admin@firma.rs -AccessRights FullAccess -AutoMapping $false
Set-CASMailbox -Identity office@firma.rs -ImapEnabled $true
Set-Mailbox -Identity office@firma.rs -MaxReceiveSize 150MB -MaxSendSize 150MB
```

Poslednja komanda nije obavezna. Treba samo ako imaš poruke veće od 35 MB.

### Varijanta B: aplikacija bez korisnika (za automatizaciju ili mnogo mailbox-ova)

1. Napravi App registration kao u koraku 1 iznad.
2. **API permissions → Add a permission → APIs my organization uses → Office 365 Exchange Online → Application permissions → `IMAP.AccessAsApp`** → **Grant admin consent**.
3. **Certificates & secrets → New client secret** → zapiši vrednost.
4. U **Enterprise applications** otvori `mailconv` i zapiši njegov **Object ID** (ne onaj iz App registrations).
5. PowerShell:

```powershell
New-ServicePrincipal -AppId <CLIENT_ID> -ObjectId <ENTERPRISE_APP_OBJECT_ID>
Add-MailboxPermission -Identity office@firma.rs -User <ENTERPRISE_APP_OBJECT_ID> -AccessRights FullAccess
Set-CASMailbox -Identity office@firma.rs -ImapEnabled $true
```

## 3. Upotreba

Primeri su u bash sintaksi. Na Windows-u (cmd) umesto `export X=…` koristi `set X=…`, a umesto `\` na kraju reda stavi sve u jedan red ili koristi `^`.

Podesi ID-jeve jednom (umesto `--client-id` i `--tenant` u svakoj komandi):

```bash
export MAILCONV_CLIENT_ID=11111111-2222-3333-4444-555555555555
export MAILCONV_TENANT=firma.onmicrosoft.com
```

**1) Pogledaj šta je pronađeno** (ništa se ne šalje):

```bash
python -m mailconv scan "D:\Stari mejlovi"
```

**2) Proveri prijavu na shared mailbox:**

```bash
python -m mailconv test-login --mailbox office@firma.rs
```

Pri prvom pokretanju otvara se obična Microsoft prijava u browseru. Prijaviš se nalogom koji ima Full Access. Token se pamti u `.mailconv_token_cache.json`, pa se sledeći put ne prijavljuješ ponovo. Na serveru bez browsera dodaj `--login code` za prijavu kodom.

**3) Proba bez slanja** (prikazuje u koji folder ide koliko poruka):

```bash
python -m mailconv upload "D:\Stari mejlovi" --mailbox office@firma.rs --root "Uvoz 2024" --dry-run
```

**4) Uvoz:**

```bash
python -m mailconv upload "D:\Stari mejlovi" arhiva.pst export.zip --mailbox office@firma.rs --root "Uvoz 2024"
```

- `--root "Uvoz 2024"` stavlja sve pod taj folder i tako je najbezbednije. Bez `--root` se spaja sa postojećim folderima: `Inbox`, `Sent`, `Poslato`, `Deleted Items`, `Otpad`, `Spam`… idu u odgovarajuće sistemske foldere mailbox-a, i to radi i kad je mailbox na srpskom (`--no-special-map` to isključuje).
- Prekid sa Ctrl+C ili pad mreže ništa ne kvari: pokreni istu komandu ponovo.
- `--workers 4` je broj paralelnih konekcija. Za Exchange Online je 4–8 razumno.

Varijanta B (aplikacija):

```bash
export MAILCONV_CLIENT_SECRET='...'
python -m mailconv upload ulaz/ --mailbox office@firma.rs --auth app --tenant firma.onmicrosoft.com
```

**Samo konverzija na disk** (bez uvoza), npr. sve u EML ili MBOX:

```bash
python -m mailconv convert arhiva.pst stari.olm -o izlaz/ --format eml
python -m mailconv convert arhiva.pst -o izlaz/ --format mbox
```

**Drugi IMAP serveri** (on-prem Exchange, Dovecot…):

```bash
python -m mailconv upload ulaz/ --mailbox korisnik@firma.rs --auth password --host mail.firma.rs --password '...'
```

## 4. Problemi i rešenja

| Simptom | Rešenje |
|---|---|
| `AUTHENTICATE failed` | 1) `Set-CASMailbox <shared> -ImapEnabled $true`. 2) Prijavljeni korisnik ili aplikacija ima FullAccess na **taj** mailbox. 3) Dat je admin consent. 4) `--tenant` je tačan. 5) Za varijantu B: `New-ServicePrincipal` je urađen sa **Enterprise app** Object ID-jem. Posle izmena prava sačekaj do 30–60 min. |
| `AADSTS7000218 … client_assertion or client_secret` | Nije uključeno *Allow public client flows* (varijanta A). |
| `AADSTS500113` / `AADSTS50011` (reply address) | Fali Redirect URI: App registration → Authentication → Add a platform → Mobile and desktop applications → `http://localhost`. |
| `AADSTS65001 … consent` | Klikni *Grant admin consent* u API permissions. |
| Poruka preko limita | `Set-Mailbox <shared> -MaxReceiveSize 150MB`. Exchange Online ne prima poruke veće od 150 MB. |
| Sporo ili throttling | Normalno je da Microsoft usporava. Alat sam čeka i pokušava ponovo. Smanji `--workers` ako ima mnogo `~` linija u logu. |
| Interni pošiljaoci iz PST-a izgledaju čudno (`IMCEAEX-…`) | Exchange to obično sam razreši na pravog korisnika. Dodaj `--x500-domain firma.rs` (podrazumevano je domen iz `--mailbox`). |
| Neke poruke su u `mailconv_greske.csv` | Pogledaj kolonu „greska“, popravi uzrok i pokreni ponovo. Već uvezene poruke se preskaču. |

## Zašto IMAP, a ne PST import ili Graph

- **PST import (Purview)** traži PST fajl (na Linux/Mac-u ga je teško napraviti), Azure upload preko AzCopy, mapping CSV, čekanje job-a i ponekad tihe greške.
- **Graph API** sa MIME sadržajem pravi poruke kao **draftove**, a JSON uvoz gubi originalna zaglavlja i potpise.
- **EWS** Microsoft gasi u Exchange Online.
- **IMAP APPEND sa OAuth2** čuva poruku bajt po bajt, sa datumom i statusom pročitanosti, i radi sa shared mailbox-om preko Full Access prava.

## Razvoj

```bash
pip install pytest
python -m pytest tests
```
