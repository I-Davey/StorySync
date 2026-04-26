from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError

from app.services.uploads import _is_checksum_unique_violation, _stream_to_temp, _validate_m4b_filename


class _DummyDiag:
    def __init__(self, constraint_name: str | None = None, message_detail: str | None = None) -> None:
        self.constraint_name = constraint_name
        self.message_detail = message_detail


class _DummyOrig:
    def __init__(
        self,
        *,
        diag: _DummyDiag | None = None,
        sqlstate: str | None = None,
        pgcode: str | None = None,
        text: str = "",
    ) -> None:
        self.diag = diag
        self.sqlstate = sqlstate
        self.pgcode = pgcode
        self._text = text

    def __str__(self) -> str:
        return self._text


def _upload(filename: str, payload: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(payload))


def _integrity_error(orig: object) -> IntegrityError:
    return IntegrityError("insert", {}, orig)


def test_validate_m4b_filename_accepts_valid_extension() -> None:
    assert _validate_m4b_filename("book.M4B") == "book.M4B"


def test_validate_m4b_filename_rejects_other_extensions() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_m4b_filename("book.mp3")

    assert exc.value.status_code == 415


def test_stream_to_temp_writes_and_hashes_content(tmp_path: Path) -> None:
    payload = b"abc123" * 1024
    upload = _upload("book.m4b", payload)

    temp_path, total_bytes, checksum = _stream_to_temp(upload, tmp_path)

    assert temp_path.exists()
    assert temp_path.read_bytes() == payload
    assert total_bytes == len(payload)
    assert len(checksum) == 64


def test_checksum_violation_detected_by_constraint_name() -> None:
    err = _integrity_error(_DummyOrig(diag=_DummyDiag(constraint_name="audiobooks_checksum_sha256_key")))

    assert _is_checksum_unique_violation(err)


def test_checksum_violation_detected_by_sqlstate_and_detail() -> None:
    err = _integrity_error(
        _DummyOrig(
            diag=_DummyDiag(message_detail="Key (checksum_sha256)=(abc) already exists."),
            sqlstate="23505",
        )
    )

    assert _is_checksum_unique_violation(err)


def test_non_checksum_unique_violation_returns_false() -> None:
    err = _integrity_error(
        _DummyOrig(
            diag=_DummyDiag(constraint_name="audiobooks_stored_path_key"),
            pgcode="23505",
            text="duplicate key value violates unique constraint",
        )
    )

    assert not _is_checksum_unique_violation(err)
