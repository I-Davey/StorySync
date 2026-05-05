from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ProcessingJob

QUEUE_LOCK_KEY = 730001


def next_queue_position(db: Session) -> int:
    db.execute(select(func.pg_advisory_xact_lock(QUEUE_LOCK_KEY)))
    position = db.scalar(select(func.coalesce(func.max(ProcessingJob.queue_position), 0) + 1))
    return int(position)
