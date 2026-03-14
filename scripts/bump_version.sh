#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NEW_VERSION="${1:-}"

if [[ -z "$NEW_VERSION" ]]; then
  echo "사용법: ./scripts/bump_version.sh 0.1.1"
  exit 1
fi

if [[ ! "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "버전 형식은 x.y.z 여야 합니다. 예: 0.1.1"
  exit 1
fi

cd "$ROOT_DIR"

printf '%s\n' "$NEW_VERSION" > VERSION

TODAY="$(date +%F)"
TMP_FILE="$(mktemp)"
{
  echo "# Changelog"
  echo
  echo "이 문서는 GitHub 버전 배포용 변경 이력을 기록합니다."
  echo
  echo "## [$NEW_VERSION] - $TODAY"
  echo
  echo "- 변경 내용을 여기에 적으세요"
  echo
  if [[ -f CHANGELOG.md ]]; then
    tail -n +5 CHANGELOG.md
  fi
} > "$TMP_FILE"
mv "$TMP_FILE" CHANGELOG.md

echo "VERSION 을 $NEW_VERSION 으로 올렸습니다."
echo "CHANGELOG.md 의 새 섹션을 수정한 뒤 커밋하세요."
