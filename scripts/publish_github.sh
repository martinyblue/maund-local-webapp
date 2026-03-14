#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OWNER="${1:-martinyblue}"
REPO="${2:-maund-local-webapp}"
VISIBILITY="${VISIBILITY:-public}"
REMOTE_URL="https://github.com/${OWNER}/${REPO}.git"

cd "$ROOT_DIR"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI (gh) 가 필요합니다."
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "먼저 GitHub 로그인부터 하세요:"
  echo "  gh auth login --hostname github.com --git-protocol https --web"
  exit 1
fi

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

if gh repo view "${OWNER}/${REPO}" >/dev/null 2>&1; then
  git push -u origin main
  echo "기존 저장소에 최신 커밋을 푸시했습니다: ${REMOTE_URL}"
  exit 0
fi

gh repo create "${OWNER}/${REPO}" "--${VISIBILITY}" --source=. --remote=origin --push
echo "새 저장소를 만들고 푸시했습니다: ${REMOTE_URL}"
