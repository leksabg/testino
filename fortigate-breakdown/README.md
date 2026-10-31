# Fortinet FortiGate u enterprise okruženju — pregled (oktobar 2026)

Gotov PDF: [`dist/Fortinet-FortiGate-enterprise-pregled-2026.pdf`](dist/Fortinet-FortiGate-enterprise-pregled-2026.pdf) (10 strana, A4).

Sadržaj: Fortinet ukratko, fizički dizajn (HA, topologija, dimenzionisanje), logički dizajn
(zone, politike, management ravan, udaljeni pristup, SD-WAN), NGFW tehnologije, koliko je
FortiGate često meta (CISA KEV, incidenti 2021–2026), proces patchovanja i kontrolna lista.

## Ponovno generisanje

```bash
python3 build/build.py
```

- `src/index.html` — sadržaj i stil dokumenta; `src/diagram_topology.svg` — dijagram topologije
- `build/charts.py` — grafikoni iz CISA KEV kataloga (verzija 2026.10.30; brojke su upisane u skriptu)
- `build/render.js` — HTML → PDF preko Playwright Chromium-a
- `fonts/` — Inter (SIL Open Font License 1.1)
