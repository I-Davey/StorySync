from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Audiobook, ProcessingJob
from app.schemas import UpdateAudiobookRequest
from app.services import jobs as job_service
from app.services.storage import existing_file, safe_delete


class AudiobookFileMissingError(FileNotFoundError):
    """Raised when an audiobook DB row points to a missing stored file."""


class ProcessingJobMissingError(LookupError):
    """Raised when an audiobook has no processing job."""


def get_audiobook(db: Session, audiobook_id: uuid.UUID) -> Audiobook | None:
    return db.get(Audiobook, audiobook_id)


def get_job_for_audiobook(db: Session, audiobook_id: uuid.UUID) -> ProcessingJob | None:
    return job_service.get_job_for_audiobook(db, audiobook_id)


def update_metadata(db: Session, audiobook: Audiobook, payload: UpdateAudiobookRequest) -> Audiobook:
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(audiobook, field_name, value)
    db.commit()
    db.refresh(audiobook)
    return audiobook


def delete_audiobook(db: Session, audiobook: Audiobook) -> None:
    paths = [audiobook.stored_path]
    cover_path = getattr(audiobook, "cover_path", None)
    if cover_path:
        paths.append(cover_path)

    db.delete(audiobook)
    db.commit()

    for path in paths:
        safe_delete(path)


def reprocess_audiobook(db: Session, audiobook: Audiobook) -> ProcessingJob:
    job = get_job_for_audiobook(db, audiobook.id)
    if job is None:
        raise ProcessingJobMissingError("Processing job not found")
    return job_service.reprocess_audiobook(db, audiobook, job)


def download_path(audiobook: Audiobook) -> Path:
    path = existing_file(audiobook.stored_path)
    if path is None:
        raise AudiobookFileMissingError("Audiobook file not found")
    return path


def cover_path(audiobook: Audiobook) -> Path | None:
    if not getattr(audiobook, "cover_path", None):
        return None
    return existing_file(audiobook.cover_path)
