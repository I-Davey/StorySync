from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.uploads import handle_upload

router = APIRouter(prefix="/audiobooks", tags=["audiobooks"])


class UploadAudiobookResponse(BaseModel):
    audiobook_id: uuid.UUID = Field(description="Created audiobook identifier")
    original_filename: str
    stored_path: str
    file_size_bytes: int
    checksum_sha256: str
    job_id: uuid.UUID
    job_state: str


@router.post("/upload", response_model=UploadAudiobookResponse, status_code=201)
def upload_audiobook(file: UploadFile = File(...), db: Session = Depends(get_db)) -> UploadAudiobookResponse:
    result = handle_upload(db, file)
    return UploadAudiobookResponse(
        audiobook_id=result.audiobook_id,
        original_filename=result.original_filename,
        stored_path=result.stored_path,
        file_size_bytes=result.file_size_bytes,
        checksum_sha256=result.checksum_sha256,
        job_id=result.job_id,
        job_state=result.job_state,
    )
