from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.api.audiobooks import list_audiobooks
from app.api.jobs import get_job


class _DummyDB:
    def __init__(self, *, audiobook=None, job=None, list_rows=None):
        self._audiobook = audiobook
        self._job = job
        self._list_rows = list_rows or []

    def get(self, model, key):
        name = model.__name__
        if name == "Audiobook":
            return self._audiobook
        if name == "ProcessingJob":
            return self._job
        return None

    def execute(self, stmt):
        stmt_text = str(stmt)
        if "WHERE processing_jobs.audiobook_id" in stmt_text:
            return SimpleNamespace(scalar_one_or_none=lambda: self._job)
        return SimpleNamespace(all=lambda: self._list_rows)


def test_get_job_endpoint_returns_job() -> None:
    job_id = uuid.uuid4()
    audiobook_id = uuid.uuid4()
    db = _DummyDB(
        job=SimpleNamespace(
            id=job_id,
            audiobook_id=audiobook_id,
            state="queued",
            queue_position=7,
            attempt_count=0,
            last_error=None,
        )
    )

    response = get_job(job_id=job_id, db=db)

    assert response.queue_position == 7


def test_list_audiobooks_supports_state_filter_query_param() -> None:
    audiobook_id = uuid.uuid4()
    job_id = uuid.uuid4()
    audiobook = SimpleNamespace(
        id=audiobook_id,
        original_filename="book.m4b",
        stored_path="/data/audio/book.m4b",
        file_size_bytes=321,
        checksum_sha256="a" * 64,
        created_at=datetime.now(timezone.utc),
    )
    job = SimpleNamespace(
        id=job_id,
        audiobook_id=audiobook_id,
        state="queued",
        queue_position=1,
        attempt_count=0,
        last_error=None,
    )
    db = _DummyDB(list_rows=[(audiobook, job)])

    response = list_audiobooks(page=1, page_size=10, state="queued", db=db)

    assert response.page == 1
    assert response.items[0].job is not None
    assert response.items[0].job.state == "queued"
