from __future__ import annotations

import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile

from app.models import Audiobook, ProcessingJob
from app.services.uploads import handle_upload


@dataclass
class _ScalarResult:
    value: int


class _IntegrationDB:
    """Tiny in-memory stand-in implementing the Session methods used by handle_upload."""

    def __init__(self) -> None:
        self.audiobooks: list[Audiobook] = []
        self.jobs: list[ProcessingJob] = []
        self._pending: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, obj: object) -> None:
        self._pending.append(obj)

    def flush(self) -> None:
        for obj in self._pending:
            if isinstance(obj, Audiobook):
                if obj.id is None:
                    obj.id = uuid.uuid4()
                self.audiobooks.append(obj)
            elif isinstance(obj, ProcessingJob):
                if obj.id is None:
                    obj.id = uuid.uuid4()
                self.jobs.append(obj)
        self._pending.clear()

    def execute(self, _stmt) -> _ScalarResult:
        # advisory lock query is ignored in this integration stub
        return _ScalarResult(value=1)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _obj: object) -> None:
        return

    def rollback(self) -> None:
        self.rollbacks += 1


def test_handle_upload_end_to_end_with_generated_fixture(tmp_path: Path, generated_m4b_payload: bytes, monkeypatch) -> None:
    db = _IntegrationDB()
    upload = UploadFile(filename="runtime-generated.m4b", file=BytesIO(generated_m4b_payload))

    monkeypatch.setattr("app.services.uploads.settings.audio_storage_root", str(tmp_path))

    result = handle_upload(db, upload)

    assert result.original_filename == "runtime-generated.m4b"
    assert result.job_state == "queued"
    assert not hasattr(result, "queue_position")
    assert result.file_size_bytes == len(generated_m4b_payload)

    stored_file = Path(result.stored_path)
    assert stored_file.exists()
    assert stored_file.suffix == ".m4b"
    assert stored_file.read_bytes() == generated_m4b_payload

    assert len(db.audiobooks) == 1
    assert len(db.jobs) == 1
    assert db.jobs[0].audiobook_id == db.audiobooks[0].id
    assert db.jobs[0].state == "queued"
    assert db.commits == 1
    assert db.rollbacks == 0
