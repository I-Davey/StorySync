from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services.audiobooks import delete_audiobook


class _DummyDB:
    def __init__(self) -> None:
        self.deleted = None
        self.committed = False

    def delete(self, obj) -> None:
        self.deleted = obj

    def commit(self) -> None:
        self.committed = True


def test_delete_audiobook_deletes_db_row_then_files(tmp_path) -> None:
    audio_path = tmp_path / "book.m4b"
    cover_path = tmp_path / "cover.png"
    audio_path.write_bytes(b"audio")
    cover_path.write_bytes(b"cover")
    audiobook = SimpleNamespace(
        id=uuid.uuid4(),
        stored_path=str(audio_path),
        cover_path=str(cover_path),
    )
    db = _DummyDB()

    delete_audiobook(db, audiobook)

    assert db.deleted is audiobook
    assert db.committed
    assert not audio_path.exists()
    assert not cover_path.exists()
