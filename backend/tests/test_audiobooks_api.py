from __future__ import annotations

import uuid
from io import BytesIO
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.services.uploads import UploadResult


def test_upload_endpoint_returns_created_payload(monkeypatch) -> None:
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
    app.dependency_overrides[get_db] = lambda: None

    try:
        with TestClient(app) as client:
            response = client.post(
                "/audiobooks/upload",
                files={"file": ("book.m4b", BytesIO(b"payload"), "audio/x-m4b")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["audiobook_id"] == str(expected.audiobook_id)
    assert data["job_id"] == str(expected.job_id)
    assert data["job_state"] == "queued"
    assert data["queue_position"] == 3
