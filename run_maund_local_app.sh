#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 가 필요합니다. macOS에 Python 3를 설치한 뒤 다시 실행하세요."
  exit 1
fi

export MAUND_OPEN_BROWSER="${MAUND_OPEN_BROWSER:-1}"
exec python3 maund_local_webapp_launcher.py
