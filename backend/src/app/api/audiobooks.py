from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Audiobook, ProcessingJob
from app.schemas import (
    AudiobookListResponse,
    AudiobookMetadata,
    AudiobookResponse,
    CoverResource,
    JobResponse,
    JobState,
    UpdateAudiobookRequest,
    UploadAudiobookResponse,
)
from app.services.covers import delete_manual_cover, extract_embedded_mp4_cover, replace_manual_cover
from app.services.queue import next_queue_position
from app.services.uploads import handle_upload

router = APIRouter(prefix="/audiobooks", tags=["audiobooks"])


def _job_response(job: ProcessingJob) -> JobResponse:
    return JobResponse(
        id=job.id,
        audiobook_id=job.audiobook_id,
        state=job.state,
        queue_position=job.queue_position,
        attempt_count=job.attempt_count,
        worker_id=job.worker_id,
        lease_expires_at=job.lease_expires_at,
        last_error=job.last_error,
    )


def _audiobook_response(audiobook: Audiobook, job: ProcessingJob | None = None) -> AudiobookResponse:
    audiobook_url = f"/audiobooks/{audiobook.id}"
    cover = None
    if getattr(audiobook, "cover_path", None):
        cover = CoverResource(url=f"{audiobook_url}/cover", media_type=getattr(audiobook, "cover_media_type", None))

    return AudiobookResponse(
        id=audiobook.id,
        original_filename=audiobook.original_filename,
        file_size_bytes=audiobook.file_size_bytes,
        checksum_sha256=audiobook.checksum_sha256,
        metadata=AudiobookMetadata(
            title=audiobook.metadata_title,
            album=audiobook.metadata_album,
            artist=audiobook.metadata_artist,
            genre=audiobook.metadata_genre,
            duration_seconds=audiobook.metadata_duration_seconds,
            track_number=audiobook.metadata_track_number,
            year=audiobook.metadata_year,
            raw=audiobook.metadata_raw,
        ),
        cover=cover,
        download_url=f"{audiobook_url}/download",
        created_at=audiobook.created_at,
        job=_job_response(job) if job else None,
    )


def _get_audiobook_or_404(db: Session, audiobook_id: uuid.UUID) -> Audiobook:
    audiobook = db.get(Audiobook, audiobook_id)
    if audiobook is None:
        raise HTTPException(status_code=404, detail="Audiobook not found")
    return audiobook


def _get_job_for_audiobook(db: Session, audiobook_id: uuid.UUID) -> ProcessingJob | None:
    return db.execute(select(ProcessingJob).where(ProcessingJob.audiobook_id == audiobook_id)).scalar_one_or_none()


def _upload_response(result) -> UploadAudiobookResponse:
    return UploadAudiobookResponse(
        audiobook_id=result.audiobook_id,
        original_filename=result.original_filename,
        file_size_bytes=result.file_size_bytes,
        checksum_sha256=result.checksum_sha256,
        job_id=result.job_id,
        job_state=result.job_state,
        queue_position=getattr(result, "queue_position", None),
        download_url=f"/audiobooks/{result.audiobook_id}/download",
    )


@router.post("", response_model=UploadAudiobookResponse, status_code=status.HTTP_201_CREATED)
def create_audiobook(
    response: Response,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadAudiobookResponse:
    result = handle_upload(db, file)
    response.headers["Location"] = f"/audiobooks/{result.audiobook_id}"
    return _upload_response(result)


@router.post("/upload", response_model=UploadAudiobookResponse, status_code=status.HTTP_201_CREATED)
def upload_audiobook(file: UploadFile = File(...), db: Session = Depends(get_db)) -> UploadAudiobookResponse:
    return _upload_response(handle_upload(db, file))


@router.get("/{audiobook_id}", response_model=AudiobookResponse)
def get_audiobook(audiobook_id: uuid.UUID, db: Session = Depends(get_db)) -> AudiobookResponse:
    audiobook = _get_audiobook_or_404(db, audiobook_id)
    job = _get_job_for_audiobook(db, audiobook.id)
    return _audiobook_response(audiobook, job)


@router.patch("/{audiobook_id}", response_model=AudiobookResponse)
def update_audiobook(
    audiobook_id: uuid.UUID,
    payload: UpdateAudiobookRequest,
    db: Session = Depends(get_db),
) -> AudiobookResponse:
    audiobook = _get_audiobook_or_404(db, audiobook_id)
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(audiobook, field_name, value)
    db.commit()
    db.refresh(audiobook)
    job = _get_job_for_audiobook(db, audiobook.id)
    return _audiobook_response(audiobook, job)


@router.post("/{audiobook_id}/cover", response_model=AudiobookResponse)
def upload_audiobook_cover(
    audiobook_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> AudiobookResponse:
    audiobook = _get_audiobook_or_404(db, audiobook_id)
    audiobook = replace_manual_cover(db, audiobook, file)
    job = _get_job_for_audiobook(db, audiobook.id)
    return _audiobook_response(audiobook, job)


@router.get("/{audiobook_id}/cover", response_model=None)
def get_audiobook_cover(audiobook_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    audiobook = _get_audiobook_or_404(db, audiobook_id)

    if audiobook.cover_path:
        path = Path(audiobook.cover_path)
        if path.is_file():
            return FileResponse(path, media_type=audiobook.cover_media_type or "application/octet-stream")

    embedded = extract_embedded_mp4_cover(audiobook)
    if embedded is None:
        raise HTTPException(status_code=404, detail="Cover not found")

    content, media_type = embedded
    return Response(content=content, media_type=media_type)


@router.delete("/{audiobook_id}/cover", status_code=status.HTTP_204_NO_CONTENT)
def delete_audiobook_cover(audiobook_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    audiobook = _get_audiobook_or_404(db, audiobook_id)
    delete_manual_cover(db, audiobook)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{audiobook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_audiobook(audiobook_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    audiobook = _get_audiobook_or_404(db, audiobook_id)
    paths = [audiobook.stored_path]
    cover_path = getattr(audiobook, "cover_path", None)
    if cover_path:
        paths.append(cover_path)

    for path in paths:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Failed to delete stored file: {path}") from exc

    db.delete(audiobook)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{audiobook_id}/reprocess", response_model=JobResponse)
def reprocess_audiobook(audiobook_id: uuid.UUID, db: Session = Depends(get_db)) -> JobResponse:
    audiobook = _get_audiobook_or_404(db, audiobook_id)
    job = _get_job_for_audiobook(db, audiobook.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")

    for field_name in (
        "metadata_title",
        "metadata_album",
        "metadata_artist",
        "metadata_genre",
        "metadata_duration_seconds",
        "metadata_track_number",
        "metadata_year",
        "metadata_raw",
    ):
        setattr(audiobook, field_name, None)

    job.state = "queued"
    job.queue_position = next_queue_position(db)
    job.worker_id = None
    job.lease_expires_at = None
    job.last_error = None

    db.commit()
    db.refresh(job)
    return _job_response(job)


@router.get("/{audiobook_id}/download")
def download_audiobook(audiobook_id: uuid.UUID, db: Session = Depends(get_db)) -> FileResponse:
    audiobook = _get_audiobook_or_404(db, audiobook_id)
    path = Path(audiobook.stored_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audiobook file not found")
    return FileResponse(
        path,
        media_type="audio/mp4",
        filename=audiobook.original_filename,
    )


@router.get("", response_model=AudiobookListResponse)
def list_audiobooks(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    state: JobState | None = None,
    db: Session = Depends(get_db),
) -> AudiobookListResponse:
    offset = (page - 1) * page_size
    stmt = select(Audiobook, ProcessingJob).join(ProcessingJob, ProcessingJob.audiobook_id == Audiobook.id)
    if state:
        stmt = stmt.where(ProcessingJob.state == state.value)
    stmt = stmt.order_by(Audiobook.created_at.desc()).offset(offset).limit(page_size)

    rows = db.execute(stmt).all()
    items = [_audiobook_response(a, j) for a, j in rows]
    return AudiobookListResponse(items=items, page=page, page_size=page_size)
