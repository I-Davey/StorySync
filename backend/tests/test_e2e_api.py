from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base


@pytest.fixture
def sqlite_session_factory(tmp_path: Path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_pg_advisory_lock(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        dbapi_connection.create_function("pg_advisory_xact_lock", 1, lambda _key: 1)

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def e2e_client(monkeypatch, tmp_path: Path, sqlite_session_factory):
    monkeypatch.setattr("app.main.initialize_schema", lambda: None)
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    monkeypatch.setattr("app.services.uploads.settings.audio_storage_root", str(tmp_path))

    def _get_db_override():
        db: Session = sqlite_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db_override
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_e2e_upload_then_fetch_job_and_audiobook(e2e_client: TestClient, generated_m4b_payload: bytes) -> None:
    upload_response = e2e_client.post(
        "/audiobooks/upload",
        files={"file": ("full-flow.m4b", BytesIO(generated_m4b_payload), "audio/x-m4b")},
    )
    assert upload_response.status_code == 201

    uploaded = upload_response.json()
    stored_path = Path(uploaded["stored_path"])
    assert stored_path.exists()
    assert stored_path.read_bytes() == generated_m4b_payload

    job_response = e2e_client.get(f"/jobs/{uploaded['job_id']}")
    assert job_response.status_code == 200
    assert job_response.json()["state"] == "queued"

    audiobook_response = e2e_client.get(f"/audiobooks/{uploaded['audiobook_id']}")
    assert audiobook_response.status_code == 200
    audiobook = audiobook_response.json()
    assert audiobook["original_filename"] == "full-flow.m4b"
    assert audiobook["job"]["id"] == uploaded["job_id"]
    assert audiobook["job"]["state"] == "queued"

    list_response = e2e_client.get("/audiobooks", params={"state": "queued", "page": 1, "page_size": 10})
    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["page"] == 1
    assert listed["page_size"] == 10
    assert len(listed["items"]) == 1
    assert listed["items"][0]["id"] == uploaded["audiobook_id"]


def test_e2e_duplicate_upload_returns_conflict(e2e_client: TestClient, generated_m4b_payload: bytes) -> None:
    first = e2e_client.post(
        "/audiobooks/upload",
        files={"file": ("dup-a.m4b", BytesIO(generated_m4b_payload), "audio/x-m4b")},
    )
    assert first.status_code == 201

    second = e2e_client.post(
        "/audiobooks/upload",
        files={"file": ("dup-b.m4b", BytesIO(generated_m4b_payload), "audio/x-m4b")},
    )
    assert second.status_code == 409
    assert "Duplicate upload detected" in second.json()["detail"]
