from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Audiobook, ProcessingJob
from app.schemas import JobState


class JobTransitionError(ValueError):
    """Raised when a requested job state transition is not allowed."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_queued_job(db: Session, audiobook_id: uuid.UUID) -> ProcessingJob:
    job = ProcessingJob(audiobook_id=audiobook_id, state=JobState.queued.value)
    db.add(job)
    db.flush()
    return job


def get_job(db: Session, job_id: uuid.UUID) -> ProcessingJob | None:
    return db.get(ProcessingJob, job_id)


def get_job_for_audiobook(db: Session, audiobook_id: uuid.UUID) -> ProcessingJob | None:
    return db.execute(select(ProcessingJob).where(ProcessingJob.audiobook_id == audiobook_id)).scalar_one_or_none()


def list_jobs(
    db: Session,
    *,
    page: int,
    page_size: int,
    state: JobState | None = None,
) -> list[ProcessingJob]:
    stmt = select(ProcessingJob)
    if state:
        stmt = stmt.where(ProcessingJob.state == state.value)
    stmt = stmt.order_by(ProcessingJob.created_at.desc(), ProcessingJob.id.asc()).offset((page - 1) * page_size).limit(page_size)
    return db.execute(stmt).scalars().all()


def cancel_job(db: Session, job: ProcessingJob) -> ProcessingJob:
    if job.state not in {JobState.queued.value, JobState.failed.value}:
        raise JobTransitionError(f"Cannot cancel job in state '{job.state}'")

    job.state = JobState.cancelled.value
    job.worker_id = None
    job.lease_expires_at = None

    db.commit()
    db.refresh(job)
    return job


def retry_job(db: Session, job: ProcessingJob) -> ProcessingJob:
    if job.state not in {JobState.failed.value, JobState.cancelled.value}:
        raise JobTransitionError(f"Cannot retry job in state '{job.state}'")

    job.state = JobState.queued.value
    job.last_error = None
    job.worker_id = None
    job.lease_expires_at = None

    db.commit()
    db.refresh(job)
    return job


def reprocess_audiobook(db: Session, audiobook: Audiobook, job: ProcessingJob) -> ProcessingJob:
    if job.state in {JobState.queued.value, JobState.processing.value}:
        raise JobTransitionError(f"Cannot reprocess job in state '{job.state}'")

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

    job.state = JobState.queued.value
    job.worker_id = None
    job.lease_expires_at = None
    job.last_error = None

    db.commit()
    db.refresh(job)
    return job


def recover_expired_leases(db: Session, now: datetime | None = None) -> int:
    current = now or utcnow()
    expired = db.execute(
        select(ProcessingJob)
        .where(
            ProcessingJob.state == JobState.processing.value,
            ProcessingJob.lease_expires_at.is_not(None),
            ProcessingJob.lease_expires_at < current,
        )
        .order_by(ProcessingJob.updated_at.asc())
        .with_for_update(skip_locked=True)
    ).scalars().all()

    if not expired:
        return 0

    for job in expired:
        job.state = JobState.queued.value
        job.worker_id = None
        job.lease_expires_at = None
        msg = "Lease expired; requeued for processing."
        job.last_error = f"{job.last_error} | {msg}" if job.last_error else msg

    db.commit()
    return len(expired)


def claim_next_job(db: Session, worker_id: str, now: datetime | None = None) -> ProcessingJob | None:
    current = now or utcnow()
    stmt = (
        select(ProcessingJob)
        .where(ProcessingJob.state == JobState.queued.value)
        .order_by(ProcessingJob.created_at.asc(), ProcessingJob.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        return None

    job.state = JobState.processing.value
    job.worker_id = worker_id
    job.lease_expires_at = current + timedelta(seconds=settings.processor_lease_seconds)
    job.attempt_count = int(job.attempt_count) + 1

    db.commit()
    db.refresh(job)
    return job


def complete_job_success(db: Session, job_id: uuid.UUID, worker_id: str) -> bool:
    result = db.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.id == job_id,
            ProcessingJob.state == JobState.processing.value,
            ProcessingJob.worker_id == worker_id,
        )
        .values(
            state=JobState.processed.value,
            worker_id=None,
            lease_expires_at=None,
            last_error=None,
        )
    )
    db.commit()
    return result.rowcount > 0


def complete_job_failure(
    db: Session,
    job_id: uuid.UUID,
    worker_id: str,
    error_text: str,
    retryable: bool = True,
) -> bool:
    job = db.execute(
        select(ProcessingJob)
        .where(
            ProcessingJob.id == job_id,
            ProcessingJob.state == JobState.processing.value,
            ProcessingJob.worker_id == worker_id,
        )
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if job is None:
        return False

    if retryable and job.attempt_count < settings.processor_max_attempts:
        job.state = JobState.queued.value
        job.worker_id = None
        job.lease_expires_at = None
        job.last_error = error_text
    else:
        job.state = JobState.failed.value
        job.worker_id = None
        job.lease_expires_at = None
        job.last_error = error_text

    db.commit()
    return True
