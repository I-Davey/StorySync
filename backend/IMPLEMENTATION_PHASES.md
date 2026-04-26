# StorySync Backend Implementation Phases

## Phase 1 (Current)
- Scaffold FastAPI backend in `backend/`.
- Add centralized settings for environment variables.
- Configure PostgreSQL engine/session wiring.
- Implement startup schema initialization with `CREATE TABLE IF NOT EXISTS` (no migrations framework).
- Create `app_meta`, `audiobooks`, and `processing_jobs` tables plus indexes.
- Add `/health` endpoint with DB connectivity check.

## Phase 2
- Implement `POST /audiobooks/upload` with `.m4b` validation.
- Stream file writes to `/data/audio`.
- Compute and persist SHA256 checksum.
- Enforce duplicate prevention via unique checksum handling.
- Create associated processing job with `received` -> `queued` state transition.

## Phase 3
- Implement queue lifecycle endpoints:
  - `GET /jobs/{job_id}`
  - `GET /audiobooks/{id}`
  - `GET /audiobooks` (pagination + state filters)
- Add deterministic queue-position assignment.

## Phase 4
- Implement background processor loop:
  - claim queued work
  - set `processing`
  - lease/heartbeat
  - complete as `processed` or `failed`
- Add restart-safe recovery for expired processing leases.

## Phase 5
- Implement M4B metadata extraction service.
- Persist extracted metadata (normalized fields + optional raw metadata payload).

## Phase 6
- Add comprehensive tests (unit + integration).
- Runtime-generate M4B fixtures in tests (no binary test assets committed).
- Add CI workflow for lint/test.
