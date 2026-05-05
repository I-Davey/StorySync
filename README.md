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
