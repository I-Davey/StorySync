from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Audiobook, ProcessingJob
from app.services.uploads import handle_upload

router = APIRouter(prefix="/audiobooks", tags=["audiobooks"])


class UploadAudiobookResponse(BaseModel):
    audiobook_id: uuid.UUID = Field(description="Created audiobook identifier")
    original_filename: str
    stored_path: str
    file_size_bytes: int
    checksum_sha256: str
    job_id: uuid.UUID
    job_state: str
    queue_position: int | None = None


class JobResponse(BaseModel):
    id: uuid.UUID
    audiobook_id: uuid.UUID
    state: str
    queue_position: int | None
    attempt_count: int
    worker_id: str | None = None
    lease_expires_at: datetime | None = None
    last_error: str | None = None


class AudiobookResponse(BaseModel):
    id: uuid.UUID
    original_filename: str
    stored_path: str
    file_size_bytes: int
    checksum_sha256: str
    created_at: datetime
    job: JobResponse | None = None


class AudiobookListResponse(BaseModel):
    items: list[AudiobookResponse]
    page: int
    page_size: int


@router.post("/upload", response_model=UploadAudiobookResponse, status_code=201)
def upload_audiobook(file: UploadFile = File(...), db: Session = Depends(get_db)) -> UploadAudiobookResponse:
    result = handle_upload(db, file)
    return UploadAudiobookResponse(
        audiobook_id=result.audiobook_id,
        original_filename=result.original_filename,
        stored_path=result.stored_path,
        file_size_bytes=result.file_size_bytes,
        checksum_sha256=result.checksum_sha256,
        job_id=result.job_id,
        job_state=result.job_state,
        queue_position=getattr(result, "queue_position", None),
    )


@router.get("/{audiobook_id}", response_model=AudiobookResponse)
def get_audiobook(audiobook_id: uuid.UUID, db: Session = Depends(get_db)) -> AudiobookResponse:
    audiobook = db.get(Audiobook, audiobook_id)
    if audiobook is None:
        raise HTTPException(status_code=404, detail="Audiobook not found")

    job = db.execute(select(ProcessingJob).where(ProcessingJob.audiobook_id == audiobook.id)).scalar_one_or_none()
    return AudiobookResponse(
        id=audiobook.id,
        original_filename=audiobook.original_filename,
        stored_path=audiobook.stored_path,
        file_size_bytes=audiobook.file_size_bytes,
        checksum_sha256=audiobook.checksum_sha256,
        created_at=audiobook.created_at,
        job=(
            JobResponse(
                id=job.id,
                audiobook_id=job.audiobook_id,
                state=job.state,
                queue_position=job.queue_position,
                attempt_count=job.attempt_count,
                worker_id=job.worker_id,
                lease_expires_at=job.lease_expires_at,
                last_error=job.last_error,
            )
            if job
            else None
        ),
    )


@router.get("", response_model=AudiobookListResponse)
def list_audiobooks(
    page: int = 1,
    page_size: int = 20,
    state: str | None = None,
    db: Session = Depends(get_db),
) -> AudiobookListResponse:
    offset = (max(page, 1) - 1) * max(page_size, 1)
    stmt = select(Audiobook, ProcessingJob).join(ProcessingJob, ProcessingJob.audiobook_id == Audiobook.id)
    if state:
        stmt = stmt.where(ProcessingJob.state == state)
    stmt = stmt.order_by(Audiobook.created_at.desc()).offset(offset).limit(max(page_size, 1))

    rows = db.execute(stmt).all()
    items = [
        AudiobookResponse(
            id=a.id,
            original_filename=a.original_filename,
            stored_path=a.stored_path,
            file_size_bytes=a.file_size_bytes,
            checksum_sha256=a.checksum_sha256,
            created_at=a.created_at,
            job=JobResponse(
                id=j.id,
                audiobook_id=j.audiobook_id,
                state=j.state,
                queue_position=j.queue_position,
                attempt_count=j.attempt_count,
                worker_id=j.worker_id,
                lease_expires_at=j.lease_expires_at,
                last_error=j.last_error,
            ),
        )
        for a, j in rows
    ]
    return AudiobookListResponse(items=items, page=max(page, 1), page_size=max(page_size, 1))
