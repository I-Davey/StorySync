# StorySync MVP Refactor, Optimisation, Simplification Review

Date: 2026-05-05
Branch reviewed: `chore/docker-local-setup`
Scope: current Dockerised MVP backend after upload, lifecycle, cover, download, and job-admin endpoints.

## Executive summary

The current StorySync MVP is functional and small enough to keep simple: about 2,036 code lines across 38 tracked source/doc/config files, with 43 backend tests passing. The main issue is not that the code is broken; it is that the MVP has grown from "upload and process" into "library management" and several concerns are now starting to blur together.

The biggest optimisations are architectural simplifications, not performance tricks:

1. **Create one shared API contract layer** so schemas, enums, pagination, and errors are defined once.
2. **Move business operations out of route files** so `api/` is HTTP-only and `services/` owns state changes/file operations.
3. **Centralise job state transitions** so upload, retry, cancel, reprocess, processor claim, processor success/failure, and lease recovery cannot drift.
4. **Fix schema/init and queue correctness before more feature work**; startup schema creation and persisted `queue_position` are the riskiest areas.
5. **Hide filesystem paths from API responses** before any frontend/client builds against them.
6. **Unify file storage utilities** for uploads, covers, downloads, delete cleanup, byte limits, temp files, and atomic replacement.
7. **Split and mark tests** so fast tests, Postgres tests, and live e2e tests are clear, stable, and faster.

Blunt verdict: the MVP is good, but now is exactly the right time to refactor boundaries before adding playback/progress/frontend work. If we keep adding endpoints directly into `api/audiobooks.py` and `api/jobs.py`, the backend will become awkward quickly.

## Current codebase inventory

Tracked repo shape:

- Python: 23 files, ~1,902 code lines
- YAML: 2 files, ~102 code lines
- Docker: 1 file, ~15 code lines
- TOML: 1 file, ~17 code lines
- Markdown/docs: 4 files
- Backend tests: 8 files
- App source: 16 Python files under `backend/src/app`

Largest current files:

- `backend/tests/test_e2e_api.py`: 416 lines
- `backend/src/app/api/audiobooks.py`: 276 lines
- `backend/tests/test_processor_service.py`: 241 lines
- `backend/src/app/services/processor.py`: 239 lines
- `backend/tests/test_queue_api.py`: 216 lines
- `backend/src/app/services/uploads.py`: 167 lines
- `backend/src/app/services/covers.py`: 148 lines

Verification during review:

- `pytest -q`: `43 passed`
- `compileall`: passed in subagent review
- `docker compose config`: valid in subagent review
- GitHub CI on PR #7: passing at time of previous implementation

One reviewer observed a one-off Postgres startup/schema race during test startup:

- `psycopg.errors.UniqueViolation: duplicate key value violates unique constraint "pg_type_typname_nsp_index"`
- Likely from concurrent `Base.metadata.create_all()` / schema init during live e2e startup.
- Main local reruns passed, but this is a warning sign around schema initialization.

---

# Priority 0 — Do before frontend/client work

These are contract/boundary decisions. If delayed, frontend code and tests will cement the current rough shapes.

## P0.1 Create a shared API schema/contract module

Current pain:

- `JobResponse` exists in both:
  - `backend/src/app/api/audiobooks.py`
  - `backend/src/app/api/jobs.py`
- Response mapping helpers are duplicated.
- Request/response models live inside route modules.
- OpenAPI/client shape can drift between endpoints.

Recommended change:

Create one of:

- `backend/src/app/schemas.py`
- or `backend/src/app/api/schemas.py`

Move these there:

- `JobState`
- `JobResponse`
- `JobListResponse`
- `AudiobookMetadataResponse`
- `AudiobookCoverResponse`
- `AudiobookResponse`
- `AudiobookListResponse`
- `UploadAudiobookResponse` or replacement create response
- `UpdateAudiobookRequest`
- `PaginationResponse`
- `ErrorResponse`

Use `ConfigDict(from_attributes=True)` where it keeps mapping simple, but do not force it if explicit mapping is clearer.

Why this matters:

- Removes immediate duplication.
- Gives the frontend one stable contract.
- Makes OpenAPI cleaner.
- Prevents tiny schema differences across route modules.

Suggested task size: small/medium.

## P0.2 Hide internal filesystem paths from public API responses

Current API leaks:

- `stored_path`
- `cover_path`

Files:

- `backend/src/app/api/audiobooks.py`
- `backend/src/app/models.py`

Problem:

- These are backend implementation details like `/data/audio/...`.
- They couple clients to local filesystem storage.
- They make future S3/object storage harder.
- They are unnecessary information disclosure.

Recommended response shape:

```json
{
  "id": "uuid",
  "original_filename": "book.m4b",
  "file_size_bytes": 123456,
  "checksum_sha256": "...",
  "download_url": "/audiobooks/{id}/download",
  "cover": {
    "has_cover": true,
    "media_type": "image/png",
    "url": "/audiobooks/{id}/cover"
  }
}
```

Keep paths internal in DB/models only.

If debugging needs paths, expose them only in logs/admin/debug responses, not the main public API.

Suggested task size: small, but test updates needed.

## P0.3 Group metadata under a nested object

Current response is DB-shaped:

- `metadata_title`
- `metadata_album`
- `metadata_artist`
- `metadata_genre`
- `metadata_duration_seconds`
- `metadata_track_number`
- `metadata_year`
- `metadata_raw`

Better API shape:

```json
{
  "metadata": {
    "title": "...",
    "album": "...",
    "artist": "...",
    "genre": "...",
    "duration_seconds": 123,
    "track_number": 1,
    "year": 2026,
    "raw": {}
  }
}
```

For updates, prefer:

```json
{
  "metadata": {
    "title": "Manual Title",
    "artist": "Manual Artist",
    "year": 2026
  }
}
```

Why:

- Cleaner client model.
- Decouples DB column names from API names.
- Reduces future churn when metadata expands.

Suggested task size: medium because tests need updates.

## P0.4 Decide upload endpoint shape now

Current:

```http
POST /audiobooks/upload
```

Better REST resource shape:

```http
POST /audiobooks
```

Recommendation:

- Add `POST /audiobooks` as canonical upload/create endpoint.
- Optionally keep `POST /audiobooks/upload` as a temporary alias while MVP settles.
- Return `201 Created`.
- Add `Location: /audiobooks/{id}` header.

Why:

- Avoids action-oriented special endpoint.
- Makes audiobook resource lifecycle consistent.

Suggested task size: small.

## P0.5 Standardise list and error response envelopes

Current list response:

```json
{
  "items": [],
  "page": 1,
  "page_size": 20
}
```

Recommended:

```json
{
  "items": [],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "has_next": false
  }
}
```

Do not add expensive `total_items` unless the UI needs page counts. `has_next` can be implemented with `limit(page_size + 1)`.

Current errors mostly use FastAPI default:

```json
{"detail": "Audiobook not found"}
```

Recommended app error shape before serious client work:

```json
{
  "error": {
    "code": "audiobook_not_found",
    "message": "Audiobook not found",
    "details": null
  }
}
```

Status code guidance:

- `400`: semantic bad request, e.g. missing filename
- `404`: missing audiobook/job/cover/file
- `409`: duplicate upload or invalid state transition
- `413`: too-large cover/upload
- `415`: unsupported/mismatched media type
- `422`: FastAPI validation errors
- `500`: unexpected server/storage failure

Suggested task size: medium.

---

# Priority 1 — Core architecture simplification

These reduce long-term complexity while keeping the MVP simple.

## P1.1 Move route business logic into services

Current `api/audiobooks.py` does too much:

- schema definitions
- response mapping
- DB lookup helpers
- update metadata
- cover orchestration
- delete files
- reprocess job state
- download file validation
- list query

Current `api/jobs.py` also owns transition logic.

Recommended target structure:

```text
backend/src/app/
  api/
    audiobooks.py      # HTTP endpoints only
    jobs.py            # HTTP endpoints only
    health.py
  schemas.py           # API contract
  domain.py            # enums/constants if not in schemas/models
  services/
    audiobooks.py      # update/delete/reprocess/download lookup
    jobs.py            # cancel/retry/state transitions
    uploads.py
    covers.py
    storage.py
    processor.py
    queue.py
```

Route handler should mostly be:

```python
@router.delete("/{audiobook_id}", status_code=204)
def delete_audiobook_route(audiobook_id: UUID, db: Session = Depends(get_db)) -> Response:
    audiobook = audiobook_service.get_or_404(db, audiobook_id)
    audiobook_service.delete(db, audiobook)
    return Response(status_code=204)
```

Why:

- Cleaner API files.
- Easier service-level tests.
- Stops route unit tests from encouraging fat handlers.
- Makes future CLI/background reuse easier.

Suggested task size: medium/large.

## P1.2 Centralise job state transitions

Current raw state mutations happen in:

- `backend/src/app/services/uploads.py`
- `backend/src/app/services/processor.py`
- `backend/src/app/api/jobs.py`
- `backend/src/app/api/audiobooks.py`
- `backend/src/app/schema_init.py`
- `backend/src/app/models.py`

Problem:

- State strings are repeated everywhere.
- Transition rules can drift.
- Shared field clearing is repeated.

Recommended:

Create a `JobState` enum:

```python
class JobState(str, Enum):
    RECEIVED = "received"
    QUEUED = "queued"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

Create `services/jobs.py` transition functions:

- `create_queued_job(db, audiobook)`
- `queue_job(db, job, clear_error=True)`
- `cancel_job(db, job)`
- `retry_job(db, job)`
- `reprocess_job(db, audiobook, job)`
- `claim_next_job(db, worker_id)` maybe remains processor-facing but uses same transitions
- `complete_success(db, job_id, worker_id, metadata)`
- `complete_failure(db, job_id, worker_id, error, retryable=True)`

Define allowed transitions in one place:

```text
queued -> processing
processing -> processed
processing -> queued   # retryable failure/expired lease
processing -> failed   # final failure
queued/failed -> cancelled
failed/cancelled -> queued
processed/failed/cancelled -> queued  # reprocess, if policy allows
```

Why:

- Removes duplicated state logic.
- Makes invalid transitions consistent.
- Makes race fixes easier.

Suggested task size: medium.

## P1.3 Fix `reprocess`, `cancel`, and `retry` races

Current risk:

- `reprocess_audiobook()` requeues regardless of current job state.
- API mutations load/mutate without row locks or conditional updates.
- A queued job can be claimed by the processor between API read and API commit.

Files:

- `backend/src/app/api/audiobooks.py`
- `backend/src/app/api/jobs.py`
- `backend/src/app/services/processor.py`

Recommended policy:

- Use `SELECT ... FOR UPDATE` when mutating job rows.
- Reject `reprocess` for `queued` and `processing` jobs.
- Use atomic conditional updates where possible:

```sql
UPDATE processing_jobs
SET state = 'cancelled', queue_position = NULL, worker_id = NULL, lease_expires_at = NULL
WHERE id = :id AND state IN ('received', 'queued', 'failed')
RETURNING *
```

Recommended states:

- `cancel`: `received`, `queued`, `failed`
- `retry`: `failed`, `cancelled`
- `reprocess`: `processed`, `failed`, `cancelled`; not `queued`/`processing`

Suggested task size: medium.

## P1.4 Make processor metadata write and job completion one guarded transaction

Current:

- `process_claimed_job()` writes audiobook metadata and commits.
- `complete_job_success()` later marks job processed.

File:

- `backend/src/app/services/processor.py`

Problem:

If lease is lost or success update fails after metadata commit, job can be requeued even though metadata was already written. A stale worker can also commit metadata after another worker reclaims the job.

Recommended flow:

1. Extract metadata outside DB transaction.
2. Open transaction.
3. Lock/check job row:
   - `state = processing`
   - `worker_id = current_worker`
   - `lease_expires_at > now()` if practical
4. Write audiobook metadata.
5. Set job `processed`.
6. Commit once.

Why:

- Keeps job status and metadata consistent.
- Prevents stale worker writes.

Suggested task size: medium.

---

# Priority 2 — Database/schema/queue correctness

## P2.1 Replace startup schema mutation with Alembic, or lock schema init properly

Current:

- `backend/src/app/schema_init.py` uses `Base.metadata.create_all()` and manual `ALTER TABLE`.
- `SCHEMA_VERSION` is written but not meaningfully used to apply migrations.
- Schema init is PostgreSQL-specific but not structured as migrations.

Risks:

- Existing tables drift from models.
- Concurrent startup can race.
- Future schema changes become manual and fragile.

Best recommendation:

- Introduce Alembic now while schema is still tiny.
- Create baseline migration for current models.
- In Docker/startup run `alembic upgrade head` before Uvicorn.
- App startup can verify DB revision instead of mutating schema.

MVP fallback if avoiding Alembic:

- Wrap `initialize_schema()` in a PostgreSQL advisory lock.
- Use one connection/transaction:

```python
with engine.begin() as conn:
    conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SCHEMA_INIT_LOCK_KEY})
    Base.metadata.create_all(bind=conn)
    conn.execute(text("ALTER TABLE ..."))
```

Suggested task size:

- Alembic: medium.
- Lock-only fallback: small.

## P2.2 Reconsider persisted `queue_position`

Current:

- `queue_position` is stored on jobs.
- `next_queue_position()` uses `max(queue_position) + 1` and a Postgres advisory lock.
- `autoflush=False` means repeated calls in one transaction can produce duplicate positions unless flushed.

Files:

- `backend/src/app/services/queue.py`
- `backend/src/app/services/processor.py`
- `backend/src/app/models.py`

Simplest bug fix if keeping it:

- Call `db.flush()` inside `next_queue_position()` before reading max.
- Add a partial unique index:

```sql
CREATE UNIQUE INDEX uq_processing_jobs_queued_position
ON processing_jobs(queue_position)
WHERE state = 'queued';
```

Better design:

- Use a PostgreSQL sequence for queue positions.

Best MVP simplification:

- Remove persisted `queue_position`.
- Add/keep `queued_at` timestamp.
- Claim by:

```sql
WHERE state = 'queued'
ORDER BY queued_at ASC, id ASC
FOR UPDATE SKIP LOCKED
LIMIT 1
```

Only compute display queue position when listing jobs, if needed.

Blunt recommendation:

- If the UI does not truly need exact queue positions, remove `queue_position`. It is complexity without much user value for this MVP.

Suggested task size: medium/large because tests and responses change.

## P2.3 Add DB invariants with constraints/indexes

Current only meaningful job constraint:

- `state IN (...)`

Add constraints:

```python
CheckConstraint("attempt_count >= 0", name="ck_processing_jobs_attempt_nonnegative")
CheckConstraint("file_size_bytes >= 0", name="ck_audiobooks_file_size_nonnegative")
CheckConstraint("length(checksum_sha256) = 64", name="ck_audiobooks_checksum_length")
```

If keeping `queue_position`:

```python
CheckConstraint(
    "(state = 'queued') = (queue_position IS NOT NULL)",
    name="ck_processing_jobs_queue_position_matches_state",
)
```

Processing lease invariant:

```python
CheckConstraint(
    "state != 'processing' OR (worker_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
    name="ck_processing_jobs_processing_has_lease",
)
```

Terminal cleanup invariant:

```python
CheckConstraint(
    "state NOT IN ('processed', 'failed', 'cancelled') OR "
    "(queue_position IS NULL AND worker_id IS NULL AND lease_expires_at IS NULL)",
    name="ck_processing_jobs_terminal_fields_clear",
)
```

Add indexes for real query patterns:

- queued claim index
- processing lease recovery partial index
- state/created list index
- audiobook created list index

Suggested task size: medium.

## P2.4 Add ORM relationships

Current:

- `ProcessingJob.audiobook_id` FK is unique.
- No SQLAlchemy relationship.

Add:

```python
class Audiobook(Base):
    job: Mapped["ProcessingJob"] = relationship(
        back_populates="audiobook",
        cascade="all, delete-orphan",
        uselist=False,
    )

class ProcessingJob(Base):
    audiobook: Mapped[Audiobook] = relationship(back_populates="job")
```

Why:

- Expresses one-to-one intent.
- Simplifies queries and response mapping.
- Makes delete cascade behavior clearer.

Suggested task size: small/medium.

---

# Priority 3 — Storage and file consistency

## P3.1 Create a shared storage service

Current duplication:

- `uploads.py` and `covers.py` both stream files in chunks.
- `CHUNK_SIZE` exists in multiple files.
- Temp file handling differs.
- Delete logic exists in routes and cover service.

Add:

`backend/src/app/services/storage.py`

Suggested functions:

- `ensure_storage_root()`
- `write_upload_to_temp(file, directory, max_bytes=None, checksum=False)`
- `atomic_replace(temp_path, final_path)`
- `safe_delete(path, missing_ok=True)`
- `audio_path_for_new_upload()`
- `cover_path_for(audiobook_id, extension)`

Why:

- One place for chunk size, size limits, cleanup, atomic writes.
- Simpler upload/cover/delete services.
- Easier future S3/object-store adapter.

Suggested task size: medium.

## P3.2 Make DB/filesystem side effects safer

Risky current patterns:

- Audiobook delete unlinks files before DB commit.
- Cover replacement can delete old cover before DB update is safely committed.
- Upload can leave orphan files if process crashes between file move and DB commit.

Recommended patterns:

For delete:

1. Delete DB row or mark deleted.
2. Commit.
3. Delete files best-effort.
4. Log cleanup failures.
5. Optional orphan cleanup job later.

For cover replacement:

1. Write temp.
2. Replace final new file.
3. Update DB.
4. Commit.
5. Delete old file after commit.
6. On commit failure, delete new file.

For uploads:

- Current cleanup is decent; add optional orphan sweeper later.

Suggested task size: medium.

## P3.3 Add upload file size limit

Current cover uploads have a 5 MiB limit. Audiobook uploads do not appear to have a configured max.

Recommendation:

- Add `max_audiobook_upload_bytes` to settings.
- Enforce while streaming in `uploads.py`.
- Return `413` if exceeded.
- Make default generous or disabled if desired for local MVP.

Why:

- Avoid accidental disk exhaustion.
- Keeps behavior consistent with cover handling.

Suggested task size: small.

---

# Priority 4 — Test suite, CI, Docker, developer experience

## P4.1 Mark and split tests

Current:

- E2E tests skip when Postgres unavailable.
- Local `pytest` can silently miss the most important live coverage.

Add pytest markers in `backend/pyproject.toml`:

```toml
markers = [
  "postgres: requires a live PostgreSQL database",
  "e2e: starts a live backend server",
  "slow: longer-running integration tests"
]
```

Mark live tests:

```python
pytestmark = [pytest.mark.e2e, pytest.mark.postgres]
```

Document commands:

```bash
pytest -q -m "not e2e"
pytest -q -m e2e
pytest -q
```

Suggested task size: small.

## P4.2 Make live e2e tests faster and less flaky

Current:

- Each live e2e test starts its own Uvicorn subprocess.
- Each test drops/recreates schema.
- Subprocess stdout/stderr pipes can deadlock if logs are noisy.

Recommendations:

- Session/module scoped live server.
- Per-test `TRUNCATE ... CASCADE` or transaction reset.
- Per-test audio subdirectory.
- Send Uvicorn logs to a temp file and print on failure.

Expected benefit:

- Faster tests.
- Less startup flake.
- Easier debug output.

Suggested task size: medium.

## P4.3 Add stronger real Postgres integration tests

Coverage gaps to add:

- Multiple expired leases recovered in one transaction get distinct queue order.
- Concurrent upload/retry/reprocess does not duplicate queue ordering.
- Reprocess/cancel race against claim.
- Schema init can run twice and under concurrent startup.
- DB constraints reject invalid states/invariants.

Suggested task size: medium.

## P4.4 Harden CI

Current CI should be expanded to cover Docker/dev changes.

Recommended:

- Trigger on `push` to main as well as PR.
- Expand path filters to include:
  - `backend/**`
  - `compose.yaml`
  - `.github/workflows/backend-ci.yml`
  - `.python-version`
  - `README.md`
- Add pip cache.
- Add Docker build check.
- Split `unit` and `postgres-e2e` jobs later.
- Add `pytest --durations=20` for visibility.

Suggested task size: small/medium.

## P4.5 Improve Docker runtime

Current Dockerfile is good enough for local MVP, but not hardened.

Recommendations:

- Run as non-root user.
- Use `pip install .` instead of editable install in container.
- Consider multi-stage wheel build.
- Pin base image minor/digest if reproducibility matters.
- Make Postgres host port configurable:

```yaml
ports:
  - "${POSTGRES_PORT:-5432}:5432"
```

- Consider `compose.dev.yaml` with hot reload.
- Consider compose test profile:

```yaml
profiles: ["test"]
command: pytest -q
```

Suggested task size: medium.

## P4.6 Improve docs and dev commands

Add to root/backend README:

- How to run Docker stack.
- How to run only Postgres.
- How to run fast tests.
- How to run e2e tests.
- Required env vars.
- Common troubleshooting:
  - port 5432 in use
  - `DATABASE_URL` missing
  - reset Docker volume

Add `.env.example` entries for all settings:

- `PROCESSOR_ENABLED`
- `PROCESSOR_POLL_INTERVAL_SECONDS`
- `PROCESSOR_BATCH_SIZE`
- `PROCESSOR_LEASE_SECONDS`
- `PROCESSOR_HEARTBEAT_INTERVAL_SECONDS`
- `PROCESSOR_MAX_ATTEMPTS`
- future upload limits

Optional `Makefile` or `justfile`:

```make
test:
	cd backend && pytest -q

test-fast:
	cd backend && pytest -q -m "not e2e"

compose-up:
	docker compose up --build

compose-down:
	docker compose down
```

Suggested task size: small.

---

# Priority 5 — Product/API roadmap discipline

## P5.1 Keep playback streaming and listening progress deferred

Do not bolt these on yet.

Reasons:

- Streaming requires byte range support, cache behavior, content type, auth later, and possibly file seek testing.
- Listening progress is a user/product concept. It depends on whether StorySync has users, devices, sessions, completion semantics, and sync conflict rules.
- Processing progress, import status, and listening progress are different things.

Recommended later design questions:

- Is this single-user local or multi-user?
- Is progress per audiobook, per user, per device, or global?
- Should progress be event-sourced or last-write-wins?
- Does progress mean playback position, completion status, or processing status?
- Should streaming be a separate `/audio` endpoint distinct from `/download`?

## P5.2 Endpoint shape to aim for

Near-term clean MVP API:

```http
GET    /health
POST   /audiobooks
GET    /audiobooks
GET    /audiobooks/{id}
PATCH  /audiobooks/{id}
DELETE /audiobooks/{id}
GET    /audiobooks/{id}/download
PUT    /audiobooks/{id}/cover
GET    /audiobooks/{id}/cover
DELETE /audiobooks/{id}/cover
POST   /audiobooks/{id}/reprocess
GET    /jobs
GET    /jobs/{id}
POST   /jobs/{id}/cancel
POST   /jobs/{id}/retry
```

Potential simplification:

- Use `PUT /audiobooks/{id}/cover` instead of `POST` because cover is a singleton replacement resource.
- Keep `POST /jobs/{id}/cancel` and `/retry` as pragmatic action endpoints.

## P5.3 Be cautious with global job admin

`GET /jobs` is useful for admin/dev debugging. For a user-facing frontend, most job data can be nested under audiobook responses.

Keep for now, but do not build a large job-admin product surface until needed.

---

# Suggested implementation sequence

## Refactor pass 1: Contract cleanup

1. Add shared `schemas.py` and `JobState` enum.
2. Move duplicate `JobResponse` and list schemas into it.
3. Use enum for query params and responses.
4. Hide `stored_path`/`cover_path`; add `download_url`/cover object.
5. Group metadata in response and patch request.
6. Add canonical `POST /audiobooks` alias.
7. Update tests.

Expected outcome:

- Cleaner public API before frontend locks in.
- Less schema duplication.

## Refactor pass 2: Service boundaries and state transitions

1. Add `services/audiobooks.py`.
2. Add/expand `services/jobs.py` for transitions.
3. Move route mutation logic into services.
4. Use row locks/conditional updates for cancel/retry/reprocess.
5. Make metadata write + processed state one guarded transaction.
6. Update route tests into service tests where appropriate.

Expected outcome:

- Thin route handlers.
- Central state machine.
- Less race risk.

## Refactor pass 3: Schema/queue correctness

1. Choose Alembic vs locked startup schema init.
2. If keeping startup init, add advisory lock and idempotency test.
3. Decide whether `queue_position` is needed.
4. If keeping it, add flush/sequence/unique partial index.
5. Add DB invariants/check constraints and indexes.
6. Add real Postgres integration tests.

Expected outcome:

- Safer startup.
- Safer queue.
- Less hidden DB drift.

## Refactor pass 4: Storage/devex

1. Add `services/storage.py`.
2. Unify upload/cover temp streaming/deletion.
3. Add audiobook upload size limit setting.
4. Fix DB/filesystem side-effect ordering.
5. Add pytest markers.
6. Improve live e2e fixture performance.
7. Harden CI and Docker image.
8. Expand docs and `.env.example`.

Expected outcome:

- Cleaner file handling.
- Faster local/dev workflow.
- Better CI reliability.

---

# Quick wins list

If you want small high-impact tasks first:

1. Shared schemas + remove duplicate `JobResponse`.
2. `JobState` enum and typed `state` filters.
3. Add canonical `POST /audiobooks` alias with `Location` header.
4. Add pytest markers for e2e/postgres.
5. Expand `.env.example`.
6. Add Docker build check to CI.
7. Add `db.flush()` to `next_queue_position()` if keeping current queue logic.
8. Add schema init advisory lock if not moving to Alembic immediately.
9. Add `services/storage.py` just for shared delete/temp helpers.
10. Add upload size limit setting.

# Biggest simplification question

The biggest decision is whether to keep `queue_position`.

If exact queue position is not valuable to the user, remove it and use `queued_at + id` ordering. That deletes advisory-lock complexity and avoids a whole class of bugs.

If exact position is valuable, keep it but switch to a sequence or add flush + partial unique index.

# Final recommendation

Do not add new product features next. Do one refactor pass first:

1. Shared schemas + public API cleanup.
2. Job state enum + transition service.
3. Schema init/queue correctness fix.
4. Test/CI/devex cleanup.

That will keep StorySync simple while giving you a much better base for the next real feature: frontend library browsing or carefully-designed playback/progress.
