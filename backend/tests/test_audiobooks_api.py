from __future__ import annotations

import uuid
from io import BytesIO

from fastapi import UploadFile

from app.api.audiobooks import upload_audiobook
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

    payload = UploadFile(filename="book.m4b", file=BytesIO(b"payload"))
    response = upload_audiobook(file=payload, db=object())

    assert response.audiobook_id == expected.audiobook_id
    assert response.job_id == expected.job_id
    assert response.job_state == "queued"
