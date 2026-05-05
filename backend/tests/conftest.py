from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Callable

import pytest

# Ensure app settings can be imported during test collection.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/storysync_test")
os.environ.setdefault("AUDIO_STORAGE_ROOT", "/tmp/storysync-test-audio")
os.environ.setdefault("PROCESSOR_ENABLED", "false")

from app.dependencies import get_current_user, require_admin  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402


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


def make_test_user(*, is_admin: bool = False, is_active: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        email="admin@example.com" if is_admin else "user@example.com",
        display_name="Admin" if is_admin else "User",
        password_hash="test-only",
        is_admin=is_admin,
        is_active=is_active,
    )


@pytest.fixture
def override_auth() -> Callable[..., User]:
    def apply(*, is_admin: bool = False, is_active: bool = True) -> User:
        user = make_test_user(is_admin=is_admin, is_active=is_active)
        app.dependency_overrides[get_current_user] = lambda: user
        if is_admin:
            app.dependency_overrides[require_admin] = lambda: user
        return user

    yield apply

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(require_admin, None)
