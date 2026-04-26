from __future__ import annotations

import os
from pathlib import Path

import pytest

# Ensure app settings can be imported during test collection.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/storysync_test")
os.environ.setdefault("AUDIO_STORAGE_ROOT", "/tmp/storysync-test-audio")
os.environ.setdefault("PROCESSOR_ENABLED", "false")


@pytest.fixture
def generated_m4b_payload() -> bytes:
    """Build a small deterministic `.m4b`-named payload at runtime for upload tests."""
    header = b"\x00\x00\x00\x20ftypM4B \x00\x00\x00\x00M4B isommp42"
    body = (b"storysync-runtime-fixture-" * 128)[:4096]
    return header + body


@pytest.fixture
def generated_m4b_file(tmp_path: Path, generated_m4b_payload: bytes) -> Path:
    file_path = tmp_path / "fixture.m4b"
    file_path.write_bytes(generated_m4b_payload)
    return file_path
