# StorySync Backend

## Phase 1 status
This directory contains the initial backend scaffold with:
- FastAPI application bootstrap
- PostgreSQL connection wiring
- startup-time schema initialization (no Alembic)
- health endpoint

## Run
```bash
pip install -e .[dev]
uvicorn app.main:app --app-dir src --host 0.0.0.0 --port 8000
```

Environment variables are documented in `.env.example`.
