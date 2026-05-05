from __future__ import annotations

from pathlib import Path


def safe_delete(path: str | Path) -> None:
    Path(path).unlink(missing_ok=True)


def existing_file(path: str | Path) -> Path | None:
    candidate = Path(path)
    return candidate if candidate.is_file() else None
