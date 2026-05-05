from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from mutagen.mp4 import MP4, MP4Cover
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Audiobook

ALLOWED_COVER_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}
CHUNK_SIZE = 1024 * 1024


def _cover_storage_dir() -> Path:
    path = Path(settings.audio_storage_root) / "covers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _delete_cover_file(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to delete cover file") from exc


def replace_manual_cover(db: Session, audiobook: Audiobook, file: UploadFile) -> Audiobook:
    media_type = file.content_type
    extension = ALLOWED_COVER_TYPES.get(media_type or "")
    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PNG, JPEG, and WebP cover images are accepted.",
        )

    cover_dir = _cover_storage_dir()
    final_path = cover_dir / f"{audiobook.id}.{extension}"
    temp_path = cover_dir / f".{audiobook.id}.{extension}.tmp"

    try:
        with temp_path.open("wb") as output:
            while True:
                chunk = file.file.read(CHUNK_SIZE)
                if not chunk:
                    break
                output.write(chunk)

        old_path = audiobook.cover_path
        if old_path and Path(old_path) != final_path:
            _delete_cover_file(old_path)
        os.replace(temp_path, final_path)

        audiobook.cover_path = str(final_path)
        audiobook.cover_media_type = media_type
        db.commit()
        db.refresh(audiobook)
        return audiobook
    except HTTPException:
        db.rollback()
        temp_path.unlink(missing_ok=True)
        raise
    except Exception:
        db.rollback()
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()


def delete_manual_cover(db: Session, audiobook: Audiobook) -> None:
    _delete_cover_file(audiobook.cover_path)
    audiobook.cover_path = None
    audiobook.cover_media_type = None
    db.commit()


def extract_embedded_mp4_cover(audiobook: Audiobook) -> tuple[bytes, str] | None:
    path = Path(audiobook.stored_path)
    if not path.is_file():
        return None

    try:
        tags = MP4(path).tags or {}
    except Exception:
        return None

    covers = tags.get("covr") or []
    if not covers:
        return None

    cover = covers[0]
    media_type = "image/jpeg"
    imageformat = getattr(cover, "imageformat", None)
    if imageformat == MP4Cover.FORMAT_PNG:
        media_type = "image/png"

    return bytes(cover), media_type
