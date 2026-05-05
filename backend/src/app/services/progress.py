from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Audiobook, UserAudiobookProgress


def get_audiobook(db: Session, audiobook_id: uuid.UUID) -> Audiobook | None:
    return db.get(Audiobook, audiobook_id)


def get_progress(db: Session, *, user_id: uuid.UUID, audiobook_id: uuid.UUID) -> UserAudiobookProgress | None:
    stmt = select(UserAudiobookProgress).where(
        UserAudiobookProgress.user_id == user_id,
        UserAudiobookProgress.audiobook_id == audiobook_id,
    )
    return db.execute(stmt).scalar_one_or_none()


def list_progress(
    db: Session,
    *,
    user_id: uuid.UUID,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[tuple[UserAudiobookProgress, Audiobook]], int]:
    base = select(UserAudiobookProgress, Audiobook).join(Audiobook, Audiobook.id == UserAudiobookProgress.audiobook_id).where(
        UserAudiobookProgress.user_id == user_id
    )
    total = db.execute(select(func.count()).select_from(UserAudiobookProgress).where(UserAudiobookProgress.user_id == user_id)).scalar_one()
    rows = db.execute(
        base.order_by(UserAudiobookProgress.last_played_at.desc(), UserAudiobookProgress.id.desc()).offset(offset).limit(limit)
    ).all()
    return list(rows), int(total)


def continue_listening(
    db: Session,
    *,
    user_id: uuid.UUID,
    limit: int = 10,
) -> list[tuple[UserAudiobookProgress, Audiobook]]:
    stmt = (
        select(UserAudiobookProgress, Audiobook)
        .join(Audiobook, Audiobook.id == UserAudiobookProgress.audiobook_id)
        .where(UserAudiobookProgress.user_id == user_id, UserAudiobookProgress.completed.is_(False))
        .order_by(UserAudiobookProgress.last_played_at.desc(), UserAudiobookProgress.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).all())


def upsert_progress(
    db: Session,
    *,
    user_id: uuid.UUID,
    audiobook: Audiobook,
    position_seconds: int,
    duration_seconds: int | None,
    is_completed: bool,
) -> UserAudiobookProgress:
    now = datetime.now(UTC)
    progress = get_progress(db, user_id=user_id, audiobook_id=audiobook.id)
    if progress is None:
        progress = UserAudiobookProgress(
            user_id=user_id,
            audiobook_id=audiobook.id,
            started_at=now,
        )
        db.add(progress)

    progress.position_seconds = position_seconds
    progress.duration_seconds = duration_seconds
    progress.completed = is_completed
    progress.last_played_at = now
    progress.completed_at = now if is_completed else None
    db.commit()
    db.refresh(progress)
    return progress


def delete_progress(db: Session, *, user_id: uuid.UUID, audiobook_id: uuid.UUID) -> bool:
    progress = get_progress(db, user_id=user_id, audiobook_id=audiobook_id)
    if progress is None:
        return False
    db.delete(progress)
    db.commit()
    return True
