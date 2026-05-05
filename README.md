# StorySync

Audiobook backend service.

## Run locally with Docker

Prerequisites:

- Docker Engine
- Docker Compose v2

Start PostgreSQL + backend:

```bash
docker compose up --build
```

Backend URL:

- `http://localhost:8000`
- health: `http://localhost:8000/health`

Useful commands:

```bash
# Run in background
docker compose up --build -d

# View logs
docker compose logs -f backend

# Stop containers
docker compose down

# Stop and delete local DB/audio volumes
docker compose down -v
```

The compose stack uses:

- PostgreSQL 16 Alpine
- FastAPI backend on port `8000`
- persistent Docker volumes for Postgres data and uploaded audio

## Current API surface

Core endpoints:

- `GET /health`
- `POST /audiobooks` — upload/create audiobook
- `POST /audiobooks/upload` — compatibility alias for upload
- `GET /audiobooks`
- `GET /audiobooks/{audiobook_id}`
- `PATCH /audiobooks/{audiobook_id}`
- `DELETE /audiobooks/{audiobook_id}`
- `POST /audiobooks/{audiobook_id}/reprocess`
- `GET /audiobooks/{audiobook_id}/download`
- `POST /audiobooks/{audiobook_id}/cover`
- `GET /audiobooks/{audiobook_id}/cover`
- `DELETE /audiobooks/{audiobook_id}/cover`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `POST /jobs/{job_id}/cancel`
- `POST /jobs/{job_id}/retry`

Not implemented yet:

- streaming/range playback endpoints
- progress tracking endpoints
