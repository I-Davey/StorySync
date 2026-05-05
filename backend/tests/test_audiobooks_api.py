from __future__ import annotations

import datetime as dt
import uuid
from io import BytesIO
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models import Audiobook, ProcessingJob
from app.services.uploads import UploadResult


def test_audiobook_read_routes_require_active_user(monkeypatch, override_auth) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)

    class _EmptyListDB:
        def execute(self, stmt):
            return type("Result", (), {"all": lambda self: []})()

    try:
        with TestClient(app) as client:
            unauthorized = client.get("/audiobooks")

            override_auth()
            app.dependency_overrides[get_db] = lambda: _EmptyListDB()
            authorized = client.get("/audiobooks")
    finally:
        app.dependency_overrides.clear()

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_audiobook_write_routes_require_admin(monkeypatch, override_auth, generated_m4b_payload: bytes) -> None:
    monkeypatch.setattr("app.api.audiobooks.handle_upload", MagicMock())
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    audiobook_id = uuid.uuid4()

    try:
        with TestClient(app) as client:
            unauthenticated = client.post(
                "/audiobooks",
                files={"file": ("book.m4b", BytesIO(generated_m4b_payload), "audio/x-m4b")},
            )

            override_auth(is_admin=False)
            forbidden = client.post(
                "/audiobooks/upload",
                files={"file": ("book.m4b", BytesIO(generated_m4b_payload), "audio/x-m4b")},
            )
            forbidden_patch = client.patch(f"/audiobooks/{audiobook_id}", json={"metadata": {"title": "New"}})
            forbidden_delete = client.delete(f"/audiobooks/{audiobook_id}")
            forbidden_cover_upload = client.post(
                f"/audiobooks/{audiobook_id}/cover",
                files={"file": ("cover.jpg", BytesIO(b"fake-jpeg"), "image/jpeg")},
            )
            forbidden_cover_delete = client.delete(f"/audiobooks/{audiobook_id}/cover")
            forbidden_reprocess = client.post(f"/audiobooks/{audiobook_id}/reprocess")
    finally:
        app.dependency_overrides.clear()

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403
    assert forbidden_patch.status_code == 403
    assert forbidden_delete.status_code == 403
    assert forbidden_cover_upload.status_code == 403
    assert forbidden_cover_delete.status_code == 403
    assert forbidden_reprocess.status_code == 403


def test_canonical_upload_endpoint_returns_public_created_payload(monkeypatch, override_auth, generated_m4b_payload: bytes) -> None:
    expected = UploadResult(
        audiobook_id=uuid.uuid4(),
        original_filename="book.m4b",
        stored_path="/data/audio/123.m4b",
        file_size_bytes=2048,
        checksum_sha256="a" * 64,
        job_id=uuid.uuid4(),
        job_state="queued",
    )

    def fake_handle_upload(db, file):
        return expected

    monkeypatch.setattr("app.api.audiobooks.handle_upload", fake_handle_upload)
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    override_auth(is_admin=True)
    app.dependency_overrides[get_db] = lambda: None

    try:
        with TestClient(app) as client:
            response = client.post(
                "/audiobooks",
                files={"file": ("book.m4b", BytesIO(generated_m4b_payload), "audio/x-m4b")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.headers["location"] == f"/audiobooks/{expected.audiobook_id}"
    data = response.json()
    assert data["audiobook_id"] == str(expected.audiobook_id)
    assert data["job_id"] == str(expected.job_id)
    assert data["job_state"] == "queued"
    assert "queue_position" not in data
    assert data["download_url"] == f"/audiobooks/{expected.audiobook_id}/download"
    assert "stored_path" not in data


def test_upload_compatibility_alias_keeps_created_payload(monkeypatch, override_auth, generated_m4b_payload: bytes) -> None:
    expected = UploadResult(
        audiobook_id=uuid.uuid4(),
        original_filename="book.m4b",
        stored_path="/data/audio/123.m4b",
        file_size_bytes=2048,
        checksum_sha256="a" * 64,
        job_id=uuid.uuid4(),
        job_state="queued",
    )

    monkeypatch.setattr("app.api.audiobooks.handle_upload", lambda db, file: expected)
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    override_auth(is_admin=True)
    app.dependency_overrides[get_db] = lambda: None

    try:
        with TestClient(app) as client:
            response = client.post(
                "/audiobooks/upload",
                files={"file": ("book.m4b", BytesIO(generated_m4b_payload), "audio/x-m4b")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["audiobook_id"] == str(expected.audiobook_id)
    assert response.json()["download_url"] == f"/audiobooks/{expected.audiobook_id}/download"
    assert "queue_position" not in response.json()
    assert "stored_path" not in response.json()


def _audiobook_and_job() -> tuple[Audiobook, ProcessingJob]:
    audiobook_id = uuid.uuid4()
    audiobook = Audiobook(
        id=audiobook_id,
        original_filename="book.m4b",
        stored_path="/data/audio/book.m4b",
        file_size_bytes=2048,
        checksum_sha256="a" * 64,
        created_at=dt.datetime.now(dt.UTC),
    )
    job = ProcessingJob(
        id=uuid.uuid4(),
        audiobook_id=audiobook_id,
        state="processing",
        attempt_count=2,
        worker_id="worker-1",
        lease_expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5),
        last_error="sensitive stack trace",
    )
    return audiobook, job


def test_audiobook_detail_returns_public_job_summary_without_worker_internals(monkeypatch, override_auth) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    audiobook, job = _audiobook_and_job()
    monkeypatch.setattr("app.api.audiobooks._get_audiobook_or_404", lambda db, audiobook_id: audiobook)
    monkeypatch.setattr("app.api.audiobooks._get_job_for_audiobook", lambda db, audiobook_id: job)
    override_auth()
    app.dependency_overrides[get_db] = lambda: None

    try:
        with TestClient(app) as client:
            response = client.get(f"/audiobooks/{audiobook.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["job"] == {"id": str(job.id), "audiobook_id": str(audiobook.id), "state": "processing", "attempt_count": 2}


def test_audiobook_list_returns_public_job_summary_without_worker_internals(monkeypatch, override_auth) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    audiobook, job = _audiobook_and_job()

    class _Result:
        def all(self):
            return [(audiobook, job)]

    class _Db:
        def execute(self, stmt):
            return _Result()

    override_auth()
    app.dependency_overrides[get_db] = lambda: _Db()

    try:
        with TestClient(app) as client:
            response = client.get("/audiobooks")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"][0]["job"] == {
        "id": str(job.id),
        "audiobook_id": str(audiobook.id),
        "state": "processing",
        "attempt_count": 2,
    }
