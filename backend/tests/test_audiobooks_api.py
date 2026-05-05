from __future__ import annotations

import uuid
from io import BytesIO
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
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
