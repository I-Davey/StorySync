from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

from app.config import Settings
from app.services.auth import (
    bootstrap_first_admin,
    create_access_token,
    decode_access_token,
    hash_password,
    normalize_email,
    verify_password,
)


def test_normalize_email_strips_and_lowercases() -> None:
    assert normalize_email("  Admin@MAIL.COM  ") == "admin@mail.com"


def test_password_hash_round_trip_and_wrong_password_rejected() -> None:
    encoded = hash_password("test-only-password")

    assert encoded != "test-only-password"
    assert verify_password("test-only-password", encoded)
    assert not verify_password("wrong-password", encoded)


def test_access_token_round_trip_and_tampering_rejected() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://test:test@localhost/test",
        auth_token_secret="test-only-secret",
        auth_token_ttl_seconds=60,
    )

    token = create_access_token("user-123", settings=settings)
    payload = decode_access_token(token, settings=settings)

    assert payload["sub"] == "user-123"
    assert payload["exp"] > int(dt.datetime.now(dt.UTC).timestamp())
    assert decode_access_token(token + "tampered", settings=settings) is None


def test_expired_access_token_rejected() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://test:test@localhost/test",
        auth_token_secret="test-only-secret",
        auth_token_ttl_seconds=-1,
    )

    token = create_access_token("user-123", settings=settings)

    assert decode_access_token(token, settings=settings) is None


def test_bootstrap_first_admin_creates_admin_when_no_users_and_password_present() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://test:test@localhost/test",
        storysync_admin_email="Admin@MAIL.COM",
        storysync_admin_password="test-only-bootstrap-password",
    )
    db = MagicMock()
    db.query.return_value.count.return_value = 0

    created = bootstrap_first_admin(db, settings=settings)

    assert created is not None
    assert created.email == "admin@mail.com"
    assert created.is_admin is True
    assert created.is_active is True
    assert verify_password("test-only-bootstrap-password", created.password_hash)
    db.add.assert_called_once_with(created)
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(created)


def test_bootstrap_first_admin_noops_when_users_exist_or_password_missing() -> None:
    settings = Settings(database_url="postgresql+psycopg://test:test@localhost/test", storysync_admin_password="")
    db = MagicMock()
    db.query.return_value.count.return_value = 0

    assert bootstrap_first_admin(db, settings=settings) is None
    db.add.assert_not_called()

    settings_with_password = Settings(
        database_url="postgresql+psycopg://test:test@localhost/test",
        storysync_admin_password="test-only-bootstrap-password",
    )
    existing_db = MagicMock()
    existing_db.query.return_value.count.return_value = 1

    assert bootstrap_first_admin(existing_db, settings=settings_with_password) is None
    existing_db.add.assert_not_called()
