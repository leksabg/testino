"""Generate the SVG charts used in the FortiGate breakdown PDF.

Data source: CISA Known Exploited Vulnerabilities catalog, version 2026.10.30
(github.com/cisagov/kev-data). Counts were computed from the catalog JSON and
are hard-coded here so the build is reproducible offline.
"""
import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "src"

# Palette (dataviz reference palette, validated: light mode, white surface)
SERIES_1 = "#2a78d6"   # FortiOS / FortiGate
SERIES_2 = "#eb6834"   # other Fortinet products
DEEMPH = "#cdd3dc"     # de-emphasised bars
SURFACE = "#ffffff"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e6e8ec"
BASE = "#c3c2b7"
FONT = "Inter, 'DejaVu Sans', sans-serif"

YEARS = ["2021", "2022", "2023", "2024", "2025", "2026*"]
FORTIOS = [4, 5, 2, 2, 4, 4]
OTHER = [0, 0, 0, 2, 4, 5]

VENDORS = [
    ("Cisco", 102), ("Ivanti", 38), ("Fortinet", 32), ("Citrix", 27),
    ("SonicWall", 19), ("Palo Alto", 16), ("Zyxel", 13), ("F5", 8),
    ("Juniper", 8), ("Sophos", 7), ("Check Point", 5), ("WatchGuard", 4),
]


def top_rounded(x, y, w, h, r=4):
    r = min(r, h, w / 2)
    return (f"M{x:.1f},{y + h:.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
            f"L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
            f"L{x + w:.1f},{y + h:.1f} Z")


def right_rounded(x, y, w, h, r=4):
    r = min(r, w, h / 2)
    return (f"M{x:.1f},{y:.1f} L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
            f"L{x + w:.1f},{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} "
            f"L{x:.1f},{y + h:.1f} Z")


def years_chart():
    W, H = 330, 214
    left, right, top, bottom = 24, 6, 40, 24
    pw, ph = W - left - right, H - top - bottom
    ymax = 10
    sy = lambda v: top + ph - v / ymax * ph
    band = pw / len(YEARS)
    bw = 22
    gap = 2
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" '
         f'role="img" aria-label="Fortinet KEV unosi po godini" font-family="{FONT}">']
    # legend
    o.append(f'<rect x="{left}" y="6" width="10" height="10" rx="2" fill="{SERIES_1}"/>')
    o.append(f'<text x="{left + 15}" y="15" font-size="10" fill="{INK_2}">FortiOS / FortiGate</text>')
    o.append(f'<rect x="{left + 128}" y="6" width="10" height="10" rx="2" fill="{SERIES_2}"/>')
    o.append(f'<text x="{left + 143}" y="15" font-size="10" fill="{INK_2}">Ostali Fortinet proizvodi</text>')
    # grid + y ticks
    for v in range(0, ymax + 1, 2):
        y = sy(v)
        color = BASE if v == 0 else GRID
        o.append(f'<line x1="{left}" y1="{y:.1f}" x2="{W - right}" y2="{y:.1f}" stroke="{color}" stroke-width="1"/>')
        o.append(f'<text x="{left - 6}" y="{y + 3.5:.1f}" font-size="9" fill="{MUTED}" text-anchor="end" '
                 f'style="font-variant-numeric: tabular-nums">{v}</text>')
    for i, yr in enumerate(YEARS):
        cx = left + band * i + band / 2
        x = cx - bw / 2
        f, ot = FORTIOS[i], OTHER[i]
        total = f + ot
        # bottom segment (FortiOS)
        y_f = sy(f)
        h_f = sy(0) - y_f
        if ot == 0:
            o.append(f'<path d="{top_rounded(x, y_f, bw, h_f)}" fill="{SERIES_1}"/>')
        else:
            o.append(f'<rect x="{x:.1f}" y="{y_f:.1f}" width="{bw}" height="{h_f:.1f}" fill="{SERIES_1}"/>')
            y_t = sy(total)
            h_o = (y_f - gap) - y_t
            o.append(f'<path d="{top_rounded(x, y_t, bw, h_o)}" fill="{SERIES_2}"/>')
        # total on cap
        o.append(f'<text x="{cx:.1f}" y="{sy(total) - 5:.1f}" font-size="10.5" font-weight="600" '
                 f'fill="{INK}" text-anchor="middle">{total}</text>')
        o.append(f'<text x="{cx:.1f}" y="{H - 8}" font-size="9.5" fill="{INK_2}" text-anchor="middle">{yr}</text>')
    o.append("</svg>")
    return "\n".join(o)


def vendors_chart():
    W, H = 330, 222
    label_w, right, top, bottom = 74, 30, 4, 20
    x0 = label_w + 4
    pw = W - x0 - right
    xmax = 110
    sx = lambda v: x0 + v / xmax * pw
    step = 15.6
    bh = 10
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" '
         f'role="img" aria-label="KEV unosi po proizvodjacu" font-family="{FONT}">']
    plot_bottom = top + step * len(VENDORS) + 2
    for v in (0, 25, 50, 75, 100):
        x = sx(v)
        color = BASE if v == 0 else GRID
        o.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{plot_bottom:.1f}" stroke="{color}" stroke-width="1"/>')
        o.append(f'<text x="{x:.1f}" y="{plot_bottom + 12:.1f}" font-size="9" fill="{MUTED}" text-anchor="middle" '
                 f'style="font-variant-numeric: tabular-nums">{v}</text>')
    for i, (name, val) in enumerate(VENDORS):
        y = top + step * i + (step - bh) / 2
        hl = name == "Fortinet"
        fill = SERIES_1 if hl else DEEMPH
        weight = "600" if hl else "400"
        ink = INK if hl else INK_2
        o.append(f'<text x="{label_w}" y="{y + bh - 1.5:.1f}" font-size="9.5" font-weight="{weight}" '
                 f'fill="{ink}" text-anchor="end">{name}</text>')
        o.append(f'<path d="{right_rounded(sx(0), y, sx(val) - sx(0), bh)}" fill="{fill}"/>')
        o.append(f'<text x="{sx(val) + 4:.1f}" y="{y + bh - 1.5:.1f}" font-size="9.5" font-weight="{weight}" '
                 f'fill="{ink}" style="font-variant-numeric: tabular-nums">{val}</text>')
    o.append("</svg>")
    return "\n".join(o)


if __name__ == "__main__":
    (OUT / "chart_kev_years.svg").write_text(years_chart(), encoding="utf-8")
    (OUT / "chart_kev_vendors.svg").write_text(vendors_chart(), encoding="utf-8")
    print("charts written to", OUT)
