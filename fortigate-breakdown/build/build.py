"""Build the FortiGate breakdown PDF.

1. regenerate SVG charts, 2. inline SVG includes into dist/index.html,
3. render with Chromium, 4. fill the cover TOC with real page numbers and
render again.  usage: python3 build/build.py
"""
import pathlib
import re
import subprocess
import sys

from pypdf import PdfReader, PdfWriter

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC, DIST, BUILD = ROOT / "src", ROOT / "dist", ROOT / "build"
PDF = DIST / "Fortinet-FortiGate-enterprise-pregled-2026.pdf"
HTML = DIST / "index.html"


def assemble(toc=None):
    html = (SRC / "index.html").read_text(encoding="utf-8")
    html = re.sub(r"<!--INCLUDE:([\w.-]+)-->",
                  lambda m: (SRC / m.group(1)).read_text(encoding="utf-8"), html)
    for sec, page in (toc or {}).items():
        html = html.replace(f'<span class="pg" data-toc="{sec}"></span>',
                            f'<span class="pg" data-toc="{sec}">str. {page}</span>')
    HTML.write_text(html, encoding="utf-8")


def render():
    subprocess.run(["node", str(BUILD / "render.js"), str(HTML), str(PDF)], check=True)


def section_pages():
    reader = PdfReader(str(PDF))
    found = {}
    for no, page in enumerate(reader.pages, start=1):
        # letter-spaced kickers extract as "s e k c i j a", so compare without whitespace
        text = re.sub(r"\s+", "", (page.extract_text() or "").lower())
        for i in range(1, 8):
            if f"sekcija0{i}" in text and f"s{i}" not in found:
                found[f"s{i}"] = no
    return found, len(reader.pages)


def set_metadata():
    reader = PdfReader(str(PDF))
    writer = PdfWriter(clone_from=reader)
    writer.add_metadata({
        "/Title": "Fortinet FortiGate u enterprise okruženju — pregled (oktobar 2026)",
        "/Subject": "Fizički i logički dizajn, NGFW tehnologije, izloženost napadima i patch proces",
        "/Keywords": "Fortinet, FortiGate, FortiOS, NGFW, HA, PSIRT, CISA KEV, patch management",
    })
    with open(PDF, "wb") as fh:
        writer.write(fh)


if __name__ == "__main__":
    subprocess.run([sys.executable, str(BUILD / "charts.py")], check=True)
    DIST.mkdir(exist_ok=True)
    assemble()
    render()
    toc, pages = section_pages()
    print("sections:", toc, "pages:", pages)
    assemble(toc)
    render()
    set_metadata()
    print("written", PDF)
