# Fortinet test laboratorija — srednji i enterprise setup (novembar 2026)

Gotov PDF: [`dist/Fortinet-test-lab-srednji-i-enterprise-2026.pdf`](dist/Fortinet-test-lab-srednji-i-enterprise-2026.pdf) (4 strane, A4).

- Srednji setup: FortiGate 30G + 2× FortiSwitch 108F-FPOE + 2× FortiAP 231K (FortiLink, ISL/LAG između switcheva).
- Enterprise setup: 2× FortiGate 120G (HA), 2× FortiGate 50G (filijale), 2× FortiSwitch 424E (MCLAG), 2× 108F-FPOE, 3× FortiAP 231K, FortiManager-VM, FortiAnalyzer-VM.
- Cene: lista (MSRP, USD, novembar 2026) umanjena za 45 %, bez PDV-a i transporta.

## Ponovno generisanje

```bash
python3 build/build.py
```

Sve stavke, količine i cene su u `ITEMS`, `MID` i `ENT` u `build/build.py`; promena cene ili popusta (`DISCOUNT`) automatski menja sve tabele i zbirove. Fontovi se uzimaju iz `../fortigate-breakdown/fonts/`.
