from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import ProcessingJob

logger = logging.getLogger(__name__)
QUEUE_LOCK_KEY = 730001


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _next_queue_position(db: Session) -> int:
    db.execute(select(func.pg_advisory_xact_lock(QUEUE_LOCK_KEY)))
    position = db.scalar(select(func.coalesce(func.max(ProcessingJob.queue_position), 0) + 1))
    return int(position)


def recover_expired_leases(db: Session, now: datetime | None = None) -> int:
    current = now or utcnow()
    expired = db.execute(
        select(ProcessingJob)
        .where(
            ProcessingJob.state == "processing",
            ProcessingJob.lease_expires_at.is_not(None),
            ProcessingJob.lease_expires_at < current,
        )
        .order_by(ProcessingJob.updated_at.asc())
        .with_for_update(skip_locked=True)
    ).scalars().all()

    if not expired:
        return 0

    for job in expired:
        job.state = "queued"
        job.queue_position = _next_queue_position(db)
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
        .where(ProcessingJob.state == "queued")
        .order_by(ProcessingJob.queue_position.asc(), ProcessingJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        return None

    job.state = "processing"
    job.worker_id = worker_id
    job.lease_expires_at = current + timedelta(seconds=settings.processor_lease_seconds)
    job.attempt_count = int(job.attempt_count) + 1
    job.queue_position = None

    db.commit()
    db.refresh(job)
    return job


def heartbeat_job(db: Session, job_id: uuid.UUID, worker_id: str, now: datetime | None = None) -> bool:
    current = now or utcnow()
    new_expiry = current + timedelta(seconds=settings.processor_lease_seconds)
    result = db.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.id == job_id,
            ProcessingJob.state == "processing",
            ProcessingJob.worker_id == worker_id,
        )
        .values(lease_expires_at=new_expiry)
    )
    db.commit()
    return result.rowcount > 0


def complete_job_success(db: Session, job_id: uuid.UUID, worker_id: str) -> bool:
    result = db.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.id == job_id,
            ProcessingJob.state == "processing",
            ProcessingJob.worker_id == worker_id,
        )
        .values(
            state="processed",
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
            ProcessingJob.state == "processing",
            ProcessingJob.worker_id == worker_id,
        )
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if job is None:
        return False

    if retryable and job.attempt_count < settings.processor_max_attempts:
        job.state = "queued"
        job.queue_position = _next_queue_position(db)
        job.worker_id = None
        job.lease_expires_at = None
        job.last_error = error_text
    else:
        job.state = "failed"
        job.worker_id = None
        job.lease_expires_at = None
        job.last_error = error_text
        job.queue_position = None

    db.commit()
    return True


def process_claimed_job(_db: Session, _job: ProcessingJob, _worker_id: str) -> None:
    """Placeholder processing implementation for Phase 4.

    Phase 5 will replace this with real metadata extraction/transformation work.
    """


def run_processor_iteration(worker_id: str) -> None:
    with SessionLocal() as db:
        recovered = recover_expired_leases(db)
        if recovered:
            logger.info("Recovered %s expired processing leases", recovered)

    for _ in range(max(1, settings.processor_batch_size)):
        with SessionLocal() as db:
            job = claim_next_job(db, worker_id=worker_id)

        if job is None:
            return

        try:
            with SessionLocal() as db:
                ok = heartbeat_job(db, job.id, worker_id)
                if not ok:
                    logger.warning("Lost lease while heartbeating job %s", job.id)
                    continue

            with SessionLocal() as db:
                process_claimed_job(db, job, worker_id)

            with SessionLocal() as db:
                complete_job_success(db, job.id, worker_id)
        except Exception as exc:  # noqa: BLE001 - catch to keep worker loop alive
            logger.exception("Job %s failed in background processor", job.id)
            with SessionLocal() as db:
                complete_job_failure(db, job.id, worker_id, str(exc), retryable=True)


def processor_loop(stop_event: threading.Event, worker_id: str) -> None:
    interval = max(settings.processor_poll_interval_seconds, 0.1)
    while not stop_event.is_set():
        run_processor_iteration(worker_id)
        stop_event.wait(interval)


def start_processor_thread() -> tuple[threading.Thread, threading.Event]:
    stop_event = threading.Event()
    worker_id = f"worker-{uuid.uuid4()}"
    thread = threading.Thread(target=processor_loop, args=(stop_event, worker_id), daemon=True)
    thread.start()
    return thread, stop_event
