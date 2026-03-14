#!/usr/bin/env bash
set -euo pipefail

pkill -f "maund_local_webapp_launcher.py" || true
pkill -f "python3 maund_local_webapp_launcher.py" || true
