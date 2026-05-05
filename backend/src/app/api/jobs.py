from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ProcessingJob
from app.schemas import JobListResponse, JobResponse, JobState
from app.services.queue import next_queue_position

router = APIRouter(prefix="/jobs", tags=["jobs"])


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


def _get_job_or_404(db: Session, job_id: uuid.UUID) -> ProcessingJob:
    job = db.get(ProcessingJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("", response_model=JobListResponse)
def list_jobs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    state: JobState | None = None,
    db: Session = Depends(get_db),
) -> JobListResponse:
    stmt = select(ProcessingJob)
    if state:
        stmt = stmt.where(ProcessingJob.state == state.value)
    stmt = stmt.order_by(ProcessingJob.created_at.desc(), ProcessingJob.id.asc()).offset((page - 1) * page_size).limit(page_size)

    jobs = db.execute(stmt).scalars().all()
    return JobListResponse(items=[_job_response(job) for job in jobs], page=page, page_size=page_size)


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> JobResponse:
    return _job_response(_get_job_or_404(db, job_id))


@router.post("/{job_id}/cancel", response_model=JobResponse)
def cancel_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> JobResponse:
    job = _get_job_or_404(db, job_id)
    if job.state not in {"received", "queued", "failed"}:
        raise HTTPException(status_code=409, detail=f"Cannot cancel job in state '{job.state}'")

    job.state = "cancelled"
    job.queue_position = None
    job.worker_id = None
    job.lease_expires_at = None

    db.commit()
    db.refresh(job)
    return _job_response(job)


@router.post("/{job_id}/retry", response_model=JobResponse)
def retry_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> JobResponse:
    job = _get_job_or_404(db, job_id)
    if job.state not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"Cannot retry job in state '{job.state}'")

    job.state = "queued"
    job.queue_position = next_queue_position(db)
    job.last_error = None
    job.worker_id = None
    job.lease_expires_at = None

    db.commit()
    db.refresh(job)
    return _job_response(job)
