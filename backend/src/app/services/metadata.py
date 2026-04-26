from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mutagen.mp4 import MP4


@dataclass
class ExtractedMetadata:
    title: str | None
    album: str | None
    artist: str | None
    genre: str | None
    duration_seconds: int | None
    track_number: int | None
    year: int | None
    raw: dict[str, Any] | None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def _first_text(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str):
        return value
    return None


def _track_number(raw: dict[str, Any]) -> int | None:
    value = raw.get("trkn")
    if not isinstance(value, list) or not value:
        return None
    first = value[0]
    if isinstance(first, (tuple, list)) and first:
        track = first[0]
        if isinstance(track, int):
            return track
    return None


def _year_from_date(raw: dict[str, Any]) -> int | None:
    text = _first_text(raw, "\xa9day")
    if not text:
        return None
    prefix = text[:4]
    return int(prefix) if prefix.isdigit() else None


def extract_m4b_metadata(file_path: str | Path) -> ExtractedMetadata:
    audio = MP4(str(file_path))
    raw = _json_safe(dict(audio.tags or {}))

    duration_seconds: int | None = None
    if audio.info and getattr(audio.info, "length", None) is not None:
        duration_seconds = int(round(float(audio.info.length)))

    return ExtractedMetadata(
        title=_first_text(raw, "\xa9nam"),
        album=_first_text(raw, "\xa9alb"),
        artist=_first_text(raw, "\xa9ART"),
        genre=_first_text(raw, "\xa9gen"),
        duration_seconds=duration_seconds,
        track_number=_track_number(raw),
        year=_year_from_date(raw),
        raw=raw or None,
    )
