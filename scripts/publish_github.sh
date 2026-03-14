#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OWNER="${1:-martinyblue}"
REPO="${2:-maund-local-webapp}"
VISIBILITY="${VISIBILITY:-public}"
REMOTE_URL="https://github.com/${OWNER}/${REPO}.git"
VERSION_FILE="$ROOT_DIR/VERSION"

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

if [[ ! -f "$VERSION_FILE" ]]; then
  echo "VERSION 파일이 없습니다."
  exit 1
fi

VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
TAG="v${VERSION}"

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

if ! gh repo view "${OWNER}/${REPO}" >/dev/null 2>&1; then
  gh repo create "${OWNER}/${REPO}" "--${VISIBILITY}"
fi

if ! git rev-parse "$TAG" >/dev/null 2>&1; then
  git tag -a "$TAG" -m "Release $TAG"
fi

git push -u origin main
git push origin "$TAG"

if ! gh release view "$TAG" --repo "${OWNER}/${REPO}" >/dev/null 2>&1; then
  NOTES_FILE="$(mktemp)"
  python3 - "$VERSION" "$NOTES_FILE" <<'PY'
from pathlib import Path
import re
import sys

version = sys.argv[1]
notes_file = Path(sys.argv[2])
changelog = Path("CHANGELOG.md")
text = changelog.read_text(encoding="utf-8") if changelog.exists() else ""
pattern = re.compile(rf"^## \[{re.escape(version)}\].*$", re.MULTILINE)
match = pattern.search(text)
notes = f"Release v{version}"
if match:
    start = match.end()
    next_match = re.search(r"^## \[", text[start:], re.MULTILINE)
    body = text[start : start + next_match.start()] if next_match else text[start:]
    body = body.strip()
    if body:
        notes = body
notes_file.write_text(notes + "\n", encoding="utf-8")
PY
  gh release create "$TAG" --repo "${OWNER}/${REPO}" --title "$TAG" --notes-file "$NOTES_FILE"
  rm -f "$NOTES_FILE"
fi

echo "GitHub 푸시와 버전 태그 배포가 완료되었습니다: ${REMOTE_URL}"
