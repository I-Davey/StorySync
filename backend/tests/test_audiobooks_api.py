from __future__ import annotations

import uuid
from io import BytesIO
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.services.uploads import UploadResult


def test_canonical_upload_endpoint_returns_public_created_payload(monkeypatch, generated_m4b_payload: bytes) -> None:
    expected = UploadResult(
        audiobook_id=uuid.uuid4(),
        original_filename="book.m4b",
        stored_path="/data/audio/123.m4b",
        file_size_bytes=2048,
        checksum_sha256="a" * 64,
        job_id=uuid.uuid4(),
        job_state="queued",
        queue_position=3,
    )

    def fake_handle_upload(db, file):
        return expected

    monkeypatch.setattr("app.api.audiobooks.handle_upload", fake_handle_upload)
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
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
    assert data["queue_position"] == 3
    assert data["download_url"] == f"/audiobooks/{expected.audiobook_id}/download"
    assert "stored_path" not in data


def test_upload_compatibility_alias_keeps_created_payload(monkeypatch, generated_m4b_payload: bytes) -> None:
    expected = UploadResult(
        audiobook_id=uuid.uuid4(),
        original_filename="book.m4b",
        stored_path="/data/audio/123.m4b",
        file_size_bytes=2048,
        checksum_sha256="a" * 64,
        job_id=uuid.uuid4(),
        job_state="queued",
        queue_position=3,
    )

    monkeypatch.setattr("app.api.audiobooks.handle_upload", lambda db, file: expected)
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
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
    assert "stored_path" not in response.json()
