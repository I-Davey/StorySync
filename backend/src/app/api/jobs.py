from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ProcessingJob
from app.schemas import JobListResponse, JobResponse, JobState
from app.services import jobs as job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


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


def _get_job_or_404(db: Session, job_id: uuid.UUID) -> ProcessingJob:
    job = job_service.get_job(db, job_id)
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
    jobs = job_service.list_jobs(db, page=page, page_size=page_size, state=state)
    return JobListResponse(items=[_job_response(job) for job in jobs], page=page, page_size=page_size)


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> JobResponse:
    return _job_response(_get_job_or_404(db, job_id))


@router.post("/{job_id}/cancel", response_model=JobResponse)
def cancel_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> JobResponse:
    job = _get_job_or_404(db, job_id)
    try:
        job = job_service.cancel_job(db, job)
    except job_service.JobTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_response(job)


@router.post("/{job_id}/retry", response_model=JobResponse)
def retry_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> JobResponse:
    job = _get_job_or_404(db, job_id)
    try:
        job = job_service.retry_job(db, job)
    except job_service.JobTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_response(job)
