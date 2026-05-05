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

## Authentication setup

StorySync is designed as a self-hosted global-library app:

- Audiobooks are global, not user-owned.
- Users cannot self-register.
- Admin users create/manage users.
- Normal users can browse/download the global library and manage their own progress.

The first admin is bootstrapped only when the users table is empty and `STORYSYNC_ADMIN_PASSWORD` is set.

Default admin email:

```text
admin@mail.com
```

Set the password at runtime, for example:

```bash
STORYSYNC_ADMIN_PASSWORD='<set-a-local-password>' docker compose up --build
```

Optional env vars:

- `STORYSYNC_ADMIN_EMAIL` — defaults to `admin@mail.com`
- `STORYSYNC_ADMIN_PASSWORD` — required for first-admin bootstrap
- `AUTH_TOKEN_SECRET` — set this for stable tokens across restarts; if omitted, the backend generates an ephemeral process-local secret

## Current API surface

Public endpoints:

- `GET /health`
- `POST /auth/login`

Authenticated user endpoints:

- `GET /auth/me`
- `GET /audiobooks`
- `GET /audiobooks/{audiobook_id}`
- `GET /audiobooks/{audiobook_id}/download`
- `GET /audiobooks/{audiobook_id}/cover`
- `GET /me/progress`
- `GET /me/continue-listening`
- `GET /audiobooks/{audiobook_id}/progress`
- `PUT /audiobooks/{audiobook_id}/progress`
- `DELETE /audiobooks/{audiobook_id}/progress`

Admin-only endpoints:

- `POST /audiobooks` — upload/create audiobook
- `POST /audiobooks/upload` — compatibility alias for upload
- `PATCH /audiobooks/{audiobook_id}`
- `DELETE /audiobooks/{audiobook_id}`
- `POST /audiobooks/{audiobook_id}/reprocess`
- `POST /audiobooks/{audiobook_id}/cover`
- `DELETE /audiobooks/{audiobook_id}/cover`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `POST /jobs/{job_id}/cancel`
- `POST /jobs/{job_id}/retry`
- `POST /admin/users`
- `GET /admin/users`
- `GET /admin/users/{user_id}`
- `PATCH /admin/users/{user_id}`
- `POST /admin/users/{user_id}/deactivate`
- `POST /admin/users/{user_id}/reset-password`

Not implemented yet:

- streaming/range playback endpoints
- bookmarks/notes
