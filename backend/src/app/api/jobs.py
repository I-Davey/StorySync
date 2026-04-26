from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ProcessingJob

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobResponse(BaseModel):
    id: uuid.UUID
    audiobook_id: uuid.UUID
    state: str
    queue_position: int | None
    attempt_count: int
    last_error: str | None = None


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> JobResponse:
    job = db.get(ProcessingJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(
        id=job.id,
        audiobook_id=job.audiobook_id,
        state=job.state,
        queue_position=job.queue_position,
        attempt_count=job.attempt_count,
        last_error=job.last_error,
    )
