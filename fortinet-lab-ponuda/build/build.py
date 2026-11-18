"""Build the Fortinet test-lab proposal PDF (mid + enterprise setup).

All prices live in ITEMS below: list price (MSRP, USD) from public price lists
of authorized resellers, November 2026. Net price = list x (1 - DISCOUNT),
rounded to cents per unit; line total = net unit x quantity.
usage: python3 build/build.py
"""
import pathlib
import subprocess
from decimal import Decimal, ROUND_HALF_UP

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
HTML = DIST / "index.html"
PDF = DIST / "Fortinet-test-lab-srednji-i-enterprise-2026.pdf"

DISCOUNT = Decimal("0.45")
CENT = Decimal("0.01")

# sku: (name shown in tables, short role, list price USD, price source)
ITEMS = {
    "FG-30G-BDL-950-12": ("FortiGate 30G + UTP 1 god.", "FortiLink i WLAN kontroler", Decimal("855.50"), "SHI MSRP"),
    "FG-50G-BDL-950-12": ("FortiGate 50G + UTP 1 god.", "filijala (SD-WAN spoke)", Decimal("1362.50"), "SHI / AVFirewalls"),
    "FG-120G-BDL-809-12": ("FortiGate 120G + Enterprise 1 god.", "HQ, HA par", Decimal("7416.00"), "CDW / SHI MSRP"),
    "FS-108F-FPOE": ("FortiSwitch 108F-FPOE", "access, 8× PoE+ (130 W)", Decimal("594.00"), "SHI MSRP"),
    "FS-424E": ("FortiSwitch 424E", "MCLAG core, 4× 10G SFP+", Decimal("1637.00"), "SHI / AVFirewalls"),
    "FAP-231K-E": ("FortiAP 231K (Wi-Fi 7)", "access point", Decimal("654.00"), "SHI MSRP"),
    "SP-CABLE-FS-SFP+1": ("DAC kabl 10G SFP+, 1 m", "FortiLink 10G i ICL", Decimal("104.00"), "Ingram Micro"),
    "FC1-10-FMGVS-258-01-12": ("FortiManager-VM, 10 uređaja", "upravljanje, 1 god.", Decimal("403.52"), "SHI MSRP"),
    "FC1-10-AZVMS-465-01-12": ("FortiAnalyzer-VM, 5 GB/dan", "logovi i SOC, 1 god.", Decimal("1265.00"), "AVFirewalls / CDW-G"),
    "FAC-VM (bez licence)": ("FortiAuthenticator-VM", "RADIUS, 802.1X, MFA (5 korisnika)", Decimal("0"), "besplatno, ne ističe"),
    "FCT-EMS (trial)": ("FortiClient EMS (trial)", "ZTNA, 3 uređaja", Decimal("0"), "besplatno, ne ističe"),
    "GPI-130": ("PoE injektor 802.3at (GPI-130)", "napajanje AP-a, 30G nema PoE", Decimal("164.00"), "Ingram Micro / CDW"),
}

# cheap setup from the earlier conversation: cheapest FortiGate + 2 AP (+ PoE, the 30G has none)
CHEAP = [("FG-30G-BDL-950-12", 1), ("FAP-231K-E", 2), ("GPI-130", 2)]
MID = [("FG-30G-BDL-950-12", 1), ("FS-108F-FPOE", 2), ("FAP-231K-E", 2)]
ENT = [
    ("FG-120G-BDL-809-12", 2), ("FG-50G-BDL-950-12", 2), ("FS-424E", 2),
    ("FS-108F-FPOE", 2), ("FAP-231K-E", 3), ("SP-CABLE-FS-SFP+1", 6),
    ("FC1-10-FMGVS-258-01-12", 1), ("FC1-10-AZVMS-465-01-12", 1),
    ("FAC-VM (bez licence)", 1), ("FCT-EMS (trial)", 1),
]
# what the mid setup already brings to the enterprise one
REUSED = {"FS-108F-FPOE": 2, "FAP-231K-E": 2}
# what the mid setup adds on top of the cheap one (FortiGate + 2 AP)
MID_ADDON = [("FS-108F-FPOE", 2)]


def net(sku):
    return (ITEMS[sku][2] * (1 - DISCOUNT)).quantize(CENT, ROUND_HALF_UP)


def lines(bom):
    out = []
    for sku, qty in bom:
        name, role, lst, src = ITEMS[sku]
        out.append(dict(sku=sku, name=name, role=role, qty=qty, list=lst,
                        net=net(sku), total=net(sku) * qty, list_total=lst * qty, src=src))
    return out


def totals(bom):
    ls = lines(bom)
    return sum(l["list_total"] for l in ls), sum(l["total"] for l in ls)


def money(d):
    s = f"{d:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " $"


def bom_table(bom):
    rows = []
    for l in lines(bom):
        free = l["list"] == 0
        rows.append(
            f'<tr><td><b>{l["name"]}</b><span class="sku">{l["sku"]}</span></td>'
            f'<td>{l["role"]}</td><td class="num c">{l["qty"]}</td>'
            f'<td class="num r">{"—" if free else money(l["list"])}</td>'
            f'<td class="num r">{"0,00 $" if free else money(l["net"])}</td>'
            f'<td class="num r"><b>{"0,00 $" if free else money(l["total"])}</b></td></tr>')
    lt, nt = totals(bom)
    rows.append(f'<tr class="tot"><td colspan="3">Ukupno</td><td class="num r">{money(lt)}</td>'
                f'<td></td><td class="num r">{money(nt)}</td></tr>')
    return ('<table class="bom"><thead><tr><th style="width:33%">Uređaj / licenca</th><th>Uloga</th>'
            '<th class="c" style="width:6%">Kol.</th><th class="r" style="width:12%">Lista</th>'
            '<th class="r" style="width:12%">Cena −45 %</th><th class="r" style="width:13%">Ukupno</th></tr></thead>'
            '<tbody>' + "".join(rows) + '</tbody></table>')


def short_table(title, bom):
    rows = "".join(
        f'<tr><td>{l["name"]}</td><td class="num c">{l["qty"]}</td>'
        f'<td class="num r">{money(l["net"])}</td><td class="num r">{money(l["total"])}</td></tr>'
        for l in lines(bom))
    _, nt = totals(bom)
    return (f'<div class="h4">{title}</div><table class="short"><thead><tr><th>Naziv uređaja</th>'
            '<th class="c" style="width:10%">Količina</th><th class="r" style="width:17%">Cena</th>'
            '<th class="r" style="width:17%">Ukupno</th></tr></thead><tbody>' + rows +
            f'<tr class="tot"><td colspan="3">Ukupno</td><td class="num r">{money(nt)}</td></tr></tbody></table>')


MID_SVG = """<svg viewBox="0 0 640 180" width="100%" role="img" aria-label="Srednji setup: FortiGate 30G, dva FortiSwitch-a i dva FortiAP-a" font-family="Inter, 'DejaVu Sans', sans-serif">
<style>.b{fill:#fff;stroke:#c9d1dc}.f{fill:#0b1f3a}.t{font-size:10px;font-weight:600;fill:#0f172a}.s{font-size:8.4px;fill:#5d6778}.w{font-size:10px;font-weight:600;fill:#fff}.ws{font-size:8.2px;fill:#b9c7dd}.l{stroke:#6b7482;stroke-width:1.3;fill:none}.isl{stroke:#eb6834;stroke-width:2.2}</style>
<rect class="b" x="14" y="22" width="92" height="30" rx="15"/><text class="t" x="60" y="41" text-anchor="middle">Internet</text>
<line class="l" x1="106" y1="37" x2="140" y2="37"/>
<rect class="f" x="140" y="16" width="110" height="44" rx="6"/><text class="w" x="195" y="35" text-anchor="middle">FortiGate 30G</text><text class="ws" x="195" y="49" text-anchor="middle">FortiLink + WLAN kontroler</text>
<rect class="b" x="300" y="16" width="130" height="44" rx="6"/><text class="t" x="365" y="35" text-anchor="middle">FS-108F-FPOE #1</text><text class="s" x="365" y="49" text-anchor="middle">FortiLink uplink</text>
<rect class="b" x="496" y="16" width="130" height="44" rx="6"/><text class="t" x="561" y="35" text-anchor="middle">FS-108F-FPOE #2</text><text class="s" x="561" y="49" text-anchor="middle">ISL ka switchu #1</text>
<line class="l" x1="250" y1="38" x2="300" y2="38"/><text class="s" x="275" y="32" text-anchor="middle">FortiLink</text>
<line class="isl" x1="430" y1="32" x2="496" y2="32"/><line class="isl" x1="430" y1="44" x2="496" y2="44"/><text class="s" x="463" y="27" text-anchor="middle">ISL / LAG 2× 1G</text>
<line class="l" x1="365" y1="60" x2="365" y2="90"/><line class="l" x1="561" y1="60" x2="561" y2="90"/>
<rect class="b" x="310" y="90" width="110" height="38" rx="6"/><text class="t" x="365" y="107" text-anchor="middle">FortiAP 231K</text><text class="s" x="365" y="120" text-anchor="middle">PoE+ sa switcha #1</text>
<rect class="b" x="506" y="90" width="110" height="38" rx="6"/><text class="t" x="561" y="107" text-anchor="middle">FortiAP 231K</text><text class="s" x="561" y="120" text-anchor="middle">PoE+ sa switcha #2</text>
<rect class="b" x="140" y="90" width="130" height="38" rx="6"/><text class="t" x="205" y="107" text-anchor="middle">Klijenti po VLAN-u</text><text class="s" x="205" y="120" text-anchor="middle">korisnici · gosti · IoT</text>
<line class="l" x1="270" y1="109" x2="300" y2="109"/><line class="l" x1="300" y1="109" x2="300" y2="60"/>
<rect x="14" y="140" width="612" height="34" rx="6" fill="#f4f6f9" stroke="#c9d1dc" stroke-dasharray="4 3"/>
<text class="t" x="26" y="154">EVE-NG: besplatni VM-ovi (0 $)</text><text class="s" x="26" y="167">FortiAuthenticator-VM za RADIUS / 802.1X / WPA3-Enterprise · FortiManager i FortiAnalyzer trial (do 3 uređaja) · FortiClient EMS trial</text>
</svg>"""

ENT_SVG = """<svg viewBox="0 0 640 316" width="100%" role="img" aria-label="Enterprise test setup" font-family="Inter, 'DejaVu Sans', sans-serif">
<style>.b{fill:#fff;stroke:#c9d1dc}.f{fill:#0b1f3a}.t{font-size:9.6px;font-weight:600;fill:#0f172a}.s{font-size:8px;fill:#5d6778}.w{font-size:9.6px;font-weight:600;fill:#fff}.ws{font-size:7.8px;fill:#b9c7dd}.l{stroke:#6b7482;stroke-width:1.2;fill:none}.x{stroke:#0b1f3a;stroke-width:2.6}.v{stroke:#2a78d6;stroke-width:1.4;fill:none;stroke-dasharray:5 3}.hb{stroke:#eb6834;stroke-width:1.4}.m{stroke:#8a93a3;stroke-width:1.1;fill:none;stroke-dasharray:1.5 2.5}</style>
<rect class="b" x="220" y="6" width="80" height="22" rx="5"/><text class="t" x="260" y="21" text-anchor="middle">ISP A</text>
<rect class="b" x="340" y="6" width="80" height="22" rx="5"/><text class="t" x="380" y="21" text-anchor="middle">ISP B</text>
<line class="l" x1="250" y1="28" x2="250" y2="48"/><line class="l" x1="270" y1="28" x2="370" y2="48"/><line class="l" x1="370" y1="28" x2="270" y2="48"/><line class="l" x1="390" y1="28" x2="390" y2="48"/>
<rect class="f" x="216" y="48" width="88" height="40" rx="5"/><text class="w" x="260" y="65" text-anchor="middle">FortiGate 120G</text><text class="ws" x="260" y="78" text-anchor="middle">HA primarni</text>
<rect class="f" x="336" y="48" width="88" height="40" rx="5"/><text class="w" x="380" y="65" text-anchor="middle">FortiGate 120G</text><text class="ws" x="380" y="78" text-anchor="middle">HA sekundarni</text>
<line class="hb" x1="304" y1="62" x2="336" y2="62"/><line class="hb" x1="304" y1="74" x2="336" y2="74"/>
<line class="x" x1="242" y1="88" x2="242" y2="124"/><line class="x" x1="278" y1="88" x2="362" y2="124"/><line class="x" x1="362" y1="88" x2="278" y2="124"/><line class="x" x1="398" y1="88" x2="398" y2="124"/>
<text class="s" x="436" y="104">FortiLink: 2× 10G</text><text class="s" x="436" y="114">po FortiGate-u (DAC)</text>
<rect class="b" x="216" y="124" width="88" height="40" rx="5"/><text class="t" x="260" y="141" text-anchor="middle">FS-424E</text><text class="s" x="260" y="154" text-anchor="middle">MCLAG core 1</text>
<rect class="b" x="336" y="124" width="88" height="40" rx="5"/><text class="t" x="380" y="141" text-anchor="middle">FS-424E</text><text class="s" x="380" y="154" text-anchor="middle">MCLAG core 2</text>
<line class="x" x1="304" y1="140" x2="336" y2="140"/><line class="x" x1="304" y1="152" x2="336" y2="152"/><text class="s" x="320" y="133" text-anchor="middle">ICL</text>
<line class="l" x1="236" y1="164" x2="216" y2="200"/><line class="l" x1="284" y1="164" x2="394" y2="200"/><line class="l" x1="356" y1="164" x2="246" y2="200"/><line class="l" x1="404" y1="164" x2="434" y2="200"/>
<rect class="b" x="176" y="200" width="100" height="40" rx="5"/><text class="t" x="226" y="217" text-anchor="middle">FS-108F-FPOE</text><text class="s" x="226" y="230" text-anchor="middle">access, MCLAG trunk</text>
<rect class="b" x="364" y="200" width="100" height="40" rx="5"/><text class="t" x="414" y="217" text-anchor="middle">FS-108F-FPOE</text><text class="s" x="414" y="230" text-anchor="middle">access, MCLAG trunk</text>
<line class="l" x1="206" y1="240" x2="206" y2="270"/><line class="l" x1="256" y1="240" x2="300" y2="270"/><line class="l" x1="422" y1="240" x2="422" y2="270"/>
<rect class="b" x="160" y="270" width="92" height="36" rx="5"/><text class="t" x="206" y="286" text-anchor="middle">FortiAP 231K</text><text class="s" x="206" y="298" text-anchor="middle">Wi-Fi 7</text>
<rect class="b" x="262" y="270" width="92" height="36" rx="5"/><text class="t" x="308" y="286" text-anchor="middle">FortiAP 231K</text><text class="s" x="308" y="298" text-anchor="middle">roaming</text>
<rect class="b" x="376" y="270" width="92" height="36" rx="5"/><text class="t" x="422" y="286" text-anchor="middle">FortiAP 231K</text><text class="s" x="422" y="298" text-anchor="middle">WIDS / mesh</text>
<rect class="f" x="10" y="54" width="118" height="36" rx="5"/><text class="w" x="69" y="70" text-anchor="middle">FortiGate 50G</text><text class="ws" x="69" y="82" text-anchor="middle">filijala 1 (spoke)</text>
<rect class="f" x="10" y="128" width="118" height="36" rx="5"/><text class="w" x="69" y="144" text-anchor="middle">FortiGate 50G</text><text class="ws" x="69" y="156" text-anchor="middle">filijala 2 (spoke)</text>
<path class="v" d="M128 70 L216 64"/><path class="v" d="M128 146 L216 80"/><path class="v" d="M69 90 L69 128"/>
<text class="s" x="10" y="184">SD-WAN / ADVPN 2.0 overlay;</text><text class="s" x="10" y="195">prečica spoke ↔ spoke</text>
<rect x="494" y="124" width="138" height="116" rx="6" fill="#f4f6f9" stroke="#c9d1dc"/>
<text class="t" x="504" y="141">Management VM-ovi</text><text class="s" x="504" y="154">EVE-NG ili hypervisor</text>
<text class="s" x="504" y="172">• FortiManager-VM</text><text class="s" x="504" y="185">• FortiAnalyzer-VM</text><text class="s" x="504" y="198">• FortiAuthenticator-VM</text><text class="s" x="504" y="211">• FortiClient EMS</text><text class="s" x="504" y="228">MGMT VLAN / OOB</text>
<path class="m" d="M424 144 L494 160"/>
</svg>"""

CSS = """
@font-face { font-family: "Inter"; src: url("../../fortigate-breakdown/fonts/Inter-Regular.ttf") format("truetype"); font-weight: 400; }
@font-face { font-family: "Inter"; src: url("../../fortigate-breakdown/fonts/Inter-Italic.ttf") format("truetype"); font-weight: 400; font-style: italic; }
@font-face { font-family: "Inter"; src: url("../../fortigate-breakdown/fonts/Inter-Medium.ttf") format("truetype"); font-weight: 500; }
@font-face { font-family: "Inter"; src: url("../../fortigate-breakdown/fonts/Inter-SemiBold.ttf") format("truetype"); font-weight: 600; }
@font-face { font-family: "Inter"; src: url("../../fortigate-breakdown/fonts/Inter-Bold.ttf") format("truetype"); font-weight: 700; }
@font-face { font-family: "Inter Display"; src: url("../../fortigate-breakdown/fonts/InterDisplay-Bold.ttf") format("truetype"); font-weight: 700; }
@page { size: A4; margin: 14mm 15mm 15mm 15mm;
  @bottom-left { content: "Fortinet test laboratorija · predlog opreme · novembar 2026"; font: 400 7.2pt "Inter", sans-serif; color: #8a93a3; vertical-align: top; padding-top: 4mm; }
  @bottom-right { content: counter(page) " / " counter(pages); font: 600 7.2pt "Inter", sans-serif; color: #8a93a3; vertical-align: top; padding-top: 4mm; } }
:root { --navy:#0b1f3a; --ink:#0f172a; --body:#263042; --muted:#5d6778; --faint:#8a93a3; --line:#e2e6ec; --panel:#f4f6f9; --accent:#2a78d6; --accent-d:#1c5cab; --accent-l:#eaf2fc; --crit:#d03b3b; --warn:#fab219; }
* { box-sizing: border-box; }
html { font-family: "Inter", sans-serif; font-size: 8.7pt; line-height: 1.42; color: var(--body); -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; }
p { margin: 0 0 1.8mm; }
b { color: var(--ink); font-weight: 600; }
.band { background: linear-gradient(135deg, #0b1f3a 0%, #0f2a52 60%, #163a6e 100%); color: #fff; border-radius: 3mm; padding: 6.5mm 8mm 6mm; margin-bottom: 4mm; }
.kicker { font: 600 7.2pt "Inter"; letter-spacing: .16em; text-transform: uppercase; color: #8fb6ea; }
h1 { font: 700 19pt/1.12 "Inter Display", "Inter"; margin: 2mm 0 1.8mm; letter-spacing: -.01em; }
.note { font-size: 7.6pt; color: var(--muted); margin: 2.2mm 0 0; }
.band p { color: #c9d6ea; font-size: 9.6pt; margin: 0; max-width: 150mm; }
.sec { margin-top: 7mm; }
.pb { break-before: page; margin-top: 0 !important; }
.sec-h { display: grid; grid-template-columns: 14mm 1fr; border-bottom: 1px solid var(--line); padding-bottom: 2.6mm; margin-bottom: 3.6mm; break-inside: avoid; break-after: avoid; }
.sec-num { font: 700 22pt/1 "Inter Display", "Inter"; color: var(--accent); }
h2 { font: 700 15pt/1.15 "Inter Display", "Inter"; color: var(--ink); margin: 0 0 1.2mm; }
.lede { color: var(--muted); font-size: 9pt; margin: 0; }
h3 { font: 600 10.4pt "Inter"; color: var(--ink); margin: 4.4mm 0 2mm; break-after: avoid; }
.h4 { font: 700 7.2pt "Inter"; letter-spacing: .1em; text-transform: uppercase; color: var(--accent-d); margin: 0 0 1.8mm; break-after: avoid; }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 5mm; }
.g4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 3mm; }
.mt { margin-top: 3.6mm; }
.tile { border: 1px solid var(--line); border-radius: 2.5mm; padding: 2.8mm 3.2mm; }
.tile .lbl { font-size: 7.4pt; color: var(--muted); }
.tile .val { font: 700 15pt/1.15 "Inter Display", "Inter"; color: var(--ink); margin: 1mm 0 .6mm; }
.tile .sub { font-size: 7.1pt; color: var(--muted); line-height: 1.3; }
.tile.hl { border-color: var(--accent); background: var(--accent-l); }
.callout { border-left: 2.6px solid var(--accent); background: var(--accent-l); padding: 2.6mm 3.6mm; border-radius: 0 2mm 2mm 0; break-inside: avoid; font-size: 8.3pt; }
.callout.warn { border-left-color: var(--warn); background: #fff7e3; }
.callout .ttl { font: 700 7.1pt "Inter"; letter-spacing: .1em; text-transform: uppercase; display: block; margin-bottom: .8mm; color: var(--accent-d); }
.callout.warn .ttl { color: #8a5a00; }
.callout ul { margin: 0; padding-left: 4mm; } .callout li { margin-bottom: .7mm; }
ul.l { margin: 0; padding-left: 4.2mm; } ul.l li { margin-bottom: 1mm; } ul.l li::marker { color: var(--accent); }
ul.x li::marker { color: #b4bac4; }
.figure { border: 1px solid var(--line); border-radius: 2.5mm; padding: 3mm; break-inside: avoid; }
.caption { font-size: 7.3pt; color: var(--muted); margin-top: 1.6mm; }
table { width: 100%; border-collapse: collapse; font-size: 7.9pt; line-height: 1.35; }
th { text-align: left; font-weight: 600; color: var(--ink); background: var(--panel); padding: 1.5mm 2mm; border-bottom: 1px solid #d6dce4; font-size: 7.5pt; }
td { padding: 1.35mm 2mm; border-bottom: 1px solid var(--line); vertical-align: top; }
tr { break-inside: avoid; }
.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
.r { text-align: right; } .c { text-align: center; }
.sku { display: block; font: 400 6.9pt "Inter"; color: var(--faint); margin-top: .3mm; }
tr.tot td { font-weight: 700; color: var(--ink); border-top: 1.4px solid var(--ink); border-bottom: none; background: #fafbfc; }
table.short td { padding: 1.5mm 2mm; font-size: 8.3pt; }
table.short tr.tot td { font-size: 8.8pt; }
.feat td:first-child { width: 47%; }
.legend { display: flex; gap: 5mm; flex-wrap: wrap; font-size: 7.2pt; color: var(--muted); margin-top: 1.8mm; }
.legend span { display: inline-flex; align-items: center; gap: 1.5mm; }
.src { font-size: 7.1pt; color: var(--muted); padding-left: 4mm; margin: 0; } .src li { margin-bottom: .6mm; }
.grand { display: grid; grid-template-columns: repeat(3, 1fr); gap: 3mm; margin-top: 4mm; }
"""


def build_html():
    cheap_lt, cheap_nt = totals(CHEAP)
    mid_lt, mid_nt = totals(MID)
    ent_lt, ent_nt = totals(ENT)
    add_lt, add_nt = totals(MID_ADDON)
    reuse_net = sum(net(s) * q for s, q in REUSED.items())
    ent_after_mid = ent_nt - reuse_net
    fmg_faz_save = net("FC1-10-FMGVS-258-01-12") + net("FC1-10-AZVMS-465-01-12")
    g90_save = (Decimal("7416.00") - Decimal("5117.40")) * (1 - DISCOUNT) * 2
    g90_save = g90_save.quantize(CENT, ROUND_HALF_UP)
    dac_save = net("SP-CABLE-FS-SFP+1") * 6

    return f"""<!DOCTYPE html>
<html lang="sr-Latn"><head><meta charset="utf-8">
<title>Fortinet test laboratorija — srednji i enterprise setup</title>
<style>{CSS}</style></head><body>

<div class="band">
  <div class="kicker">Predlog opreme · cene sa popustom 45 % · novembar 2026</div>
  <h1>Fortinet test laboratorija:<br>srednji i enterprise setup</h1>
  <p>Srednji setup dodaje FortiLink sa dva switcha za najmanje para. Enterprise setup pokriva sve: HA, MCLAG, Wi-Fi 7, SD-WAN, ZTNA, FortiManager i FortiAnalyzer.</p>
</div>

<div class="g4">
  <div class="tile"><div class="lbl">Srednji setup (FortiLink)</div><div class="val">{money(mid_nt)}</div><div class="sub">lista {money(mid_lt)}</div></div>
  <div class="tile"><div class="lbl">Dodatak na jeftini setup</div><div class="val">{money(add_nt)}</div><div class="sub">samo 2 switcha; FortiGate i AP-ovi već postoje</div></div>
  <div class="tile hl"><div class="lbl">Enterprise test (sve)</div><div class="val">{money(ent_nt)}</div><div class="sub">lista {money(ent_lt)}</div></div>
  <div class="tile"><div class="lbl">Enterprise posle srednjeg</div><div class="val">{money(ent_after_mid)}</div><div class="sub">switchevi 108F i 2 AP-a se ponovo koriste</div></div>
</div>
<p class="note">Cene u USD: lista (MSRP) umanjena za vaš popust od 45 %, bez PDV-a i transporta. Kako su računate i odakle su, piše na strani 3.</p>

<section class="sec">
  <header class="sec-h"><div class="sec-num">01</div><div>
    <h2>Srednji setup: FortiLink za najmanje para</h2>
    <p class="lede">Jeftinom setupu dodajemo dva najjeftinija PoE FortiSwitch-a. FortiGate 30G ih upravlja preko FortiLink-a (do 8 switcheva i 16 AP-ova).</p>
  </div></header>
  <div class="figure">{MID_SVG}</div>
  <div class="g2 mt">
    <div>
      <div class="h4">Šta testiramo</div>
      <ul class="l">
        <li><b>FortiLink:</b> otkrivanje i autorizacija switcheva, upgrade firmvera switcheva i AP-ova sa FortiGate-a.</li>
        <li><b>Između switcheva:</b> ISL, LAG trunk sa 2 linka, VLAN-ovi preko oba switcha, STP i zaštita od petlji.</li>
        <li><b>Port:</b> NAC (VLAN po tipu uređaja), karantin hosta, DHCP snooping, PoE.</li>
        <li><b>802.1X i WPA3-Enterprise</b> uz FortiAuthenticator-VM u EVE-NG (5 korisnika besplatno).</li>
      </ul>
    </div>
    <div>
      <div class="h4">Šta ovde ne ide</div>
      <ul class="l x">
        <li><b>MCLAG:</b> serija 1xx ga ne podržava, treba 2xx/4xx (ima ga enterprise setup).</li>
        <li><b>HA i SD-WAN između lokacija:</b> postoji samo jedan FortiGate.</li>
        <li><b>FortiManager / FortiAnalyzer:</b> samo kao trial u EVE-NG (do 3 uređaja, bez FortiGuard servisa).</li>
      </ul>
    </div>
  </div>
  <h3>Oprema i cene: srednji setup</h3>
  {bom_table(MID)}
</section>

<section class="sec pb">
  <header class="sec-h"><div class="sec-num">02</div><div>
    <h2>Enterprise test: pokriva sve funkcije</h2>
    <p class="lede">Kompletna HQ laboratorija sa dve filijale, po istoj arhitekturi kao u dokumentu o FortiGate dizajnu: HA par, FortiLink preko MCLAG-a, Wi-Fi 7, SD-WAN/ADVPN, ZTNA i centralno upravljanje i logovanje.</p>
  </div></header>
  <div class="figure">{ENT_SVG}
    <div class="legend">
      <span><svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke="#0b1f3a" stroke-width="2.6"/></svg>10G DAC</span>
      <span><svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke="#6b7482" stroke-width="1.3"/></svg>1G bakar</span>
      <span><svg width="22" height="8"><line x1="0" y1="2" x2="22" y2="2" stroke="#eb6834" stroke-width="1.5"/><line x1="0" y1="6" x2="22" y2="6" stroke="#eb6834" stroke-width="1.5"/></svg>HA heartbeat</span>
      <span><svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke="#2a78d6" stroke-width="1.5" stroke-dasharray="5 3"/></svg>SD-WAN overlay</span>
    </div>
  </div>
  <h3>Koje funkcije pokriva i na čemu</h3>
  <table class="feat">
    <thead><tr><th>Funkcija</th><th>Na čemu se testira</th></tr></thead>
    <tbody>
      <tr><td>HA (FGCP active-passive), session pickup, upgrade bez prekida</td><td>2× FortiGate 120G</td></tr>
      <tr><td>NGFW: IPS, Application Control, antimalver, web/DNS filter, SSL deep inspection</td><td>Enterprise Protection paket na 120G</td></tr>
      <tr><td>Inline CASB, DLP, inline sandbox</td><td>Enterprise Protection paket na 120G</td></tr>
      <tr><td>FortiLink preko MCLAG-a, multi-tier, zaštita od split-brain-a</td><td>2× FS-424E (core, ICL 2× 10G) + 2× FS-108F-FPOE</td></tr>
      <tr><td>NAC, 802.1X, dinamički VLAN, PoE</td><td>FortiSwitch + FortiAuthenticator-VM</td></tr>
      <tr><td>Wi-Fi 7: roaming (802.11r/k/v), WPA3-Enterprise, WIDS, gost portal</td><td>3× FortiAP 231K</td></tr>
      <tr><td>SD-WAN, ADVPN 2.0, BGP na loopback-u, failover linkova</td><td>HA par kao hub + 2× FortiGate 50G</td></tr>
      <tr><td>ZTNA i provera stanja uređaja</td><td>FortiClient EMS (trial, 3 uređaja)</td></tr>
      <tr><td>MFA, SAML, RADIUS</td><td>FortiAuthenticator-VM + 2 besplatna FortiToken Mobile uz FortiGate</td></tr>
      <tr><td>Centralno upravljanje, firmware šabloni, revizije</td><td>FortiManager-VM (10 uređaja; HA par se broji kao 1)</td></tr>
      <tr><td>Logovi, izveštaji, IOC, automatizacija</td><td>FortiAnalyzer-VM (5 GB/dan)</td></tr>
      <tr><td>VDOM segmentacija</td><td>FortiGate 120G (10 VDOM-ova)</td></tr>
    </tbody>
  </table>
</section>

<section class="sec pb">
  <h3 style="margin-top:0">Oprema i cene: enterprise setup</h3>
  {bom_table(ENT)}
  <div class="g2 mt">
    <div class="callout">
      <span class="ttl">Gde može jeftinije</span>
      <ul>
        <li>FortiManager i FortiAnalyzer kao besplatni trial: −{money(fmg_faz_save)} (FMG do 3 uređaja, bez FortiGuard servisa).</li>
        <li>2× FortiGate 90G umesto 120G: −{money(g90_save)} (manje portova i performansi, iste funkcije).</li>
        <li>Bez DAC kablova, sve na 1G bakru: −{money(dac_save)}.</li>
      </ul>
    </div>
    <div class="callout warn">
      <span class="ttl">Nije uračunato</span>
      <ul>
        <li>Server ili EVE-NG host za VM-ove: računajte najmanje ~48 GB RAM (FMG i FAZ po 16 GB).</li>
        <li>Dva ISP linka za SD-WAN test, rek, patch kablovi, mali switch za WAN stranu HA para.</li>
        <li>FortiCare za switcheve i AP-ove (za test nije neophodan) i obnova licenci posle 1. godine.</li>
      </ul>
    </div>
  </div>
  <h3>Kako su računate cene</h3>
  <ul class="l">
    <li>Lista = MSRP iz javnih cenovnika ovlašćenih distributera (SHI, CDW, AVFirewalls, Ingram Micro), novembar 2026. Cena = lista × 0,55 (vaš popust od 45 %), zaokruženo po komadu.</li>
    <li>Iznosi su u USD, bez PDV-a, transporta i dodatnih carinskih troškova. Licence (UTP, Enterprise Protection, FortiManager, FortiAnalyzer) važe 1 godinu.</li>
    <li>Jeftini setup iz ranijeg razgovora računam kao FortiGate 30G + 2× FortiAP 231K + 2 PoE injektora (30G nema PoE portove). Ako ste uzeli druge modele, menjaju se samo ti redovi.</li>
  </ul>
  <div class="h4 mt">Izvori cena</div>
  <ol class="src">
    <li>FortiGate 30G, 50G (UTP), FortiSwitch 108F-FPOE, FortiAP 231K, FortiManager-VM: MSRP na shi.com.</li>
    <li>FortiGate 120G (Enterprise Protection): MSRP 7.416 $ na cdw.com i shi.com (raspon na tržištu 5.550–8.158 $).</li>
    <li>FortiSwitch 424E: lista 1.637 $ (shi.com, avfirewalls.com). FortiAnalyzer-VM: lista 1.265 $ (avfirewalls.com, cdwg.com).</li>
    <li>DAC kabl SP-CABLE-FS-SFP+1: 104 $ (Ingram Micro). FortiAuthenticator-VM i FortiClient EMS: besplatni režimi bez isteka (Fortinet dokumentacija).</li>
    <li>Cenovnici US distributera se međusobno razlikuju i do ~30 %, a EMEA lista vašeg distributera može biti drugačija. Za narudžbinu tražite zvaničnu ponudu.</li>
  </ol>
</section>

<section class="sec pb">
  <header class="sec-h"><div class="sec-num">03</div><div>
    <h2>Skraćeni popis</h2>
    <p class="lede">Sva tri setupa: naziv uređaja, količina, cena po komadu sa popustom od 45 % i ukupno.</p>
  </div></header>
  {short_table("Jeftini setup (FortiGate + 2 AP)", CHEAP)}
  <div class="mt"></div>
  {short_table("Srednji setup (FortiLink)", MID)}
  <div class="mt"></div>
  {short_table("Enterprise test setup", ENT)}
  <div class="grand">
    <div class="tile"><div class="lbl">Jeftini setup</div><div class="val">{money(cheap_nt)}</div><div class="sub">lista {money(cheap_lt)}</div></div>
    <div class="tile"><div class="lbl">Srednji setup</div><div class="val">{money(mid_nt)}</div><div class="sub">lista {money(mid_lt)}</div></div>
    <div class="tile hl"><div class="lbl">Enterprise setup</div><div class="val">{money(ent_nt)}</div><div class="sub">lista {money(ent_lt)}</div></div>
  </div>
  <p class="note">Ako idete redom, svaki korak koristi opremu iz prethodnog: jeftini {money(cheap_nt)} → srednji +{money(add_nt)} → enterprise +{money(ent_after_mid)} = ukupno {money(cheap_nt + add_nt + ent_after_mid)} (PoE injektori iz jeftinog setupa tada ostaju rezerva).</p>
</section>
</body></html>"""


if __name__ == "__main__":
    DIST.mkdir(exist_ok=True)
    HTML.write_text(build_html(), encoding="utf-8")
    subprocess.run(["node", str(ROOT / "build" / "render.js"), str(HTML), str(PDF)], check=True)
    for name, bom in (("srednji", MID), ("enterprise", ENT)):
        lt, nt = totals(bom)
        print(f"{name}: lista {money(lt)} | neto {money(nt)}")
    print("written", PDF)
