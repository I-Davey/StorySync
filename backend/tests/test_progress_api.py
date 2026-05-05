from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models import Audiobook, Base, User, UserAudiobookProgress


def _user(email: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        display_name=email.split("@")[0],
        password_hash="test-only",
        is_admin=False,
        is_active=True,
    )


def _audiobook(
    *,
    original_filename: str = "book.m4b",
    title: str = "Book",
    duration: int | None = 3600,
) -> Audiobook:
    return Audiobook(
        id=uuid.uuid4(),
        original_filename=original_filename,
        stored_path=f"/private/storage/{uuid.uuid4()}.m4b",
        file_size_bytes=12345,
        checksum_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        metadata_title=title,
        metadata_duration_seconds=duration,
        created_at=datetime.now(UTC),
    )


def _client_for(session: Session, user: User) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def _session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()


def test_put_get_and_delete_progress_for_current_user_only(monkeypatch) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.bootstrap_first_admin", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    session = _session()
    first_user = _user("first@example.com")
    second_user = _user("second@example.com")
    book = _audiobook(title="Shared Global Book")
    session.add_all([first_user, second_user, book])
    session.commit()

    try:
        with _client_for(session, first_user) as client:
            created = client.put(
                f"/audiobooks/{book.id}/progress",
                json={"position_seconds": 120, "duration_seconds": 3600},
            )
            fetched = client.get(f"/audiobooks/{book.id}/progress")

        with _client_for(session, second_user) as client:
            missing_for_second = client.get(f"/audiobooks/{book.id}/progress")
            second_created = client.put(
                f"/audiobooks/{book.id}/progress",
                json={"position_seconds": 999, "duration_seconds": 3600},
            )
            second_deleted = client.delete(f"/audiobooks/{book.id}/progress")
            second_deleted_again = client.delete(f"/audiobooks/{book.id}/progress")

        with _client_for(session, first_user) as client:
            still_first = client.get(f"/audiobooks/{book.id}/progress")
    finally:
        _clear_overrides()
        session.close()

    assert created.status_code == 200
    created_body = created.json()
    assert created_body["user_id"] == str(first_user.id)
    assert created_body["audiobook_id"] == str(book.id)
    assert created_body["position_seconds"] == 120
    assert created_body["duration_seconds"] == 3600
    assert created_body["is_completed"] is False
    assert created_body["started_at"]
    assert created_body["last_played_at"]
    assert created_body["completed_at"] is None
    assert created_body["audiobook"] == {
        "id": str(book.id),
        "title": "Shared Global Book",
        "author": None,
        "duration_seconds": 3600,
    }
    assert "password_hash" not in created.text
    assert "stored_path" not in created.text
    assert "/private/storage" not in created.text

    assert fetched.status_code == 200
    assert fetched.json()["id"] == created_body["id"]
    assert missing_for_second.status_code == 404
    assert second_created.status_code == 200
    assert second_created.json()["user_id"] == str(second_user.id)
    assert second_deleted.status_code == 204
    assert second_deleted_again.status_code == 204
    assert still_first.status_code == 200
    assert still_first.json()["position_seconds"] == 120


def test_put_progress_updates_timestamps_and_completion_state(monkeypatch) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.bootstrap_first_admin", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    session = _session()
    user = _user("listener@example.com")
    book = _audiobook()
    session.add_all([user, book])
    session.commit()

    try:
        with _client_for(session, user) as client:
            created = client.put(f"/audiobooks/{book.id}/progress", json={"position_seconds": 10})
            completed = client.put(
                f"/audiobooks/{book.id}/progress",
                json={"position_seconds": 3600, "duration_seconds": 3600, "is_completed": True},
            )
            reopened = client.put(
                f"/audiobooks/{book.id}/progress",
                json={"position_seconds": 1800, "duration_seconds": 3600, "is_completed": False},
            )
    finally:
        _clear_overrides()
        session.close()

    assert created.status_code == 200
    assert completed.status_code == 200
    assert reopened.status_code == 200
    assert completed.json()["id"] == created.json()["id"]
    assert completed.json()["started_at"] == created.json()["started_at"]
    assert completed.json()["last_played_at"] >= created.json()["last_played_at"]
    assert completed.json()["is_completed"] is True
    assert completed.json()["completed_at"] is not None
    assert reopened.json()["id"] == created.json()["id"]
    assert reopened.json()["started_at"] == created.json()["started_at"]
    assert reopened.json()["is_completed"] is False
    assert reopened.json()["completed_at"] is None


def test_progress_lists_are_current_user_ordered_and_paginated(monkeypatch) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.bootstrap_first_admin", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    session = _session()
    user = _user("current@example.com")
    other = _user("other@example.com")
    old_book = _audiobook(original_filename="old.m4b", title="Old")
    new_book = _audiobook(original_filename="new.m4b", title="New")
    complete_book = _audiobook(original_filename="done.m4b", title="Done")
    other_book = _audiobook(original_filename="other.m4b", title="Other")
    now = datetime.now(UTC)
    session.add_all([user, other, old_book, new_book, complete_book, other_book])
    session.add_all(
        [
            UserAudiobookProgress(
                id=uuid.uuid4(),
                user_id=user.id,
                audiobook_id=old_book.id,
                position_seconds=50,
                completed=False,
                started_at=now - timedelta(days=4),
                last_played_at=now - timedelta(days=3),
            ),
            UserAudiobookProgress(
                id=uuid.uuid4(),
                user_id=user.id,
                audiobook_id=new_book.id,
                position_seconds=100,
                completed=False,
                started_at=now - timedelta(days=2),
                last_played_at=now - timedelta(days=1),
            ),
            UserAudiobookProgress(
                id=uuid.uuid4(),
                user_id=user.id,
                audiobook_id=complete_book.id,
                position_seconds=300,
                completed=True,
                completed_at=now,
                started_at=now - timedelta(days=1),
                last_played_at=now,
            ),
            UserAudiobookProgress(
                id=uuid.uuid4(),
                user_id=other.id,
                audiobook_id=other_book.id,
                position_seconds=999,
                completed=False,
                started_at=now,
                last_played_at=now + timedelta(days=1),
            ),
        ]
    )
    session.commit()

    try:
        with _client_for(session, user) as client:
            progress_page = client.get("/me/progress", params={"offset": 1, "limit": 2})
            continue_listening = client.get("/me/continue-listening")
    finally:
        _clear_overrides()
        session.close()

    assert progress_page.status_code == 200
    assert [item["audiobook"]["title"] for item in progress_page.json()["items"]] == ["New", "Old"]
    assert progress_page.json()["offset"] == 1
    assert progress_page.json()["limit"] == 2
    assert progress_page.json()["total"] == 3

    assert continue_listening.status_code == 200
    assert [item["audiobook"]["title"] for item in continue_listening.json()["items"]] == ["New", "Old"]
    assert all(item["is_completed"] is False for item in continue_listening.json()["items"])
    assert "Other" not in [item["audiobook"]["title"] for item in continue_listening.json()["items"]]


def test_progress_requires_auth_validates_payload_and_missing_audiobook(monkeypatch) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.bootstrap_first_admin", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    session = _session()
    user = _user("listener@example.com")
    session.add(user)
    session.commit()
    missing_book_id = uuid.uuid4()

    try:
        app.dependency_overrides[get_db] = lambda: session
        with TestClient(app) as client:
            unauthenticated = client.get("/me/progress")

        with _client_for(session, user) as client:
            missing = client.put(f"/audiobooks/{missing_book_id}/progress", json={"position_seconds": 0})
            bad_position = client.put(f"/audiobooks/{missing_book_id}/progress", json={"position_seconds": -1})
            bad_duration = client.put(
                f"/audiobooks/{missing_book_id}/progress",
                json={"position_seconds": 0, "duration_seconds": -1},
            )
    finally:
        _clear_overrides()
        session.close()

    assert unauthenticated.status_code == 401
    assert missing.status_code == 404
    assert bad_position.status_code == 422
    assert bad_duration.status_code == 422
