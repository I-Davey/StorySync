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

E2E_ADMIN_EMAIL = "admin@mail.com"
E2E_ADMIN_PASSWORD = "e2e-admin-password"


def _authenticate_admin(client: httpx.Client, base_url: str) -> None:
    response = client.post(
        f"{base_url}/auth/login",
        json={"email": E2E_ADMIN_EMAIL, "password": E2E_ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    client.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})


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
    env["STORYSYNC_ADMIN_EMAIL"] = E2E_ADMIN_EMAIL
    env["STORYSYNC_ADMIN_PASSWORD"] = E2E_ADMIN_PASSWORD

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
        _authenticate_admin(client, base_url)
        upload_response = client.post(
            f"{base_url}/audiobooks",
            files={"file": ("live-flow.m4b", BytesIO(generated_m4b_payload), "audio/x-m4b")},
        )
        assert upload_response.status_code == 201

        uploaded = upload_response.json()
        assert upload_response.headers["location"] == f"/audiobooks/{uploaded['audiobook_id']}"
        assert uploaded["download_url"] == f"/audiobooks/{uploaded['audiobook_id']}/download"
        assert "stored_path" not in uploaded
        assert len(list(audio_dir.glob("*.m4b"))) == 1

        job_response = client.get(f"{base_url}/jobs/{uploaded['job_id']}")
        assert job_response.status_code == 200
        assert job_response.json()["state"] == "queued"

        audiobook_response = client.get(f"{base_url}/audiobooks/{uploaded['audiobook_id']}")
        assert audiobook_response.status_code == 200
        audiobook = audiobook_response.json()
        assert audiobook["original_filename"] == "live-flow.m4b"
        assert audiobook["download_url"] == f"/audiobooks/{uploaded['audiobook_id']}/download"
        assert audiobook["cover"] is None
        assert "stored_path" not in audiobook
        assert "cover_path" not in audiobook
        assert "metadata_title" not in audiobook
        assert audiobook["metadata"]["title"] is None
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
        _authenticate_admin(client, base_url)
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


def test_e2e_live_patch_reprocess_download_and_delete_audiobook(
    live_backend_server,
    generated_m4b_payload: bytes,
) -> None:
    base_url, _audio_dir = live_backend_server

    with httpx.Client(timeout=10.0) as client:
        _authenticate_admin(client, base_url)
        upload_response = client.post(
            f"{base_url}/audiobooks/upload",
            files={"file": ("lifecycle-flow.m4b", BytesIO(generated_m4b_payload), "audio/x-m4b")},
        )
        assert upload_response.status_code == 201
        uploaded = upload_response.json()
        audiobook_id = uploaded["audiobook_id"]
        assert "stored_path" not in uploaded
        assert len(list(Path(_audio_dir).glob("*.m4b"))) == 1

        patch_response = client.patch(
            f"{base_url}/audiobooks/{audiobook_id}",
            json={
                "metadata_title": "Manual Title",
                "metadata_artist": "Manual Artist",
                "metadata_year": 2026,
            },
        )
        assert patch_response.status_code == 200
        patched = patch_response.json()
        assert patched["metadata"]["title"] == "Manual Title"
        assert patched["metadata"]["artist"] == "Manual Artist"
        assert patched["metadata"]["year"] == 2026
        assert patched["metadata"]["album"] is None
        assert "stored_path" not in patched
        assert "cover_path" not in patched
        assert patched["job"]["id"] == uploaded["job_id"]

        download_response = client.get(f"{base_url}/audiobooks/{audiobook_id}/download")
        assert download_response.status_code == 200
        assert download_response.content == generated_m4b_payload
        assert download_response.headers["content-type"].startswith("audio/mp4")
        assert "attachment" in download_response.headers["content-disposition"]
        assert "lifecycle-flow.m4b" in download_response.headers["content-disposition"]

        reprocess_queued_response = client.post(f"{base_url}/audiobooks/{audiobook_id}/reprocess")
        assert reprocess_queued_response.status_code == 409

        cancel_response = client.post(f"{base_url}/jobs/{uploaded['job_id']}/cancel")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["state"] == "cancelled"

        reprocess_response = client.post(f"{base_url}/audiobooks/{audiobook_id}/reprocess")
        assert reprocess_response.status_code == 200
        reprocessed_job = reprocess_response.json()
        assert reprocessed_job["id"] == uploaded["job_id"]
        assert reprocessed_job["state"] == "queued"
        assert "queue_position" not in reprocessed_job
        assert reprocessed_job["worker_id"] is None
        assert reprocessed_job["lease_expires_at"] is None
        assert reprocessed_job["last_error"] is None

        cleared_response = client.get(f"{base_url}/audiobooks/{audiobook_id}")
        assert cleared_response.status_code == 200
        cleared = cleared_response.json()
        assert cleared["metadata"]["title"] is None
        assert cleared["metadata"]["artist"] is None
        assert cleared["metadata"]["year"] is None

        delete_response = client.delete(f"{base_url}/audiobooks/{audiobook_id}")
        assert delete_response.status_code == 204
        assert list(Path(_audio_dir).glob("*.m4b")) == []

        missing_response = client.get(f"{base_url}/audiobooks/{audiobook_id}")
        assert missing_response.status_code == 404


def test_e2e_live_lifecycle_missing_audiobook_returns_404(live_backend_server) -> None:
    base_url, _audio_dir = live_backend_server
    missing_id = "00000000-0000-0000-0000-000000000404"

    with httpx.Client(timeout=10.0) as client:
        _authenticate_admin(client, base_url)
        patch_response = client.patch(
            f"{base_url}/audiobooks/{missing_id}",
            json={"metadata_title": "Nope"},
        )
        assert patch_response.status_code == 404

        reprocess_response = client.post(f"{base_url}/audiobooks/{missing_id}/reprocess")
        assert reprocess_response.status_code == 404

        download_response = client.get(f"{base_url}/audiobooks/{missing_id}/download")
        assert download_response.status_code == 404

        delete_response = client.delete(f"{base_url}/audiobooks/{missing_id}")
        assert delete_response.status_code == 404


def test_e2e_live_job_admin_list_cancel_retry_errors(
    live_backend_server,
    postgres_ready: str,
    generated_m4b_payload: bytes,
) -> None:
    base_url, _audio_dir = live_backend_server
    missing_id = "00000000-0000-0000-0000-000000000404"

    with httpx.Client(timeout=10.0) as client:
        _authenticate_admin(client, base_url)
        upload_response = client.post(
            f"{base_url}/audiobooks/upload",
            files={"file": ("job-admin-flow.m4b", BytesIO(generated_m4b_payload), "audio/x-m4b")},
        )
        assert upload_response.status_code == 201
        uploaded = upload_response.json()
        job_id = uploaded["job_id"]

        list_queued_response = client.get(f"{base_url}/jobs", params={"state": "queued", "page": 1, "page_size": 10})
        assert list_queued_response.status_code == 200
        queued_list = list_queued_response.json()
        assert queued_list["page"] == 1
        assert queued_list["page_size"] == 10
        assert [item["id"] for item in queued_list["items"]] == [job_id]

        retry_queued_response = client.post(f"{base_url}/jobs/{job_id}/retry")
        assert retry_queued_response.status_code == 409

        cancel_response = client.post(f"{base_url}/jobs/{job_id}/cancel")
        assert cancel_response.status_code == 200
        cancelled = cancel_response.json()
        assert cancelled["state"] == "cancelled"
        assert "queue_position" not in cancelled
        assert cancelled["worker_id"] is None
        assert cancelled["lease_expires_at"] is None

        list_cancelled_response = client.get(f"{base_url}/jobs", params={"state": "cancelled"})
        assert list_cancelled_response.status_code == 200
        cancelled_list = list_cancelled_response.json()
        assert [item["id"] for item in cancelled_list["items"]] == [job_id]

        retry_response = client.post(f"{base_url}/jobs/{job_id}/retry")
        assert retry_response.status_code == 200
        retried = retry_response.json()
        assert retried["state"] == "queued"
        assert "queue_position" not in retried
        assert retried["last_error"] is None
        assert retried["worker_id"] is None
        assert retried["lease_expires_at"] is None

        retry_missing_response = client.post(f"{base_url}/jobs/{missing_id}/retry")
        assert retry_missing_response.status_code == 404
        cancel_missing_response = client.post(f"{base_url}/jobs/{missing_id}/cancel")
        assert cancel_missing_response.status_code == 404

        with psycopg.connect(postgres_ready.replace("postgresql+psycopg://", "postgresql://")) as conn:
            conn.execute(
                "UPDATE processing_jobs SET state = 'processed' WHERE id = %s",
                (job_id,),
            )
            conn.commit()

        cancel_processed_response = client.post(f"{base_url}/jobs/{job_id}/cancel")
        assert cancel_processed_response.status_code == 409


def test_e2e_live_cover_upload_get_and_delete(
    live_backend_server,
    generated_m4b_payload: bytes,
) -> None:
    base_url, audio_dir = live_backend_server
    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff"
        b"\xff?\x00\x05\xfe\x02\xfeA\x90\xf4\xd9\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    with httpx.Client(timeout=10.0) as client:
        _authenticate_admin(client, base_url)
        upload_response = client.post(
            f"{base_url}/audiobooks/upload",
            files={"file": ("cover-flow.m4b", BytesIO(generated_m4b_payload), "audio/x-m4b")},
        )
        assert upload_response.status_code == 201
        uploaded = upload_response.json()
        audiobook_id = uploaded["audiobook_id"]

        cover_response = client.post(
            f"{base_url}/audiobooks/{audiobook_id}/cover",
            files={"file": ("cover.png", BytesIO(tiny_png), "image/png")},
        )
        assert cover_response.status_code == 200
        cover_payload = cover_response.json()
        assert cover_payload["id"] == audiobook_id
        assert cover_payload["cover"] == {
            "url": f"/audiobooks/{audiobook_id}/cover",
            "media_type": "image/png",
        }
        assert "cover_path" not in cover_payload

        cover_path = audio_dir / "covers" / f"{audiobook_id}.png"
        assert cover_path.exists()
        assert cover_path.read_bytes() == tiny_png

        get_cover_response = client.get(f"{base_url}/audiobooks/{audiobook_id}/cover")
        assert get_cover_response.status_code == 200
        assert get_cover_response.headers["content-type"].startswith("image/png")
        assert get_cover_response.content == tiny_png

        delete_cover_response = client.delete(f"{base_url}/audiobooks/{audiobook_id}/cover")
        assert delete_cover_response.status_code == 204
        assert not cover_path.exists()

        missing_cover_response = client.get(f"{base_url}/audiobooks/{audiobook_id}/cover")
        assert missing_cover_response.status_code == 404


def test_e2e_live_cover_errors(
    live_backend_server,
    generated_m4b_payload: bytes,
) -> None:
    base_url, _audio_dir = live_backend_server
    missing_id = "00000000-0000-0000-0000-000000000404"

    with httpx.Client(timeout=10.0) as client:
        _authenticate_admin(client, base_url)
        missing_upload_response = client.post(
            f"{base_url}/audiobooks/{missing_id}/cover",
            files={"file": ("cover.png", BytesIO(b"png"), "image/png")},
        )
        assert missing_upload_response.status_code == 404

        upload_response = client.post(
            f"{base_url}/audiobooks/upload",
            files={"file": ("cover-errors.m4b", BytesIO(generated_m4b_payload), "audio/x-m4b")},
        )
        assert upload_response.status_code == 201
        audiobook_id = upload_response.json()["audiobook_id"]

        missing_cover_response = client.get(f"{base_url}/audiobooks/{audiobook_id}/cover")
        assert missing_cover_response.status_code == 404

        unsupported_response = client.post(
            f"{base_url}/audiobooks/{audiobook_id}/cover",
            files={"file": ("not-image.txt", BytesIO(b"not an image"), "text/plain")},
        )
        assert unsupported_response.status_code == 415

        missing_get_response = client.get(f"{base_url}/audiobooks/{missing_id}/cover")
        assert missing_get_response.status_code == 404

        missing_delete_response = client.delete(f"{base_url}/audiobooks/{missing_id}/cover")
        assert missing_delete_response.status_code == 404
