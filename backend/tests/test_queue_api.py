from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.api.audiobooks import list_audiobooks, reprocess_audiobook
from app.api.jobs import cancel_job, get_job, list_jobs, retry_job
from app.schemas import JobState


class _DummyDB:
    def __init__(self, *, audiobook=None, job=None, list_rows=None):
        self._audiobook = audiobook
        self._job = job
        self._list_rows = list_rows or []
        self.committed = False

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
        return SimpleNamespace(
            all=lambda: self._list_rows,
            scalars=lambda: SimpleNamespace(all=lambda: [row[0] if isinstance(row, tuple) else row for row in self._list_rows]),
        )

    def scalar(self, stmt):
        return 42

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        return None


def test_get_job_endpoint_returns_job() -> None:
    job_id = uuid.uuid4()
    audiobook_id = uuid.uuid4()
    db = _DummyDB(
        job=SimpleNamespace(
            id=job_id,
            audiobook_id=audiobook_id,
            state="queued",
            attempt_count=0,
            worker_id=None,
            lease_expires_at=None,
            last_error=None,
        )
    )

    response = get_job(job_id=job_id, db=db)

    assert not hasattr(response, "queue_position")


def _job(state: str):
    return SimpleNamespace(
        id=uuid.uuid4(),
        audiobook_id=uuid.uuid4(),
        state=state,
        attempt_count=2,
        worker_id="worker-1",
        lease_expires_at=datetime.now(timezone.utc),
        last_error="boom",
    )


def test_list_jobs_endpoint_returns_filtered_page() -> None:
    job = _job("queued")
    db = _DummyDB(list_rows=[(job,)])

    response = list_jobs(page=1, page_size=10, state=JobState.queued, db=db)

    assert response.page == 1
    assert response.page_size == 10
    assert response.items[0].id == job.id
    assert response.items[0].state == "queued"
    assert not hasattr(response.items[0], "queue_position")


def test_cancel_job_clears_queue_and_worker_fields() -> None:
    job = _job("queued")
    db = _DummyDB(job=job)

    response = cancel_job(job_id=job.id, db=db)

    assert response.state == "cancelled"
    assert response.worker_id is None
    assert response.lease_expires_at is None
    assert db.committed


def test_cancel_processed_job_conflicts() -> None:
    job = _job("processed")
    db = _DummyDB(job=job)

    try:
        cancel_job(job_id=job.id, db=db)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("Expected HTTPException")


def test_cancel_processing_job_conflicts() -> None:
    job = _job("processing")
    db = _DummyDB(job=job)

    try:
        cancel_job(job_id=job.id, db=db)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("Expected HTTPException")


def test_retry_cancelled_job_requeues_without_resetting_attempt_count() -> None:
    job = _job("cancelled")
    db = _DummyDB(job=job)

    response = retry_job(job_id=job.id, db=db)

    assert response.state == "queued"
    assert response.attempt_count == 2
    assert response.worker_id is None
    assert response.lease_expires_at is None
    assert response.last_error is None
    assert db.committed


def test_retry_queued_job_conflicts() -> None:
    job = _job("queued")
    db = _DummyDB(job=job)

    try:
        retry_job(job_id=job.id, db=db)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("Expected HTTPException")


def test_reprocess_queued_job_conflicts() -> None:
    audiobook = SimpleNamespace(id=uuid.uuid4())
    job = _job("queued")
    job.audiobook_id = audiobook.id
    db = _DummyDB(audiobook=audiobook, job=job)

    try:
        reprocess_audiobook(audiobook_id=audiobook.id, db=db)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("Expected HTTPException")


def test_reprocess_processing_job_conflicts() -> None:
    audiobook = SimpleNamespace(id=uuid.uuid4())
    job = _job("processing")
    job.audiobook_id = audiobook.id
    db = _DummyDB(audiobook=audiobook, job=job)

    try:
        reprocess_audiobook(audiobook_id=audiobook.id, db=db)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("Expected HTTPException")


def test_list_audiobooks_supports_state_filter_query_param() -> None:
    audiobook_id = uuid.uuid4()
    job_id = uuid.uuid4()
    audiobook = SimpleNamespace(
        id=audiobook_id,
        original_filename="book.m4b",
        stored_path="/data/audio/book.m4b",
        file_size_bytes=321,
        checksum_sha256="a" * 64,
        metadata_title="My Book",
        metadata_album=None,
        metadata_artist=None,
        metadata_genre=None,
        metadata_duration_seconds=None,
        metadata_track_number=None,
        metadata_year=None,
        metadata_raw=None,
        created_at=datetime.now(timezone.utc),
    )
    job = SimpleNamespace(
        id=job_id,
        audiobook_id=audiobook_id,
        state="queued",
        attempt_count=0,
        worker_id=None,
        lease_expires_at=None,
        last_error=None,
    )
    db = _DummyDB(list_rows=[(audiobook, job)])

    response = list_audiobooks(page=1, page_size=10, state=JobState.queued, db=db)

    assert response.page == 1
    assert response.items[0].job is not None
    assert response.items[0].job.state == "queued"
    assert response.items[0].metadata.title == "My Book"
    assert response.items[0].download_url == f"/audiobooks/{audiobook_id}/download"
    assert response.items[0].cover is None
    assert not hasattr(response.items[0], "stored_path")
    assert not hasattr(response.items[0], "cover_path")


def test_job_routes_require_admin(monkeypatch, override_auth) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    job_id = uuid.uuid4()

    try:
        with TestClient(app) as client:
            unauthenticated = client.get("/jobs")

            override_auth(is_admin=False)
            forbidden_list = client.get("/jobs")
            forbidden_get = client.get(f"/jobs/{job_id}")
            forbidden_cancel = client.post(f"/jobs/{job_id}/cancel")
            forbidden_retry = client.post(f"/jobs/{job_id}/retry")
    finally:
        app.dependency_overrides.clear()

    assert unauthenticated.status_code == 401
    assert forbidden_list.status_code == 403
    assert forbidden_get.status_code == 403
    assert forbidden_cancel.status_code == 403
    assert forbidden_retry.status_code == 403


def test_list_pagination_query_bounds_are_enforced(monkeypatch, override_auth) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    override_auth(is_admin=True)
    app.dependency_overrides[get_db] = lambda: None

    try:
        with TestClient(app) as client:
            audiobook_bad_page = client.get("/audiobooks", params={"page": 0})
            audiobook_bad_page_size = client.get("/audiobooks", params={"page_size": 101})
            jobs_bad_page = client.get("/jobs", params={"page": 0})
            jobs_bad_page_size = client.get("/jobs", params={"page_size": 0})
            audiobook_bad_state = client.get("/audiobooks", params={"state": "bogus"})
            jobs_bad_state = client.get("/jobs", params={"state": "bogus"})
    finally:
        app.dependency_overrides.clear()

    assert audiobook_bad_page.status_code == 422
    assert audiobook_bad_page_size.status_code == 422
    assert jobs_bad_page.status_code == 422
    assert jobs_bad_page_size.status_code == 422
    assert audiobook_bad_state.status_code == 422
    assert jobs_bad_state.status_code == 422
