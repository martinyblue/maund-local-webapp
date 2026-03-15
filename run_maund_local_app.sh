#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 가 필요합니다. macOS에 Python 3를 설치한 뒤 다시 실행하세요."
  exit 1
fi

if command -v lsof >/dev/null 2>&1; then
  EXISTING_PIDS="$(lsof -ti tcp:8501 2>/dev/null || true)"
  if [[ -n "$EXISTING_PIDS" ]]; then
    echo "기존 MAUND 로컬 앱을 종료하고 최신 버전으로 다시 시작합니다."
    kill $EXISTING_PIDS 2>/dev/null || true
    sleep 1
  fi
fi

export MAUND_OPEN_BROWSER="${MAUND_OPEN_BROWSER:-1}"
exec python3 maund_local_webapp_launcher.py
