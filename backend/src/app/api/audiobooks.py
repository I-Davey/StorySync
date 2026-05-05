from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user, require_admin
from app.models import Audiobook, ProcessingJob
from app.schemas import (
    AudiobookListResponse,
    AudiobookMetadata,
    AudiobookResponse,
    CoverResource,
    JobResponse,
    JobState,
    PublicJobSummary,
    UpdateAudiobookRequest,
    UploadAudiobookResponse,
)
from app.services import audiobooks as audiobook_service
from app.services import jobs as job_service
from app.services.covers import delete_manual_cover, extract_embedded_mp4_cover, replace_manual_cover
from app.services.uploads import handle_upload

router = APIRouter(prefix="/audiobooks", tags=["audiobooks"])


def _job_response(job: ProcessingJob) -> JobResponse:
    return JobResponse(
        id=job.id,
        audiobook_id=job.audiobook_id,
        state=job.state,
        attempt_count=job.attempt_count,
        worker_id=job.worker_id,
        lease_expires_at=job.lease_expires_at,
        last_error=job.last_error,
    )


def _public_job_summary(job: ProcessingJob) -> PublicJobSummary:
    return PublicJobSummary(
        id=job.id,
        audiobook_id=job.audiobook_id,
        state=job.state,
        attempt_count=job.attempt_count,
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
        job=_public_job_summary(job) if job else None,
    )


def _get_audiobook_or_404(db: Session, audiobook_id: uuid.UUID) -> Audiobook:
    audiobook = audiobook_service.get_audiobook(db, audiobook_id)
    if audiobook is None:
        raise HTTPException(status_code=404, detail="Audiobook not found")
    return audiobook


def _get_job_for_audiobook(db: Session, audiobook_id: uuid.UUID) -> ProcessingJob | None:
    return audiobook_service.get_job_for_audiobook(db, audiobook_id)


def _upload_response(result) -> UploadAudiobookResponse:
    return UploadAudiobookResponse(
        audiobook_id=result.audiobook_id,
        original_filename=result.original_filename,
        file_size_bytes=result.file_size_bytes,
        checksum_sha256=result.checksum_sha256,
        job_id=result.job_id,
        job_state=result.job_state,
        download_url=f"/audiobooks/{result.audiobook_id}/download",
    )


@router.post(
    "",
    response_model=UploadAudiobookResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_audiobook(
    response: Response,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadAudiobookResponse:
    result = handle_upload(db, file)
    response.headers["Location"] = f"/audiobooks/{result.audiobook_id}"
    return _upload_response(result)


@router.post(
    "/upload",
    response_model=UploadAudiobookResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def upload_audiobook(file: UploadFile = File(...), db: Session = Depends(get_db)) -> UploadAudiobookResponse:
    return _upload_response(handle_upload(db, file))


@router.get("/{audiobook_id}", response_model=AudiobookResponse, dependencies=[Depends(get_current_user)])
def get_audiobook(audiobook_id: uuid.UUID, db: Session = Depends(get_db)) -> AudiobookResponse:
    audiobook = _get_audiobook_or_404(db, audiobook_id)
    job = _get_job_for_audiobook(db, audiobook.id)
    return _audiobook_response(audiobook, job)


@router.patch("/{audiobook_id}", response_model=AudiobookResponse, dependencies=[Depends(require_admin)])
def update_audiobook(
    audiobook_id: uuid.UUID,
    payload: UpdateAudiobookRequest,
    db: Session = Depends(get_db),
) -> AudiobookResponse:
    audiobook = _get_audiobook_or_404(db, audiobook_id)
    audiobook = audiobook_service.update_metadata(db, audiobook, payload)
    job = _get_job_for_audiobook(db, audiobook.id)
    return _audiobook_response(audiobook, job)


@router.post("/{audiobook_id}/cover", response_model=AudiobookResponse, dependencies=[Depends(require_admin)])
def upload_audiobook_cover(
    audiobook_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> AudiobookResponse:
    audiobook = _get_audiobook_or_404(db, audiobook_id)
    audiobook = replace_manual_cover(db, audiobook, file)
    job = _get_job_for_audiobook(db, audiobook.id)
    return _audiobook_response(audiobook, job)


@router.get("/{audiobook_id}/cover", response_model=None, dependencies=[Depends(get_current_user)])
def get_audiobook_cover(audiobook_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    audiobook = _get_audiobook_or_404(db, audiobook_id)

    if audiobook.cover_path:
        path = audiobook_service.cover_path(audiobook)
        if path is not None:
            return FileResponse(path, media_type=audiobook.cover_media_type or "application/octet-stream")

    embedded = extract_embedded_mp4_cover(audiobook)
    if embedded is None:
        raise HTTPException(status_code=404, detail="Cover not found")

    content, media_type = embedded
    return Response(content=content, media_type=media_type)


@router.delete(
    "/{audiobook_id}/cover",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
def delete_audiobook_cover(audiobook_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    audiobook = _get_audiobook_or_404(db, audiobook_id)
    delete_manual_cover(db, audiobook)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{audiobook_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def delete_audiobook(audiobook_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    audiobook = _get_audiobook_or_404(db, audiobook_id)
    try:
        audiobook_service.delete_audiobook(db, audiobook)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to delete stored file") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{audiobook_id}/reprocess", response_model=JobResponse, dependencies=[Depends(require_admin)])
def reprocess_audiobook(audiobook_id: uuid.UUID, db: Session = Depends(get_db)) -> JobResponse:
    audiobook = _get_audiobook_or_404(db, audiobook_id)
    try:
        job = audiobook_service.reprocess_audiobook(db, audiobook)
    except audiobook_service.ProcessingJobMissingError as exc:
        raise HTTPException(status_code=404, detail="Processing job not found") from exc
    except job_service.JobTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_response(job)


@router.get("/{audiobook_id}/download", dependencies=[Depends(get_current_user)])
def download_audiobook(audiobook_id: uuid.UUID, db: Session = Depends(get_db)) -> FileResponse:
    audiobook = _get_audiobook_or_404(db, audiobook_id)
    try:
        path = audiobook_service.download_path(audiobook)
    except audiobook_service.AudiobookFileMissingError as exc:
        raise HTTPException(status_code=404, detail="Audiobook file not found") from exc
    return FileResponse(
        path,
        media_type="audio/mp4",
        filename=audiobook.original_filename,
    )


@router.get("", response_model=AudiobookListResponse, dependencies=[Depends(get_current_user)])
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
