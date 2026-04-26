from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

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
    )

    def fake_handle_upload(db, file):
        return expected

    monkeypatch.setattr("app.api.audiobooks.handle_upload", fake_handle_upload)
    monkeypatch.setattr(app.router, "on_startup", [])

    with TestClient(app) as client:
        response = client.post(
            "/audiobooks/upload",
            files={"file": ("book.m4b", b"payload", "audio/mp4")},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["audiobook_id"] == str(expected.audiobook_id)
    assert body["job_id"] == str(expected.job_id)
    assert body["job_state"] == "queued"
