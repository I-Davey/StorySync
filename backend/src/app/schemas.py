from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class JobState(str, Enum):
    received = "received"
    queued = "queued"
    processing = "processing"
    processed = "processed"
    failed = "failed"
    cancelled = "cancelled"


class JobResponse(BaseModel):
    id: uuid.UUID
    audiobook_id: uuid.UUID
    state: JobState
    queue_position: int | None
    attempt_count: int
    worker_id: str | None = None
    lease_expires_at: datetime | None = None
    last_error: str | None = None


class JobListResponse(BaseModel):
    items: list[JobResponse]
    page: int
    page_size: int


class AudiobookMetadata(BaseModel):
    title: str | None = None
    album: str | None = None
    artist: str | None = None
    genre: str | None = None
    duration_seconds: int | None = None
    track_number: int | None = None
    year: int | None = None
    raw: dict | None = None


class CoverResource(BaseModel):
    url: str
    media_type: str | None = None


class UploadAudiobookResponse(BaseModel):
    audiobook_id: uuid.UUID = Field(description="Created audiobook identifier")
    original_filename: str
    file_size_bytes: int
    checksum_sha256: str
    job_id: uuid.UUID
    job_state: JobState
    queue_position: int | None = None
    download_url: str


class AudiobookResponse(BaseModel):
    id: uuid.UUID
    original_filename: str
    file_size_bytes: int
    checksum_sha256: str
    metadata: AudiobookMetadata
    cover: CoverResource | None = None
    download_url: str
    created_at: datetime
    job: JobResponse | None = None


class AudiobookListResponse(BaseModel):
    items: list[AudiobookResponse]
    page: int
    page_size: int


class UpdateAudiobookRequest(BaseModel):
    metadata_title: str | None = None
    metadata_album: str | None = None
    metadata_artist: str | None = None
    metadata_genre: str | None = None
    metadata_duration_seconds: int | None = Field(default=None, ge=0)
    metadata_track_number: int | None = Field(default=None, ge=0)
    metadata_year: int | None = Field(default=None, ge=0)
