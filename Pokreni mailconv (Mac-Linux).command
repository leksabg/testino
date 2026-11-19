#!/bin/bash
# Mac: dupli klik. Linux: ./"Pokreni mailconv (Mac-Linux).command"
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "Prvo pokretanje: instaliram potrebne pakete..."
  python3 -m venv .venv || { echo "Instaliraj Python 3 sa python.org"; read -r; exit 1; }
  .venv/bin/pip install -q --upgrade -r requirements.txt || { read -r; exit 1; }
  .venv/bin/pip install -q libpff-python || echo "Napomena: PST podrska nije instalirana - ostali formati rade."
fi
.venv/bin/python mailconv_gui.pyw
