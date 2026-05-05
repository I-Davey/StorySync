from __future__ import annotations

import uuid
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from app.services.covers import MAX_COVER_BYTES, replace_manual_cover

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff"
    b"\xff?\x00\x05\xfe\x02\xfeA\x90\xf4\xd9\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _upload(filename: str, payload: bytes, content_type: str) -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(payload), headers={"content-type": content_type})


def _audiobook() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), cover_path=None, cover_media_type=None)


def test_replace_manual_cover_rejects_invalid_image_bytes(tmp_path) -> None:
    db = MagicMock()
    audiobook = _audiobook()
    upload = _upload("cover.png", b"not really a png", "image/png")

    with patch("app.services.covers.settings") as mock_settings:
        mock_settings.audio_storage_root = str(tmp_path)
        with pytest.raises(HTTPException) as exc_info:
            replace_manual_cover(db, audiobook, upload)

    assert exc_info.value.status_code == 415
    assert not list((tmp_path / "covers").glob("*"))
    db.rollback.assert_called_once()


def test_replace_manual_cover_rejects_magic_type_mismatch(tmp_path) -> None:
    db = MagicMock()
    audiobook = _audiobook()
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"jpeg-ish"
    upload = _upload("cover.png", jpeg_bytes, "image/png")

    with patch("app.services.covers.settings") as mock_settings:
        mock_settings.audio_storage_root = str(tmp_path)
        with pytest.raises(HTTPException) as exc_info:
            replace_manual_cover(db, audiobook, upload)

    assert exc_info.value.status_code == 415
    assert not list((tmp_path / "covers").glob("*"))


def test_replace_manual_cover_rejects_extension_mismatch(tmp_path) -> None:
    db = MagicMock()
    audiobook = _audiobook()
    upload = _upload("cover.jpg", TINY_PNG, "image/png")

    with patch("app.services.covers.settings") as mock_settings:
        mock_settings.audio_storage_root = str(tmp_path)
        with pytest.raises(HTTPException) as exc_info:
            replace_manual_cover(db, audiobook, upload)

    assert exc_info.value.status_code == 415


def test_replace_manual_cover_rejects_too_large_upload_while_streaming(tmp_path) -> None:
    db = MagicMock()
    audiobook = _audiobook()
    payload = b"\x89PNG\r\n\x1a\n" + (b"x" * MAX_COVER_BYTES)
    upload = _upload("cover.png", payload, "image/png")

    with patch("app.services.covers.settings") as mock_settings:
        mock_settings.audio_storage_root = str(tmp_path)
        with pytest.raises(HTTPException) as exc_info:
            replace_manual_cover(db, audiobook, upload)

    assert exc_info.value.status_code == 413
    assert not list((tmp_path / "covers").glob("*"))
    db.rollback.assert_called_once()


def test_replace_manual_cover_accepts_valid_png(tmp_path) -> None:
    db = MagicMock()
    audiobook = _audiobook()
    upload = _upload("cover.png", TINY_PNG, "image/png")

    with patch("app.services.covers.settings") as mock_settings:
        mock_settings.audio_storage_root = str(tmp_path)
        result = replace_manual_cover(db, audiobook, upload)

    assert result.cover_media_type == "image/png"
    cover_path = tmp_path / "covers" / f"{audiobook.id}.png"
    assert cover_path.read_bytes() == TINY_PNG
    db.commit.assert_called_once()
