# StorySync MVP Refactor Execution Plan

Date: 2026-05-05
Branch: `chore/docker-local-setup`

## User direction

- Remove `queue_position`.
- Do the refactor.
- Keep code neat, simple, and organised.
- Do not add extra product features.
- Use subagents.
- Build tests and verify locally before reporting back.

## Non-goals

- No playback streaming/range support.
- No listening progress.
- No auth/multi-user model.
- No frontend.
- No large abstraction framework.

## Target architecture

```text
backend/src/app/
  api/
    audiobooks.py      # thin HTTP endpoints
    jobs.py            # thin HTTP endpoints
    health.py
  schemas.py           # public API request/response models + enums
  services/
    audiobooks.py      # audiobook CRUD/reprocess/download orchestration
    jobs.py            # state transitions and queries
    storage.py         # common path/temp/delete helpers
    uploads.py         # upload ingestion
    covers.py          # cover validation/storage/extraction
    processor.py       # background worker, using job service/state enum
```

## Task 1 — Contract/schema refactor

Goals:

- Create `app/schemas.py`.
- Move duplicate response models out of route modules.
- Add `JobState` enum.
- Use typed state filters.
- Hide internal `stored_path` and `cover_path` from public responses.
- Add `download_url` and cover resource fields.
- Group metadata under `metadata`.
- Add canonical `POST /audiobooks` upload endpoint while keeping `/audiobooks/upload` as compatibility alias.

Tests first:

- API response does not include `stored_path` or `cover_path`.
- Audiobook response has `metadata`, `download_url`, and `cover` object.
- Invalid state filter returns `422`.
- `POST /audiobooks` creates upload and returns `Location` header.
- `/audiobooks/upload` still works.

## Task 2 — Remove queue_position and centralise jobs

Goals:

- Remove `queue_position` from public schemas and model usage.
- Replace FIFO queue ordering with `created_at ASC, id ASC`.
- Remove `services/queue.py` if no longer needed.
- Create/expand `services/jobs.py` for transitions:
  - create queued job
  - cancel
  - retry
  - reprocess
  - claim next job
  - recover expired leases
  - complete success/failure
- Use `JobState` enum throughout.
- Remove `received` state if it is still only transient and not externally observable; create upload jobs directly as `queued`.

Tests first:

- Upload creates a queued job without queue position.
- Job list responses omit queue position.
- Jobs are claimed FIFO by creation order.
- Retry/reprocess creates a new FIFO position by updated created/queued ordering policy or simply returns to queued without explicit position.
- Invalid state transitions return `409`.

## Task 3 — Service/storage boundaries

Goals:

- Keep route handlers thin.
- Move audiobook update/delete/reprocess/download lookup into `services/audiobooks.py`.
- Create `services/storage.py` for common helpers:
  - ensure root
  - safe delete
  - write temp/atomic replace primitives where simple
- Keep upload/cover services small and reuse storage helpers where useful.
- Improve DB/filesystem side-effect ordering where practical without overengineering.

Tests first:

- Delete removes DB row and files.
- Cover replacement/deletion still works.
- Download returns bytes and 404s when missing.
- Service-level tests cover transition/file helper behavior where cleaner than direct route calls.

## Task 4 — Schema init and constraints

Goals:

- Add advisory lock around schema init as the MVP-safe option.
- Remove queue_position schema assumptions.
- Update check constraint states.
- Add simple constraints:
  - non-negative attempt count
  - non-negative file size
  - 64-char checksum length
- Keep `Base.metadata.create_all()` for this PR; Alembic can come later as a dedicated migration PR.

Tests first:

- `initialize_schema()` can run twice.
- Model/schema tests cover important constants/constraints where practical.

## Task 5 — Final verification/review

Run:

- `pytest -q` from backend.
- Docker rebuild/start.
- Manual live API/e2e smoke with real `.m4b`:
  - upload via `POST /audiobooks`
  - list/get/patch
  - cover upload/get/delete
  - download byte match
  - jobs list/get/cancel/retry/reprocess where possible
  - delete audiobook
- Subagent review:
  - spec compliance
  - code quality
- Push branch.
- Watch GitHub CI.
- Comment on PR with summary and verification.
