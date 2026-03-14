#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "[MAUND] Creating local virtual environment..."
  python3 -m venv .venv
fi

if [[ ! -x ".venv/bin/pyinstaller" ]]; then
  echo "[MAUND] Installing required packages..."
  .venv/bin/pip install -r requirements.txt
fi

.venv/bin/python -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name maund-local-webapp \
  --add-data "maund_local_app:maund_local_app" \
  maund_local_webapp_launcher.py
