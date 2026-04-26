from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path

import httpx
import psycopg
import pytest
from sqlalchemy import create_engine

from app.models import Base


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_postgres(database_url: str, timeout_seconds: float = 30.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        engine = create_engine(database_url, pool_pre_ping=True)
        try:
            with engine.connect():
                return True
        except Exception:
            time.sleep(0.5)
        finally:
            engine.dispose()
    return False


@pytest.fixture(scope="session")
def postgres_database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/storysync_test",
    )


@pytest.fixture(scope="session")
def postgres_ready(postgres_database_url: str) -> str:
    if not _wait_for_postgres(postgres_database_url):
        pytest.skip("PostgreSQL is required for live e2e tests.")
    return postgres_database_url


@pytest.fixture
def reset_postgres_schema(postgres_ready: str) -> None:
    engine = create_engine(postgres_ready, pool_pre_ping=True)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def live_backend_server(postgres_ready: str, reset_postgres_schema, tmp_path: Path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env["DATABASE_URL"] = postgres_ready
    env["AUDIO_STORAGE_ROOT"] = str(audio_dir)
    env["PROCESSOR_ENABLED"] = "false"

    process = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--app-dir",
            "src",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        with httpx.Client(timeout=1.0) as client:
            for _ in range(60):
                if process.poll() is not None:
                    stderr_output = process.stderr.read() if process.stderr else ""
                    raise RuntimeError(f"Backend failed to start. stderr:\n{stderr_output}")
                try:
                    health = client.get(f"{base_url}/health")
                    if health.status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.25)
            else:
                raise RuntimeError("Timed out waiting for backend /health endpoint.")

        yield base_url, audio_dir
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_e2e_live_upload_then_fetch_job_and_audiobook(
    live_backend_server,
    generated_m4b_payload: bytes,
) -> None:
    base_url, audio_dir = live_backend_server

    with httpx.Client(timeout=10.0) as client:
        upload_response = client.post(
            f"{base_url}/audiobooks/upload",
            files={"file": ("live-flow.m4b", BytesIO(generated_m4b_payload), "audio/x-m4b")},
        )
        assert upload_response.status_code == 201

        uploaded = upload_response.json()
        stored_path = Path(uploaded["stored_path"])
        assert stored_path.exists()
        assert stored_path.parent == audio_dir
        assert stored_path.read_bytes() == generated_m4b_payload

        job_response = client.get(f"{base_url}/jobs/{uploaded['job_id']}")
        assert job_response.status_code == 200
        assert job_response.json()["state"] == "queued"

        audiobook_response = client.get(f"{base_url}/audiobooks/{uploaded['audiobook_id']}")
        assert audiobook_response.status_code == 200
        audiobook = audiobook_response.json()
        assert audiobook["original_filename"] == "live-flow.m4b"
        assert audiobook["job"]["id"] == uploaded["job_id"]
        assert audiobook["job"]["state"] == "queued"

        list_response = client.get(
            f"{base_url}/audiobooks",
            params={"state": "queued", "page": 1, "page_size": 10},
        )
        assert list_response.status_code == 200
        listed = list_response.json()
        assert listed["page"] == 1
        assert listed["page_size"] == 10
        assert len(listed["items"]) == 1
        assert listed["items"][0]["id"] == uploaded["audiobook_id"]


def test_e2e_live_duplicate_upload_returns_conflict(
    live_backend_server,
    generated_m4b_payload: bytes,
) -> None:
    base_url, _audio_dir = live_backend_server

    with httpx.Client(timeout=10.0) as client:
        first = client.post(
            f"{base_url}/audiobooks/upload",
            files={"file": ("dup-a.m4b", BytesIO(generated_m4b_payload), "audio/x-m4b")},
        )
        assert first.status_code == 201

        second = client.post(
            f"{base_url}/audiobooks/upload",
            files={"file": ("dup-b.m4b", BytesIO(generated_m4b_payload), "audio/x-m4b")},
        )
        assert second.status_code == 409
        assert "Duplicate upload detected" in second.json()["detail"]
