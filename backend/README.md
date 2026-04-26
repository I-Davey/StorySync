# StorySync Backend

## Phase 6 status
This directory now includes:
- FastAPI application bootstrap
- PostgreSQL connection wiring
- startup-time schema initialization (no Alembic)
- health endpoint
- `POST /audiobooks/upload` endpoint for `.m4b` intake
- streamed storage writes to `audio_storage_root`
- SHA256 checksum persistence + duplicate conflict handling
- processing job creation with `received` -> `queued` transition
- deterministic queue-position assignment when jobs are queued
- `GET /jobs/{job_id}` queue lifecycle lookup
- `GET /audiobooks/{id}` audiobook + current job lookup
- `GET /audiobooks` with pagination and optional `state` filter
- background processing loop for queued jobs
- lease/heartbeat support with restart-safe lease expiration recovery
- processing completion transitions to `processed` or `failed`/re-queued
- M4B metadata extraction during processing (`title`, `album`, `artist`, `genre`, `duration`, `track`, `year`)
- extracted metadata persisted in normalized audiobook columns plus `metadata_raw` payload
- comprehensive unit + integration-oriented backend tests
- runtime-generated `.m4b` fixtures in tests (no committed binary test assets)
- GitHub Actions CI workflow for compile-check + pytest

## Run
```bash
pip install -e .[dev]
uvicorn app.main:app --app-dir src --host 0.0.0.0 --port 8000
```

Environment variables are documented in `.env.example`.
