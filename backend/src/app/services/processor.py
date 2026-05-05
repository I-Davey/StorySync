from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Audiobook, ProcessingJob
from app.services.jobs import claim_next_job, complete_job_failure, complete_job_success, recover_expired_leases
from app.services.metadata import extract_m4b_metadata

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


def process_claimed_job(db: Session, job: ProcessingJob, _worker_id: str) -> None:
    audiobook = db.execute(select(Audiobook).where(Audiobook.id == job.audiobook_id)).scalar_one_or_none()
    if audiobook is None:
        raise RuntimeError(f"Audiobook not found for job {job.id}")

    metadata = extract_m4b_metadata(audiobook.stored_path)
    audiobook.metadata_title = metadata.title
    audiobook.metadata_album = metadata.album
    audiobook.metadata_artist = metadata.artist
    audiobook.metadata_genre = metadata.genre
    audiobook.metadata_duration_seconds = metadata.duration_seconds
    audiobook.metadata_track_number = metadata.track_number
    audiobook.metadata_year = metadata.year
    audiobook.metadata_raw = metadata.raw
    db.commit()


def _run_claimed_job_work(job: ProcessingJob, worker_id: str) -> None:
    with SessionLocal() as db:
        process_claimed_job(db, job, worker_id)


def _execute_with_heartbeat(job_id: uuid.UUID, worker_id: str, work_fn: Callable[[], None]) -> bool:
    heartbeat_interval = max(settings.processor_heartbeat_interval_seconds, 0.1)
    lease_window = max(settings.processor_lease_seconds, 1)
    safe_interval = min(heartbeat_interval, max(lease_window / 2, 0.1))
    stop_event = threading.Event()
    lease_lost = threading.Event()

    def _heartbeat_loop() -> None:
        while not stop_event.wait(safe_interval):
            with SessionLocal() as db:
                if not heartbeat_job(db, job_id, worker_id):
                    lease_lost.set()
                    stop_event.set()
                    return

    heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    heartbeat_thread.start()
    try:
        work_fn()
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=safe_interval + 1.0)

    return not lease_lost.is_set()


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
            lease_ok = _execute_with_heartbeat(
                job.id,
                worker_id,
                work_fn=lambda: _run_claimed_job_work(job, worker_id),
            )
            if not lease_ok:
                logger.warning("Lost lease while processing job %s", job.id)
                continue

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
