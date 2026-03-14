from __future__ import annotations

from pathlib import Path


def _version_file() -> Path:
    return Path(__file__).resolve().parent.parent / "VERSION"


def get_version() -> str:
    path = _version_file()
    if not path.exists():
        return "0.0.0"
    return path.read_text(encoding="utf-8").strip() or "0.0.0"


__version__ = get_version()
