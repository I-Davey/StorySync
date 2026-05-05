from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models import Audiobook, User, UserAudiobookProgress
from app.services import progress as progress_service

router = APIRouter(tags=["progress"])


class ProgressAudiobookSummary(BaseModel):
    id: uuid.UUID
    title: str | None = None
    author: str | None = None
    duration_seconds: int | None = None


class ProgressResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    audiobook_id: uuid.UUID
    position_seconds: int
    duration_seconds: int | None = None
    is_completed: bool
    started_at: datetime
    last_played_at: datetime
    completed_at: datetime | None = None
    audiobook: ProgressAudiobookSummary | None = None


class ProgressListResponse(BaseModel):
    items: list[ProgressResponse]
    offset: int
    limit: int
    total: int | None = None


class UpdateProgressRequest(BaseModel):
    position_seconds: int = Field(ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)
    is_completed: bool = False


def _audiobook_summary(audiobook: Audiobook) -> ProgressAudiobookSummary:
    return ProgressAudiobookSummary(
        id=audiobook.id,
        title=audiobook.metadata_title or audiobook.metadata_album or audiobook.original_filename,
        author=audiobook.metadata_artist,
        duration_seconds=audiobook.metadata_duration_seconds,
    )


def _progress_response(
    progress: UserAudiobookProgress,
    audiobook: Audiobook | None = None,
) -> ProgressResponse:
    return ProgressResponse(
        id=progress.id,
        user_id=progress.user_id,
        audiobook_id=progress.audiobook_id,
        position_seconds=progress.position_seconds,
        duration_seconds=progress.duration_seconds,
        is_completed=progress.completed,
        started_at=progress.started_at,
        last_played_at=progress.last_played_at,
        completed_at=progress.completed_at,
        audiobook=_audiobook_summary(audiobook) if audiobook is not None else None,
    )


def _get_audiobook_or_404(db: Session, audiobook_id: uuid.UUID) -> Audiobook:
    audiobook = progress_service.get_audiobook(db, audiobook_id)
    if audiobook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audiobook not found")
    return audiobook


@router.get("/me/progress", response_model=ProgressListResponse)
def list_my_progress(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProgressListResponse:
    rows, total = progress_service.list_progress(db, user_id=current_user.id, offset=offset, limit=limit)
    return ProgressListResponse(
        items=[_progress_response(progress, audiobook) for progress, audiobook in rows],
        offset=offset,
        limit=limit,
        total=total,
    )


@router.get("/me/continue-listening", response_model=ProgressListResponse)
def continue_listening(
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProgressListResponse:
    rows = progress_service.continue_listening(db, user_id=current_user.id, limit=limit)
    return ProgressListResponse(
        items=[_progress_response(progress, audiobook) for progress, audiobook in rows],
        offset=0,
        limit=limit,
        total=None,
    )


@router.get("/audiobooks/{audiobook_id}/progress", response_model=ProgressResponse)
def get_audiobook_progress(
    audiobook_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProgressResponse:
    audiobook = _get_audiobook_or_404(db, audiobook_id)
    progress = progress_service.get_progress(db, user_id=current_user.id, audiobook_id=audiobook.id)
    if progress is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Progress not found")
    return _progress_response(progress, audiobook)


@router.put("/audiobooks/{audiobook_id}/progress", response_model=ProgressResponse)
def put_audiobook_progress(
    audiobook_id: uuid.UUID,
    payload: UpdateProgressRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProgressResponse:
    audiobook = _get_audiobook_or_404(db, audiobook_id)
    progress = progress_service.upsert_progress(
        db,
        user_id=current_user.id,
        audiobook=audiobook,
        position_seconds=payload.position_seconds,
        duration_seconds=payload.duration_seconds,
        is_completed=payload.is_completed,
    )
    return _progress_response(progress, audiobook)


@router.delete("/audiobooks/{audiobook_id}/progress", status_code=status.HTTP_204_NO_CONTENT)
def delete_audiobook_progress(
    audiobook_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    _get_audiobook_or_404(db, audiobook_id)
    progress_service.delete_progress(db, user_id=current_user.id, audiobook_id=audiobook_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
