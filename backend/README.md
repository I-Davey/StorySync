# StorySync Backend

## Phase 3 status
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

## Run
```bash
pip install -e .[dev]
uvicorn app.main:app --app-dir src --host 0.0.0.0 --port 8000
```

Environment variables are documented in `.env.example`.
