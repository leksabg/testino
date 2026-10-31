"""Generise PDF vodic: Windows AI radna stanica (VM) sa VS Code, svim modelima i memorijom."""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
                                PageBreak, Table, TableStyle, Preformatted, KeepTogether,
                                NextPageTemplate)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon
from reportlab.platypus.tableofcontents import TableOfContents
import os, sys

F = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("Sans", F + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("Sans-Bold", F + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Sans-Oblique", "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"))
pdfmetrics.registerFont(TTFont("Mono", F + "DejaVuSansMono.ttf"))
from reportlab.pdfbase.pdfmetrics import registerFontFamily
registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans-Oblique", boldItalic="Sans-Bold")

NAVY = colors.HexColor("#0F1B3D")
ACCENT = colors.HexColor("#3B82F6")
ACCENT2 = colors.HexColor("#8B5CF6")
GREEN = colors.HexColor("#10B981")
AMBER = colors.HexColor("#F59E0B")
RED = colors.HexColor("#EF4444")
LIGHT = colors.HexColor("#F1F5F9")
MID = colors.HexColor("#CBD5E1")
TEXT = colors.HexColor("#1E293B")
MUTED = colors.HexColor("#64748B")

body = ParagraphStyle("body", fontName="Sans", fontSize=9.6, leading=14, textColor=TEXT, spaceAfter=5)
small = ParagraphStyle("small", parent=body, fontSize=8.2, leading=11.5, textColor=MUTED)
h1 = ParagraphStyle("h1", fontName="Sans-Bold", fontSize=19, leading=24, textColor=NAVY, spaceBefore=4, spaceAfter=10)
h2 = ParagraphStyle("h2", fontName="Sans-Bold", fontSize=12.5, leading=17, textColor=ACCENT, spaceBefore=10, spaceAfter=5)
h3 = ParagraphStyle("h3", fontName="Sans-Bold", fontSize=10.5, leading=14, textColor=NAVY, spaceBefore=6, spaceAfter=3)
bullet = ParagraphStyle("bullet", parent=body, leftIndent=12, bulletIndent=2, spaceAfter=2.5)
code = ParagraphStyle("code", fontName="Mono", fontSize=7.6, leading=10, textColor=colors.HexColor("#E2E8F0"))
cell = ParagraphStyle("cell", parent=body, fontSize=8.3, leading=11, spaceAfter=0)
cellb = ParagraphStyle("cellb", parent=cell, fontName="Sans-Bold", textColor=colors.white)
toc1 = ParagraphStyle("toc1", fontName="Sans", fontSize=10.5, leading=17, textColor=TEXT, leftIndent=6)


class Doc(BaseDocTemplate):
    def afterFlowable(self, f):
        if isinstance(f, Paragraph) and f.style.name == "h1":
            txt = f.getPlainText()
            key = "h1-%s" % abs(hash(txt))
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(txt, key, level=0)
            self.notify("TOCEntry", (0, txt, self.page, key))


def P(t, s=body):
    return Paragraph(t, s)


def B(items):
    return [Paragraph(i, bullet, bulletText="•") for i in items]


def CODE(txt, title=None):
    pre = Preformatted(txt.strip("\n"), code, maxLineLength=98, newLineChars="      ")
    rows = []
    if title:
        rows.append([Paragraph(title, ParagraphStyle("ct", fontName="Sans-Bold", fontSize=7.5,
                                                     textColor=colors.HexColor("#93C5FD"), leading=9))])
    rows.append([pre])
    t = Table(rows, colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0B1220")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return KeepTogether([t, Spacer(1, 6)])


def BOX(title, text, color=ACCENT):
    t = Table([[Paragraph("<b>%s</b><br/>%s" % (title, text), ParagraphStyle("bx", parent=body, spaceAfter=0))]],
              colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("LINEBEFORE", (0, 0), (0, -1), 3.5, color),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return KeepTogether([t, Spacer(1, 7)])


def TABLE(head, rows, widths, hcolor=NAVY):
    data = [[Paragraph(h, cellb) for h in head]] + [[Paragraph(c, cell) for c in r] for r in rows]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    st = [("BACKGROUND", (0, 0), (-1, 0), hcolor),
          ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("GRID", (0, 0), (-1, -1), 0.4, MID),
          ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
          ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    for i in range(1, len(data)):
        if i % 2 == 0:
            st.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    t.setStyle(TableStyle(st))
    return KeepTogether([t, Spacer(1, 8)])


def box(d, x, y, w, h, fill, title, sub=None, tc=colors.white):
    d.add(Rect(x, y, w, h, rx=5, ry=5, fillColor=fill, strokeColor=None))
    d.add(String(x + w / 2, y + h - 13, title, fontName="Sans-Bold", fontSize=8, fillColor=tc, textAnchor="middle"))
    if sub:
        for i, s in enumerate(sub):
            d.add(String(x + w / 2, y + h - 25 - i * 10, s, fontName="Sans", fontSize=6.6, fillColor=tc, textAnchor="middle"))


def arrow(d, x1, y1, x2, y2, c=MUTED):
    d.add(Line(x1, y1, x2, y2, strokeColor=c, strokeWidth=1.2))
    d.add(Polygon([x2, y2, x2 - 3, y2 + 6, x2 + 3, y2 + 6], fillColor=c, strokeColor=None))


def architecture():
    W = 170 * mm
    d = Drawing(W, 300)
    # VM frame
    d.add(Rect(0, 70, W, 228, rx=8, ry=8, fillColor=colors.HexColor("#EEF2FF"), strokeColor=ACCENT, strokeWidth=1))
    d.add(String(8, 286, "Windows 11 Pro VM  (\"AI-WS\")", fontName="Sans-Bold", fontSize=9, fillColor=NAVY))
    # layer 1: tools
    bw = (W - 40) / 5
    names = [("VS Code", ["Copilot Chat", "Agents window"]), ("Claude Code", ["CLI + ekstenzija"]),
             ("Codex CLI", ["CLI + ekstenzija"]), ("Gemini CLI", ["CLI"]), ("Cline / Kilo", ["agent ekstenzije"])]
    for i, (n, s) in enumerate(names):
        box(d, 8 + i * (bw + 6), 225, bw, 48, ACCENT if i else NAVY, n, s)
    # layer 2: memory + mcp
    box(d, 8, 150, (W - 22) / 2, 55, ACCENT2, "MEMORIJA",
        ["AGENTS.md / CLAUDE.md / GEMINI.md", "Claude auto-memory  •  memory-bank/", "MCP memory graf (C:\\AI\\brain)"])
    box(d, 14 + (W - 22) / 2, 150, (W - 22) / 2, 55, colors.HexColor("#0E7490"), "MCP SERVERI (zajednički)",
        ["memory • filesystem • git/GitHub", "playwright • context7 (docs)", "isti spisak za sve alate"])
    # gateway
    box(d, 8, 80, W - 16, 52, GREEN, "LiteLLM gateway  —  http://localhost:4000  (Docker)",
        ["Jedan URL i jedan ključ za sve modele  •  fallback  •  budžeti  •  logovi troškova"])
    for x in [8 + bw / 2 + i * (bw + 6) for i in range(5)]:
        arrow(d, x, 225, x, 207)
    arrow(d, W / 2, 150, W / 2, 134)
    # providers
    prov = ["Anthropic", "OpenAI", "Google Gemini", "OpenRouter", "Ollama (GPU)"]
    pw = (W - 16 - 4 * 6) / 5
    for i, p in enumerate(prov):
        x = 8 + i * (pw + 6)
        box(d, x, 8, pw, 38, colors.HexColor("#334155") if i < 4 else AMBER, p,
            ["cloud API" if i < 3 else ("300+ modela" if i == 3 else "lokalni modeli")])
        arrow(d, x + pw / 2, 80, x + pw / 2, 48)
    return d


def on_page(c, doc):
    c.saveState()
    c.setFillColor(NAVY)
    c.rect(0, A4[1] - 9 * mm, A4[0], 9 * mm, fill=1, stroke=0)
    c.setFont("Sans", 7.5)
    c.setFillColor(colors.white)
    c.drawString(20 * mm, A4[1] - 6 * mm, "AI radna stanica — vodič za podešavanje")
    c.drawRightString(A4[0] - 20 * mm, A4[1] - 6 * mm, "Verzija: oktobar 2026")
    c.setFillColor(MUTED)
    c.drawRightString(A4[0] - 20 * mm, 10 * mm, "strana %d" % doc.page)
    c.restoreState()


def on_cover(c, doc):
    W, H = A4
    c.saveState()
    c.setFillColor(NAVY)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    # decorative blocks
    for i, col in enumerate([ACCENT, ACCENT2, GREEN, AMBER]):
        c.setFillColor(col)
        c.roundRect(20 * mm + i * 14 * mm, H - 60 * mm, 10 * mm, 10 * mm, 2 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Sans-Bold", 34)
    c.drawString(20 * mm, H - 95 * mm, "AI radna stanica")
    c.setFont("Sans-Bold", 15)
    c.setFillColor(colors.HexColor("#93C5FD"))
    c.drawString(20 * mm, H - 108 * mm, "Windows VM  •  VS Code  •  svi modeli  •  memorija")
    c.setFont("Sans", 11)
    c.setFillColor(colors.HexColor("#CBD5E1"))
    lines = ["Kompletan vodič korak-po-korak: od praznog VM-a do okruženja",
             "u kome Claude, GPT, Gemini, OpenRouter i lokalni modeli rade",
             "zajedno, sa zajedničkim alatima (MCP) i trajnom memorijom."]
    for i, l in enumerate(lines):
        c.drawString(20 * mm, H - 130 * mm - i * 6.5 * mm, l)
    c.setStrokeColor(ACCENT)
    c.setLineWidth(2)
    c.line(20 * mm, 45 * mm, 90 * mm, 45 * mm)
    c.setFont("Sans", 9)
    c.setFillColor(colors.HexColor("#94A3B8"))
    c.drawString(20 * mm, 37 * mm, "Stanje alata: oktobar 2026  •  proveriti verzije pre instalacije")
    c.drawString(20 * mm, 31 * mm, "Jezik: srpski (latinica)")
    c.restoreState()


def build(out):
    doc = Doc(out, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=16 * mm,
              title="AI radna stanica — Windows VM vodič", author="Claude Code", subject="VS Code, multi-model, memorija")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
    doc.addPageTemplates([PageTemplate(id="cover", frames=[frame], onPage=on_cover),
                          PageTemplate(id="main", frames=[frame], onPage=on_page)])
    s = []
    s += [NextPageTemplate("main"), PageBreak()]

    toc = TableOfContents()
    toc.levelStyles = [toc1]
    s += [P("Sadržaj", ParagraphStyle("tt", parent=h1)), toc, PageBreak()]

    # 1 -------------------------------------------------------------
    s.append(P("1. Ukratko — preporučena postavka", h1))
    s.append(P("Posle pregleda aktuelnih izvora (zvanična dokumentacija, release notes, uporedni testovi iz 2026.) "
               "najbolji praktičan pristup danas <b>nije jedan alat</b>, već <b>slojevita postavka</b>: "
               "nekoliko agenata u VS Code-u i terminalu, jedan zajednički <i>gateway</i> kroz koji idu svi modeli, "
               "zajednički MCP alati i memorija koja je ista za sve agente."))
    s.append(architecture())
    s.append(Spacer(1, 6))
    s.append(TABLE(["Sloj", "Šta koristimo", "Zašto"], [
        ["Agenti / UI", "VS Code + GitHub Copilot (Agent mode, BYOK), Claude Code, Codex CLI, Gemini CLI, Cline ili Kilo Code",
         "Svaki vendor ima najbolji agent za svoje modele; Copilot/Cline/Kilo pokrivaju sve ostale modele."],
        ["Pristup modelima", "LiteLLM proxy (lokalno, Docker) + OpenRouter kao „sve ostalo“",
         "Jedan OpenAI-kompatibilan URL za sve; fallback ako provajder padne; kontrola troškova."],
        ["Lokalni modeli", "Ollama (Qwen3-Coder i sl.) na GPU-u",
         "Autocomplete i privatni kod bez slanja u cloud, nula troška po tokenu."],
        ["Alati (MCP)", "memory, filesystem, git/GitHub, Playwright, Context7",
         "Isti alati dostupni svakom agentu — standard koji podržavaju svi."],
        ["Memorija", "AGENTS.md kao jedan izvor istine + Claude auto-memory + MCP memory graf + memory-bank",
         "Agent „pamti“ projekat, pravila i odluke između sesija i između alata."],
    ], [30, 70, 70]))
    s.append(BOX("Važno o stanju tržišta (2026)",
                 "• <b>Roo Code je ugašen</b> (repo arhiviran 15. maja 2026). Ne instalirati ga — naslednici su "
                 "<b>Kilo Code</b> i <b>Cline</b> (oba aktivna).<br/>"
                 "• GitHub Copilot u VS Code-u od aprila 2026. ima <b>BYOK</b> (svoj API ključ: Anthropic, OpenAI, Gemini, "
                 "OpenRouter, Ollama, Custom endpoint). Inline autocomplete i dalje ide preko GitHub-ovih modela.<br/>"
                 "• Za <b>Continue</b> postoje nepotvrđene vesti o akviziciji — koristiti ga samo kao opcioni dodatak.",
                 AMBER))

    # 2 -------------------------------------------------------------
    s.append(PageBreak())
    s.append(P("2. Virtuelna mašina — specifikacija", h1))
    s.append(P("Pošto su resursi dostupni, VM dimenzionišemo tako da istovremeno radi više agenata, Docker (gateway, baza) "
               "i indeksiranje koda. Lokalni modeli zahtevaju GPU — vidi napomenu ispod."))
    s.append(TABLE(["Resurs", "Minimum", "Preporuka", "Napomena"], [
        ["OS", "Windows 11 Pro", "Windows 11 Pro / Enterprise 24H2+", "Gen2 VM, Secure Boot, vTPM (obavezno za Win11)"],
        ["vCPU", "8", "16–24", "Paralelni agenti, Docker, build-ovi"],
        ["RAM", "32 GB", "64–128 GB, <b>statički</b>", "Dinamička memorija isključena (zbog nested virtualizacije)"],
        ["Disk", "256 GB SSD", "512 GB – 1 TB NVMe", "Modeli za Ollama zauzimaju 5–50 GB po modelu"],
        ["GPU", "—", "NVIDIA 24 GB+ VRAM (passthrough)", "Samo ako želite lokalne modele u samom VM-u"],
        ["Mreža", "NAT", "Bridged + statička IP", "Lakši pristup gateway-u sa drugih mašina"],
    ], [22, 30, 50, 68]))
    s.append(P("Hyper-V: kreiranje VM-a (PowerShell kao Administrator na hostu)", h2))
    s.append(CODE(r'''
$vm = "AI-WS"
New-VM -Name $vm -Generation 2 -MemoryStartupBytes 64GB `
       -NewVHDPath "D:\VMs\$vm\$vm.vhdx" -NewVHDSizeBytes 768GB -SwitchName "External"
Set-VMProcessor -VMName $vm -Count 16 -ExposeVirtualizationExtensions $true   # nested virt za Docker/WSL2
Set-VMMemory    -VMName $vm -DynamicMemoryEnabled $false
Set-VMKeyProtector -VMName $vm -NewLocalKeyProtector
Enable-VMTPM    -VMName $vm
Set-VMFirmware  -VMName $vm -EnableSecureBoot On
Add-VMDvdDrive  -VMName $vm -Path "D:\ISO\Win11_24H2.iso"
Start-VM $vm
''', "host  •  PowerShell (Admin)"))
    s.append(BOX("GPU i lokalni modeli — realna preporuka",
                 "Na <b>Proxmox / ESXi</b> hostu: PCIe passthrough NVIDIA kartice direktno u VM — radi pouzdano.<br/>"
                 "Na <b>Hyper-V</b>: DDA postoji samo na Windows Server hostu; GPU-P na Windows 11 klijentu je nezvaničan.<br/>"
                 "<b>Najčistija opcija:</b> Ollama na zasebnoj Linux GPU mašini (ili na hostu), a VM se na nju kači preko "
                 "<font name='Mono'>http://&lt;gpu-host&gt;:11434</font>. VM ostaje lagan, a GPU deli ceo tim.", ACCENT2))
    s.append(P("Higijena VM-a", h2))
    s += B(["Posle svake faze ovog vodiča napraviti <b>checkpoint/snapshot</b> (npr. „01-base“, „02-tools“, „03-ai-configured“).",
            "Poseban lokalni korisnik bez admin prava za svakodnevni rad; admin samo za instalacije.",
            "Uključiti BitLocker (vTPM) — na disku će biti API ključevi i kod.",
            "Kada je sve podešeno: exportovati VM kao <b>zlatnu sliku</b> i klonirati je za ostale članove tima."])

    # 3 -------------------------------------------------------------
    s.append(PageBreak())
    s.append(P("3. Osnovni softver (jedna skripta)", h1))
    s.append(P("Sve instaliramo preko <b>winget</b>-a da bi postavka bila ponovljiva. Pokrenuti u VM-u kao Administrator:"))
    s.append(CODE(r'''
# 01-base.ps1  —  osnovni alati
$apps = @(
  "Microsoft.PowerShell", "Microsoft.WindowsTerminal", "Git.Git", "GitHub.cli",
  "Microsoft.VisualStudioCode", "OpenJS.NodeJS.LTS", "Python.Python.3.12", "astral-sh.uv",
  "Docker.DockerDesktop", "Ollama.Ollama", "BurntSushi.ripgrep.MSVC", "jqlang.jq",
  "Bitwarden.Bitwarden"   # ili drugi menadžer lozinki za API ključeve
)
foreach ($a in $apps) { winget install --id $a -e --accept-source-agreements --accept-package-agreements }

wsl --install -d Ubuntu          # WSL2 (Docker backend + Linux alati)
git config --global core.autocrlf input
git config --global init.defaultBranch main
# Developer Mode -> dozvoljava symlinkove bez admina (trebaće za deljenu memoriju)
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock" /t REG_DWORD /f /v "AllowDevelopmentWithoutDevLicense" /d "1"
Restart-Computer
''', "VM  •  PowerShell (Admin)"))
    s.append(P("CLI agenti", h2))
    s.append(CODE(r'''
# 02-agents.ps1  —  agenti u terminalu (novi PowerShell prozor posle restarta)
irm https://claude.ai/install.ps1 | iex      # Claude Code (native installer)
npm install -g @openai/codex                # OpenAI Codex CLI
npm install -g @google/gemini-cli           # Gemini CLI
claude --version; codex --version; gemini --version
''', "VM  •  PowerShell"))
    s.append(P("Svaki CLI se prijavljuje pretplatom (Claude Pro/Max, ChatGPT Plus/Pro, Google nalog) ili API ključem. "
               "Za intenzivan agentski rad <b>pretplate su po pravilu dosta jeftinije od plaćanja po tokenu</b>; API ključeve "
               "čuvamo za gateway, automatizaciju i modele bez pretplate."))
    s.append(P("VS Code ekstenzije", h2))
    s.append(CODE(r'''
code --install-extension GitHub.copilot-chat
code --install-extension anthropic.claude-code
code --install-extension openai.chatgpt              # Codex ekstenzija
code --install-extension saoudrizwan.claude-dev      # Cline
code --install-extension kilocode.kilo-code          # Kilo Code (naslednik Roo Code-a)
code --install-extension ms-vscode-remote.remote-wsl
code --install-extension eamodio.gitlens
''', "VM  •  PowerShell"))
    s.append(P("ID-jeve ekstenzija proveriti na Marketplace-u pre pokretanja — izdavači ponekad menjaju naziv. "
               "Ne instalirati sve agent-ekstenzije odjednom ako ne treba: <b>Cline ILI Kilo Code</b> je dovoljno.", small))

    # 4 -------------------------------------------------------------
    s.append(PageBreak())
    s.append(P("4. API ključevi i bezbednost", h1))
    s += B(["Ključeve držati u menadžeru lozinki; u VM ih upisati kao <b>korisničke environment varijable</b>, nikad u repo.",
            "Svaki provajder: postaviti <b>mesečni limit potrošnje</b> na svom dashboard-u (Anthropic, OpenAI, Google, OpenRouter).",
            "Za tim: svako dobija svoj <b>virtuelni ključ</b> na LiteLLM gateway-u (sa budžetom), a pravi ključevi ostaju samo na gateway-u."])
    s.append(CODE(r'''
# 03-keys.ps1  —  jednom, kao običan korisnik
[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY",  "sk-ant-...", "User")
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY",     "sk-...",     "User")
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY",     "AIza...",    "User")
[Environment]::SetEnvironmentVariable("OPENROUTER_API_KEY", "sk-or-...",  "User")
[Environment]::SetEnvironmentVariable("LITELLM_MASTER_KEY", "sk-local-" + [guid]::NewGuid(), "User")
''', "VM  •  PowerShell"))
    s.append(BOX("Pravila za agente (stavite ih u AGENTS.md)",
                 "Agent nikad ne commit-uje <font name='Mono'>.env</font> i ključeve • destruktivne komande (brisanje, force push, "
                 "drop baze) traže potvrdu • rad na posebnoj grani, PR umesto direktnog push-a na main. "
                 "U Claude Code-u to se dodatno sprovodi kroz <font name='Mono'>permissions</font> u settings.json "
                 "(<font name='Mono'>deny</font> pravila za opasne komande).", RED))

    # 5 -------------------------------------------------------------
    s.append(P("5. Gateway: svi modeli preko jednog URL-a", h1))
    s.append(P("Ovo je deo koji omogućava da „jurite sve dostupne modele“. <b>LiteLLM</b> je open-source proxy koji izlaže "
               "jedan OpenAI-kompatibilan endpoint (<font name='Mono'>http://localhost:4000/v1</font>) i iza njega rutira ka bilo "
               "kom provajderu. Bilo koja ekstenzija koja podržava „OpenAI compatible“ provajdera (Copilot Custom Endpoint, Cline, "
               "Kilo, Continue…) odmah vidi sve modele. <b>OpenRouter</b> dodajemo kao „sve ostalo“ — stotine modela preko jednog "
               "ključa (uz malu proviziju), bez dodatnog podešavanja."))
    s.append(CODE(r'''
# C:\AI\gateway\config.yaml
model_list:
  # --- Anthropic ---
  - model_name: claude-opus
    litellm_params: { model: anthropic/claude-opus-5-5,   api_key: os.environ/ANTHROPIC_API_KEY }
  - model_name: claude-sonnet
    litellm_params: { model: anthropic/claude-sonnet-5-5, api_key: os.environ/ANTHROPIC_API_KEY }
  - model_name: claude-haiku
    litellm_params: { model: anthropic/claude-haiku-5-5,  api_key: os.environ/ANTHROPIC_API_KEY }
  # --- OpenAI / Google (upisati aktuelne ID-jeve modela sa njihovih stranica) ---
  - model_name: gpt
    litellm_params: { model: openai/<NAJNOVIJI-GPT>,         api_key: os.environ/OPENAI_API_KEY }
  - model_name: gemini-pro
    litellm_params: { model: gemini/<NAJNOVIJI-GEMINI-PRO>,  api_key: os.environ/GEMINI_API_KEY }
  # --- sve sa OpenRouter-a: npr. "openrouter/deepseek/..." ---
  - model_name: openrouter/*
    litellm_params: { model: openrouter/*, api_key: os.environ/OPENROUTER_API_KEY }
  # --- lokalno (Ollama na hostu ili GPU serveru) ---
  - model_name: local-coder
    litellm_params: { model: ollama_chat/qwen3-coder:30b, api_base: http://host.docker.internal:11434 }

router_settings:
  num_retries: 2
  fallbacks:
    - { claude-opus: [gpt, gemini-pro] }
    - { gpt: [claude-sonnet] }

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL        # potrošnja, virtuelni ključevi, budžeti
''', "config.yaml"))
    s.append(CODE(r'''
# C:\AI\gateway\docker-compose.yml
services:
  litellm:
    image: ghcr.io/berriai/litellm:main-stable
    command: ["--config", "/app/config.yaml", "--port", "4000"]
    ports: ["4000:4000"]
    volumes: ["./config.yaml:/app/config.yaml:ro"]
    environment:
      - ANTHROPIC_API_KEY
      - OPENAI_API_KEY
      - GEMINI_API_KEY
      - OPENROUTER_API_KEY
      - LITELLM_MASTER_KEY
      - DATABASE_URL=postgresql://llm:llm@db:5432/litellm
    depends_on: [db]
    restart: unless-stopped
  db:
    image: postgres:16
    environment: { POSTGRES_USER: llm, POSTGRES_PASSWORD: llm, POSTGRES_DB: litellm }
    volumes: ["pgdata:/var/lib/postgresql/data"]
    restart: unless-stopped
volumes: { pgdata: {} }
''', "docker-compose.yml   →   cd C:\\AI\\gateway; docker compose up -d"))
    s.append(P("Provera: <font name='Mono'>http://localhost:4000/ui</font> (admin panel: modeli, potrošnja, ključevi). "
               "Test iz PowerShell-a:"))
    s.append(CODE(r'''
$h = @{ Authorization = "Bearer $env:LITELLM_MASTER_KEY" }
Invoke-RestMethod http://localhost:4000/v1/models -Headers $h | % data | % id
''', "test"))

    # 6 -------------------------------------------------------------
    s.append(PageBreak())
    s.append(P("6. Povezivanje alata sa modelima", h1))
    s.append(P("6.1 GitHub Copilot (VS Code) — BYOK", h2))
    s += B(["Chat panel → birač modela → <b>Manage Models…</b> (otvara se Language Models editor).",
            "Dodati provajdere: <b>Anthropic</b>, <b>OpenAI</b>, <b>Gemini</b>, <b>OpenRouter</b>, <b>Ollama</b> — nalepiti ključ i označiti modele.",
            "Za gateway: provajder <b>Custom Endpoint / OpenAI Compatible</b>, URL <font name='Mono'>http://localhost:4000/v1</font>, ključ = LITELLM_MASTER_KEY (ili virtuelni ključ).",
            "U <b>Agent mode</b> se vide samo modeli koji podržavaju <i>tool calling</i>; lokalni model koji „nestane“ u Agent modu nema tu podršku.",
            "Ograničenja: inline autocomplete ostaje na GitHub modelima; admin organizacije može da isključi BYOK politikom."])
    s.append(P("6.2 Cline / Kilo Code", h2))
    s += B(["Settings → API Provider: <b>OpenAI Compatible</b> → Base URL <font name='Mono'>http://localhost:4000/v1</font>, ključ, Model ID (npr. <font name='Mono'>claude-sonnet</font>).",
            "Alternativa bez gateway-a: provajder <b>OpenRouter</b> — direktno bira bilo koji od stotina modela.",
            "Kilo Code ima režime (Architect / Code / Debug / Ask) — za svaki režim može drugi model: skup model za planiranje, jeftin za izvršavanje."])
    s.append(P("6.3 Claude Code, Codex, Gemini CLI", h2))
    s += B(["Najbolje rade sa <b>svojim</b> modelima i sopstvenom prijavom (pretplata) — tako ih i koristimo.",
            "Claude Code u VS Code-u: ekstenzija daje panel, diff pregled i deli kontekst otvorenih fajlova. Model se menja komandom <font name='Mono'>/model</font>.",
            "Opciono: Claude Code može kroz gateway (<font name='Mono'>ANTHROPIC_BASE_URL=http://localhost:4000</font>) radi centralnog logovanja troškova.",
            "Codex i Gemini CLI se mogu pokretati iz VS Code terminala; obe imaju i ekstenzije/integracije sa editorom."])
    s.append(P("6.4 Lokalni modeli (Ollama)", h2))
    s.append(CODE(r'''
ollama pull qwen3-coder:30b        # ~19 GB, MoE; komforno na 24 GB VRAM
ollama pull qwen3:14b              # za 12 GB kartice
ollama pull nomic-embed-text       # embeddings za indeksiranje koda / RAG
# Ollama na drugoj mašini: na toj mašini OLLAMA_HOST=0.0.0.0, pa u VM-u koristiti http://<gpu-host>:11434
''', "Ollama"))
    s.append(P("Lokalni modeli su odlični za autocomplete, brza pitanja i poverljiv kod; za složene višekoračne agentske zadatke "
               "frontier cloud modeli su i dalje znatno pouzdaniji."))

    s.append(PageBreak())
    s.append(P("6.5 Koji model za šta", h2))
    s.append(TABLE(["Zadatak", "Preporuka", "Alat"], [
        ["Veliki refaktor, nova funkcionalnost, agent koji radi satima", "Claude Opus (ili Sonnet za brzinu/cenu)", "Claude Code"],
        ["Drugo mišljenje, code review, teški bagovi", "Najnoviji GPT (Codex)", "Codex CLI / Copilot"],
        ["Ogroman kontekst (ceo monorepo, dugački logovi, PDF-ovi)", "Gemini Pro", "Gemini CLI / Copilot"],
        ["Planiranje → izvršavanje", "Skup model planira, jeftin izvršava", "Kilo Code režimi / Cline Plan-Act"],
        ["Isprobavanje novih modela (DeepSeek, Qwen, Mistral, Grok…)", "OpenRouter", "Cline / Kilo / Copilot BYOK"],
        ["Autocomplete, privatni kod, offline", "Qwen3-Coder lokalno", "Ollama + Copilot/Continue/Kilo"],
        ["Jeftini pomoćni poslovi (commit poruke, sažeci)", "Claude Haiku ili mali lokalni model", "bilo koji"],
    ], [62, 55, 53]))
    s.append(P("Rangiranja modela se menjaju svakih par meseci — gateway sloj vam omogućava da promenite model "
               "u jednoj liniji config-a bez diranja alata.", small))

    # 7 -------------------------------------------------------------
    s.append(PageBreak())
    s.append(P("7. Memorija — kako agenti „pamte“", h1))
    s.append(P("Modeli sami ne pamte ništa između sesija. „Pamćenje“ se pravi od fajlova i alata koje agent čita na početku "
               "i dopunjuje tokom rada. Koristimo <b>četiri nivoa</b>:"))
    s.append(TABLE(["Nivo", "Šta je", "Ko piše", "Kada se učitava"], [
        ["1. Instrukcije", "AGENTS.md (Codex, Copilot, Cline, Kilo…), CLAUDE.md (Claude), GEMINI.md (Gemini)",
         "Vi (i agent na zahtev)", "Automatski na početku svake sesije"],
        ["2. Auto-memorija", "Claude Code sam beleži naučeno u MEMORY.md pod ~/.claude/projects/…",
         "Agent", "Automatski (početak fajla)"],
        ["3. Memory bank", "Folder memory-bank/ u repou: kontekst, odluke, napredak (Markdown)",
         "Agent po pravilu iz AGENTS.md", "Agent ga čita na početku zadatka"],
        ["4. MCP memory graf", "Entiteti/relacije/opažanja u JSON-u, dostupni svim agentima kao alat",
         "Agent preko MCP alata", "Na zahtev (pretraga)"],
    ], [26, 64, 38, 42], ACCENT2))

    s.append(P("7.1 Jedan izvor istine za sve alate", h2))
    s.append(P("Pravimo folder <font name='Mono'>C:\\AI\\brain</font> (git repo, može na privatni GitHub radi backup-a i deljenja "
               "između VM-ova). Globalna pravila pišemo jednom u <font name='Mono'>AGENTS.md</font>, a svaki alat dobija link ka tom fajlu:"))
    s.append(CODE(r'''
# 04-memory.ps1
$brain = "C:\AI\brain"; New-Item -ItemType Directory -Force $brain, "$brain\memory" | Out-Null
cd $brain; git init

# globalna pravila -> svaki alat ih čita iz svog standardnog mesta
New-Item -ItemType Directory -Force "$HOME\.claude", "$HOME\.codex", "$HOME\.gemini" | Out-Null
New-Item -ItemType SymbolicLink -Force -Path "$HOME\.codex\AGENTS.md"  -Target "$brain\AGENTS.md"
New-Item -ItemType SymbolicLink -Force -Path "$HOME\.gemini\GEMINI.md" -Target "$brain\AGENTS.md"
Set-Content "$HOME\.claude\CLAUDE.md" "@$brain\AGENTS.md"     # Claude: import sintaksa @putanja
''', "VM  •  PowerShell (Developer Mode uključen)"))
    s.append(P("U svakom projektu isto: <font name='Mono'>AGENTS.md</font> u korenu repoa, a <font name='Mono'>CLAUDE.md</font> "
               "sadrži samo liniju <font name='Mono'>@AGENTS.md</font>. Za Gemini CLI u <font name='Mono'>~/.gemini/settings.json</font> "
               "dodati da čita i AGENTS.md (<font name='Mono'>\"context\": {\"fileName\": [\"AGENTS.md\", \"GEMINI.md\"]}</font>; "
               "u starijim verzijama ključ <font name='Mono'>contextFileName</font>)."))
    s.append(CODE(r'''
# AGENTS.md  (globalni primer — kratko i konkretno, ispod ~200 linija)
## Ko sam i kako radim
- Odgovaraj na srpskom, kod i komentari na engleskom.
- Stack: <upišite: .NET / Node / Python...>. Testovi pre svakog commit-a.
## Pravila
- Nikad ne commit-uj tajne (.env, ključevi). Destruktivne komande samo uz potvrdu.
- Radi na posebnoj grani; male, opisne commit poruke.
## Memorija
- Na početku zadatka pročitaj memory-bank/ (ako postoji) i pretraži MCP "memory".
- Kada doneseš važnu odluku ili naučiš nešto o projektu: zapiši u memory-bank/
  (activeContext.md, progress.md) i dodaj opažanje u MCP memory graf.
''', "AGENTS.md"))

    s.append(KeepTogether([P("7.2 Memory bank (po projektu)", h2),
              P("Popularan obrazac iz Cline zajednice, radi sa svim agentima jer je samo Markdown u repou:"),
              CODE(r'''
memory-bank/
  projectbrief.md     # šta pravimo i zašto (piše čovek)
  productContext.md   # korisnici, problemi, ciljevi
  systemPatterns.md   # arhitektura, ključne odluke (ADR ukratko)
  techContext.md      # stack, komande, okruženje
  activeContext.md    # na čemu se trenutno radi, sledeći koraci
  progress.md         # šta je gotovo, šta ne radi, poznati bagovi
''', "struktura")]))

    s.append(P("7.3 MCP memory graf (deljen između svih agenata)", h2))
    s.append(P("Zvanični <font name='Mono'>@modelcontextprotocol/server-memory</font> čuva entitete i relacije u jednom JSON fajlu. "
               "Pošto svi alati gađaju <b>isti fajl</b>, ono što Claude zapamti, vidi i Copilot/Codex/Gemini."))

    # 8 -------------------------------------------------------------
    s.append(PageBreak())
    s.append(P("8. Zajednički MCP serveri", h1))
    s.append(P("MCP (Model Context Protocol) je standard kojim agenti dobijaju alate. Podesimo isti skup u svakom alatu:"))
    s.append(TABLE(["Server", "Paket / URL", "Čemu služi"], [
        ["memory", "@modelcontextprotocol/server-memory", "Trajna memorija (graf znanja)"],
        ["filesystem", "@modelcontextprotocol/server-filesystem", "Pristup dozvoljenim folderima (npr. C:\\AI, C:\\src)"],
        ["github", "https://api.githubcopilot.com/mcp/", "Issues, PR-ovi, review (zvanični GitHub MCP, remote)"],
        ["playwright", "@playwright/mcp", "Agent otvara browser, testira UI, pravi screenshot-ove"],
        ["context7", "@upstash/context7-mcp", "Aktuelna dokumentacija biblioteka (manje izmišljenih API-ja)"],
    ], [24, 66, 80], colors.HexColor("#0E7490")))
    s.append(CODE(r'''
// VS Code (Copilot, i ekstenzije koje čitaju VS Code MCP):  %APPDATA%\Code\User\mcp.json
// ili po projektu: .vscode/mcp.json
{
  "servers": {
    "memory": {
      "command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"],
      "env": { "MEMORY_FILE_PATH": "C:\\AI\\brain\\memory\\memory.json" }
    },
    "filesystem": {
      "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\AI", "C:\\src"]
    },
    "playwright": { "command": "npx", "args": ["-y", "@playwright/mcp@latest"] },
    "context7":   { "command": "npx", "args": ["-y", "@upstash/context7-mcp"] },
    "github":     { "type": "http", "url": "https://api.githubcopilot.com/mcp/" }
  }
}
''', "mcp.json  (VS Code)"))
    s.append(CODE(r'''
# Claude Code — korisnički nivo (važi u svim projektima). Na Windows-u npx ide kroz "cmd /c".
claude mcp add memory -s user -e MEMORY_FILE_PATH=C:\AI\brain\memory\memory.json -- cmd /c npx -y @modelcontextprotocol/server-memory
claude mcp add playwright -s user -- cmd /c npx -y @playwright/mcp@latest
claude mcp add context7   -s user -- cmd /c npx -y @upstash/context7-mcp
claude mcp list
''', "Claude Code"))
    s.append(CODE(r'''
# Codex — %USERPROFILE%\.codex\config.toml
[mcp_servers.memory]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-memory"]
env = { MEMORY_FILE_PATH = 'C:\AI\brain\memory\memory.json' }

// Gemini CLI — %USERPROFILE%\.gemini\settings.json
{ "context": { "fileName": ["AGENTS.md", "GEMINI.md"] },
  "mcpServers": { "memory": { "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"],
      "env": { "MEMORY_FILE_PATH": "C:\\AI\\brain\\memory\\memory.json" } } } }
''', "Codex + Gemini"))
    s.append(P("Cline i Kilo Code imaju svoj MCP panel (ikonica servera u ekstenziji → Edit config) sa istim "
               "<font name='Mono'>mcpServers</font> formatom kao gore. Ne dodavati desetine servera: svaki alat troši kontekst modela — "
               "5–8 dobro izabranih je optimum.", small))

    # 9 -------------------------------------------------------------
    s.append(PageBreak())
    s.append(P("9. Svakodnevni rad: više agenata paralelno", h1))
    s += B(["<b>Git worktree po agentu</b>: svaki agent radi u svom folderu i grani, bez sudaranja — "
            "<font name='Mono'>git worktree add ..\\proj-feat-x -b feat/x</font>.",
            "<b>VS Code Agents window</b> i Claude Code sub-agenti: jedan zadatak se deli na delove (istraživanje, implementacija, testovi).",
            "<b>Unakrsni review</b>: kod koji napiše Claude da pregleda GPT (Codex), i obrnuto — hvata greške koje jedan model sistematski ne vidi.",
            "<b>Plan pre koda</b>: za veće zadatke tražiti plan (Claude Code plan mode, Kilo Architect, Cline Plan), pa tek onda izvršavanje.",
            "<b>Kraj sesije</b>: „ažuriraj memory-bank i zapamti odluke“ — tako sledeća sesija (bilo kog agenta) kreće od iste tačke.",
            "<b>Troškovi</b>: Agent mod troši višestruko više tokena od običnog chata; pratiti dashboard na "
            "<font name='Mono'>localhost:4000/ui</font> i provajderske limite."])
    s.append(P("Struktura foldera u VM-u", h2))
    s.append(CODE(r'''
C:\AI\
  brain\                 # git repo: globalni AGENTS.md, memory\memory.json, beleške
  gateway\               # LiteLLM config.yaml + docker-compose.yml
  scripts\               # 01-base.ps1, 02-agents.ps1, 03-keys.ps1, 04-memory.ps1
C:\src\                  # projekti (svaki sa AGENTS.md, CLAUDE.md -> @AGENTS.md, memory-bank\)
''', "layout"))

    s.append(P("10. Kontrolna lista", h1))
    checks = ["VM: Gen2, vTPM, 16+ vCPU, 64 GB statički RAM, nested virtualization, BitLocker",
              "winget osnovni paket + WSL2 + Docker Desktop radi (<font name='Mono'>docker run hello-world</font>)",
              "Claude Code, Codex CLI, Gemini CLI instalirani i prijavljeni",
              "VS Code: Copilot Chat, Claude Code, Codex, Cline ili Kilo Code",
              "API ključevi kao User env varijable + limiti potrošnje kod provajdera",
              "LiteLLM gateway gore, <font name='Mono'>/v1/models</font> vraća sve modele, fallback testiran",
              "Copilot BYOK + Cline/Kilo povezani na gateway ili OpenRouter",
              "Ollama: lokalni coder model + embeddings (u VM-u ili na GPU serveru)",
              "C:\\AI\\brain: globalni AGENTS.md povezan za Claude/Codex/Gemini",
              "MCP serveri (memory, filesystem, github, playwright, context7) u svim alatima, isti memory.json",
              "Test: kažete Claude-u „zapamti X“, pa pitate Codex/Copilot „šta znaš o X?“ — mora da zna",
              "Snapshot „03-ai-configured“ + export zlatne slike"]
    rows = [[Paragraph("☐", ParagraphStyle("cb", parent=body, fontSize=12, spaceAfter=0)), Paragraph(c, cell)] for c in checks]
    t = Table(rows, colWidths=[8 * mm, 162 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, MID),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    s.append(t)

    # 11 ------------------------------------------------------------
    s.append(PageBreak())
    s.append(P("11. Izvori i napomene", h1))
    s.append(P("Vodič je zasnovan na pretrazi aktuelnih izvora (oktobar 2026). Deo izvora su blogovi i uporedni sajtovi; "
               "ključne tvrdnje su proverene kroz više izvora, ali <b>pre instalacije proverite zvaničnu dokumentaciju</b> — "
               "alati se menjaju mesečno."))
    src = [
        ("GitHub Copilot BYOK u VS Code-u (Anthropic, Ollama, Foundry Local)", "https://startdebugging.net/2026/04/github-copilot-vs-code-byok-anthropic-ollama-foundry-local/"),
        ("Copilot Agent mode — vodič", "https://lucaberton.com/blog/github-copilot-agent-mode-vscode-complete-guide/"),
        ("GitHub release notes (BYOK, Custom Endpoint, Agents window)", "https://releasebot.io/updates/github"),
        ("Kilo Code vs Roo Code posle gašenja", "https://kilo.ai/kilo-code/vs/roo-code"),
        ("Cline vs Kilo Code vs Roo Code (2026)", "https://agentscamp.com/guides/comparisons/cline-vs-kilo-code-vs-roo-code"),
        ("Roo Code vs Cline — razlike i migracija", "https://fast.io/resources/roo-code-vs-cline/"),
        ("Open-source AI coding asistenti — vodič 2026", "https://www.morphllm.com/ai-coding-assistant-open-source"),
        ("OpenRouter vs LiteLLM (2026)", "https://gateway.orq.ai/blog/openrouter-vs-litellm"),
        ("Portkey vs LiteLLM vs OpenRouter", "https://www.pkgpulse.com/guides/portkey-vs-litellm-vs-openrouter-llm-gateway-2026"),
        ("Agentic primitives: Codex CLI vs Claude Code vs Gemini CLI", "https://codex.danielvaughan.com/2026/03/26/agentic-primitives-codex-claude-gemini/"),
        ("Claude Code vs Codex CLI vs Gemini CLI", "https://www.deployhq.com/blog/comparing-claude-code-openai-codex-and-google-gemini-cli-which-ai-coding-assistant-is-right-for-your-deployment-workflow"),
        ("Knowledge Graph Memory MCP server", "https://playbooks.com/mcp/modelcontextprotocol-knowledge-graph-memory"),
        ("Docker MCP — memory server", "https://hub.docker.com/mcp/server/memory/manual"),
        ("LLM-ovi na Windows-u — podešavanje", "https://llmhardware.io/guides/how-to-run-llms-on-windows"),
        ("Ollama — coding modeli", "https://registry.ollama.ai/blog/coding-models"),
        ("Zvanično: Claude Code docs", "https://code.claude.com/docs"),
        ("Zvanično: LiteLLM proxy docs", "https://docs.litellm.ai/docs/simple_proxy"),
        ("Zvanično: MCP serveri", "https://github.com/modelcontextprotocol/servers"),
    ]
    for t_, u in src:
        s.append(Paragraph('%s<br/><font name="Mono" size="7" color="#3B82F6"><a href="%s">%s</a></font>' % (t_, u, u),
                           ParagraphStyle("src", parent=body, fontSize=8.6, leading=11.5, spaceAfter=4)))
    s.append(Spacer(1, 8))
    s.append(BOX("Nepotvrđeno / pratiti",
                 "• Vesti o akviziciji Continue-a (jun 2026) — nisu potvrđene iz zvaničnih izvora.<br/>"
                 "• Navodi o premeštanju besplatnog Gemini CLI nivoa u zaseban alat — proveriti na Google stranicama.<br/>"
                 "• ID-jeve GPT i Gemini modela u config.yaml upisati sa zvaničnih stranica provajdera u trenutku instalacije.",
                 AMBER))

    doc.multiBuild(s)


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "AI-radna-stanica-vodic.pdf")
