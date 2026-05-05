from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Audiobook, ProcessingJob
from app.services.queue import next_queue_position

CHUNK_SIZE = 1024 * 1024
CHECKSUM_COLUMN = "checksum_sha256"
CHECKSUM_CONSTRAINT = "audiobooks_checksum_sha256_key"
UNIQUE_VIOLATION_SQLSTATE = "23505"


@dataclass
class UploadResult:
    audiobook_id: uuid.UUID
    original_filename: str
    stored_path: str
    file_size_bytes: int
    checksum_sha256: str
    job_id: uuid.UUID
    job_state: str
    queue_position: int | None = None


def _validate_m4b_filename(filename: str | None) -> str:
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must have a filename.",
        )

    if not filename.lower().endswith(".m4b"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only .m4b files are accepted.",
        )

    return Path(filename).name


def _stream_to_temp(file: UploadFile, storage_root: Path) -> tuple[Path, int, str]:
    digest = hashlib.sha256()
    total_bytes = 0
    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(prefix="upload-", suffix=".tmp", dir=storage_root, delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            while True:
                chunk = file.file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                digest.update(chunk)
                temp_file.write(chunk)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise

    return temp_path, total_bytes, digest.hexdigest()


def _is_checksum_unique_violation(exc: IntegrityError) -> bool:
    orig = exc.orig
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    if constraint_name == CHECKSUM_CONSTRAINT:
        return True

    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate == UNIQUE_VIOLATION_SQLSTATE:
        detail = getattr(diag, "message_detail", None) or str(orig)
        if CHECKSUM_COLUMN in detail:
            return True

    # SQLite and generic DBAPI fallback where driver-specific fields are not present.
    detail_text = str(orig)
    if CHECKSUM_COLUMN in detail_text and "UNIQUE constraint failed" in detail_text:
        return True

    return False


def handle_upload(db: Session, file: UploadFile) -> UploadResult:
    original_filename = _validate_m4b_filename(file.filename)

    storage_root = Path(settings.audio_storage_root)
    storage_root.mkdir(parents=True, exist_ok=True)

    temp_path: Path | None = None
    final_path: Path | None = None

    try:
        temp_path, total_bytes, checksum = _stream_to_temp(file, storage_root)
        final_name = f"{uuid.uuid4()}.m4b"
        final_path = storage_root / final_name
        os.replace(temp_path, final_path)

        audiobook = Audiobook(
            original_filename=original_filename,
            stored_path=str(final_path),
            file_size_bytes=total_bytes,
            checksum_sha256=checksum,
        )
        db.add(audiobook)
        db.flush()

        job = ProcessingJob(audiobook_id=audiobook.id, state="received")
        db.add(job)
        db.flush()

        job.state = "queued"
        job.queue_position = next_queue_position(db)
        db.commit()
        db.refresh(audiobook)
        db.refresh(job)

        return UploadResult(
            audiobook_id=audiobook.id,
            original_filename=audiobook.original_filename,
            stored_path=audiobook.stored_path,
            file_size_bytes=audiobook.file_size_bytes,
            checksum_sha256=audiobook.checksum_sha256,
            job_id=job.id,
            job_state=job.state,
            queue_position=job.queue_position,
        )
    except IntegrityError as exc:
        db.rollback()
        if final_path and final_path.exists():
            final_path.unlink(missing_ok=True)

        if _is_checksum_unique_violation(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Duplicate upload detected for this audiobook checksum.",
            ) from exc

        raise
    except HTTPException:
        db.rollback()
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        if final_path and final_path.exists():
            final_path.unlink(missing_ok=True)
        raise
    except Exception:
        db.rollback()
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        if final_path and final_path.exists():
            final_path.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()
