# Library Management Endpoints Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add simple, production-usable StorySync API endpoints for audiobook lifecycle management, metadata edits/reprocessing, download, artwork, and job administration while deliberately leaving streaming/progress for a later design pass.

**Architecture:** Keep the existing FastAPI + SQLAlchemy shape. Add small service modules for file/artwork/lifecycle/job operations so route handlers stay thin. Avoid migrations for now by relying on `Base.metadata.create_all`; if the schema changes, bump `schema_version` and keep changes additive/simple.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, PostgreSQL, Mutagen MP4/M4B metadata/artwork support, pytest/httpx e2e tests.

---

## Scope

Implement these endpoints:

1. `DELETE /audiobooks/{audiobook_id}`
2. `POST /audiobooks/{audiobook_id}/reprocess`
3. `PATCH /audiobooks/{audiobook_id}`
4. `GET /audiobooks/{audiobook_id}/download`
5. `GET /audiobooks/{audiobook_id}/cover`
6. `POST /audiobooks/{audiobook_id}/cover`
7. `DELETE /audiobooks/{audiobook_id}/cover`
8. `GET /jobs`
9. `POST /jobs/{job_id}/retry`
10. `POST /jobs/{job_id}/cancel`

Explicitly **do not** implement streaming/range support yet. It needs more design.

## Design decisions

- Metadata update is manual DB metadata only. Do not rewrite `.m4b` tags yet.
- Reprocess sets existing job back to `queued`, clears error/worker/lease, assigns next queue position, and clears extracted metadata fields. It does not create duplicate jobs because `ProcessingJob.audiobook_id` is unique.
- Delete removes the DB audiobook and attempts to delete the stored audio file and cover file. If file deletion fails, fail with `500`; if file is already missing, continue.
- Download returns a `FileResponse` for the original file. Use `audio/mp4` media type and attachment filename from `original_filename`.
- Cover support stores one cover per audiobook on disk under `AUDIO_STORAGE_ROOT/covers/{audiobook_id}.{ext}` and stores path/media type on `Audiobook`. This is simple and avoids a separate table.
- Embedded cover extraction from `.m4b` is useful but optional for v1. For `GET /cover`, first return manually uploaded cover. If absent, try extracting embedded MP4 cover from `covr` in memory and return it if present. If none, return `404`.
- Job cancel uses state `cancelled`. Add `cancelled` to the job state check constraint.
- Job retry only allows failed/cancelled jobs initially; if job is currently queued/processing/processed, return `409`.

## Data model changes

Modify `backend/src/app/models.py`:

- Add nullable columns to `Audiobook`:
  - `cover_path: Mapped[str | None] = mapped_column(Text)`
  - `cover_media_type: Mapped[str | None] = mapped_column(String(64))`
- Update `ProcessingJob` check constraint to allow:
  - `received`, `queued`, `processing`, `processed`, `failed`, `cancelled`

Modify `backend/src/app/schema_init.py`:

- Bump `schema_version` from `5` to `6`.
- Add lightweight additive schema upgrade for existing dev DBs:
  - `ALTER TABLE audiobooks ADD COLUMN IF NOT EXISTS cover_path TEXT`
  - `ALTER TABLE audiobooks ADD COLUMN IF NOT EXISTS cover_media_type VARCHAR(64)`
  - For PostgreSQL dev DBs, replace/drop/recreate check constraint if needed so `cancelled` is accepted.

## Response models

Reuse existing `AudiobookResponse` and `JobResponse` where possible.

Add:

```python
class UpdateAudiobookRequest(BaseModel):
    metadata_title: str | None = None
    metadata_album: str | None = None
    metadata_artist: str | None = None
    metadata_genre: str | None = None
    metadata_duration_seconds: int | None = Field(default=None, ge=0)
    metadata_track_number: int | None = Field(default=None, ge=0)
    metadata_year: int | None = Field(default=None, ge=0)
```

Allow partial updates. Only fields explicitly sent should be updated.

Add job list response:

```python
class JobListResponse(BaseModel):
    items: list[JobResponse]
    page: int
    page_size: int
```

---

## Task 1: Add tests for lifecycle endpoints

**Objective:** Create failing tests for delete, manual metadata patch, reprocess, and download.

**Files:**
- Modify: `backend/tests/test_e2e_api.py`
- Modify: `backend/tests/test_audiobooks_api.py` if small unit coverage is helpful

**Tests to add:**

1. `test_e2e_live_patch_reprocess_download_and_delete_audiobook`
   - Upload `.m4b`
   - `PATCH /audiobooks/{id}` with metadata title/artist/year
   - Assert returned metadata fields update
   - `GET /audiobooks/{id}/download`
   - Assert `200`, body bytes match uploaded payload, content-disposition contains original filename
   - `POST /audiobooks/{id}/reprocess`
   - Assert job state returns `queued`
   - `DELETE /audiobooks/{id}`
   - Assert `204`
   - Assert stored file no longer exists
   - Assert `GET /audiobooks/{id}` returns `404`

2. Error cases:
   - `PATCH /audiobooks/{missing}` -> `404`
   - `POST /audiobooks/{missing}/reprocess` -> `404`
   - `GET /audiobooks/{missing}/download` -> `404`
   - `DELETE /audiobooks/{missing}` -> `404`

**Run RED:**

```bash
cd backend
pytest tests/test_e2e_api.py::test_e2e_live_patch_reprocess_download_and_delete_audiobook -v
```

Expected: fail because endpoints do not exist.

---

## Task 2: Implement audiobook lifecycle service + routes

**Objective:** Make Task 1 tests pass with thin route handlers and simple service functions.

**Files:**
- Create: `backend/src/app/services/audiobooks.py`
- Modify: `backend/src/app/api/audiobooks.py`

**Implementation notes:**

- Add helper `_get_audiobook_or_404(db, audiobook_id)` in API or service.
- Add helper to serialize `Audiobook` + optional job into `AudiobookResponse` to remove current duplicated response-building code.
- `PATCH` should use Pydantic `model_fields_set` / `model_dump(exclude_unset=True)` so omitted fields are not overwritten.
- `DELETE` should delete the stored audio file and cover file if present, then delete DB object and commit.
- `reprocess` should find existing job, set state `queued`, assign queue position using a shared queue helper, clear worker/lease/error, clear metadata fields on audiobook, and commit.
- `download` should verify stored path exists and return `FileResponse`.

**Run GREEN:**

```bash
cd backend
pytest tests/test_e2e_api.py::test_e2e_live_patch_reprocess_download_and_delete_audiobook -v
pytest tests/test_audiobooks_api.py tests/test_queue_api.py -q
```

---

## Task 3: Add tests for cover endpoints

**Objective:** Create failing e2e tests for manual cover upload/get/delete.

**Files:**
- Modify: `backend/tests/test_e2e_api.py`

**Tests to add:**

1. `test_e2e_live_cover_upload_get_and_delete`
   - Upload `.m4b`
   - POST PNG bytes to `/audiobooks/{id}/cover` with filename `cover.png`, media type `image/png`
   - Assert response returns updated audiobook or `204`/simple payload, depending implementation
   - GET cover returns same bytes with `image/png`
   - DELETE cover returns `204`
   - GET cover returns `404`

2. Error cases:
   - POST cover to missing audiobook -> `404`
   - POST non-image cover file -> `415`
   - GET missing cover -> `404`

**Run RED:**

```bash
cd backend
pytest tests/test_e2e_api.py::test_e2e_live_cover_upload_get_and_delete -v
```

Expected: fail because endpoints do not exist.

---

## Task 4: Implement cover service + routes

**Objective:** Make cover endpoint tests pass without overbuilding.

**Files:**
- Create: `backend/src/app/services/covers.py`
- Modify: `backend/src/app/models.py`
- Modify: `backend/src/app/schema_init.py`
- Modify: `backend/src/app/api/audiobooks.py`

**Implementation notes:**

- Accept only `image/jpeg`, `image/png`, `image/webp`.
- Store under `{AUDIO_STORAGE_ROOT}/covers/{audiobook_id}.{jpg|png|webp}`.
- Delete old cover file before replacing.
- Save `cover_path` and `cover_media_type` on audiobook.
- Return `AudiobookResponse` from POST cover for consistency.
- `GET /cover` returns `FileResponse` if manual cover exists.
- If no manual cover exists, attempt embedded cover extraction from `mutagen.mp4.MP4(path).tags['covr']`. Return bytes via `Response` if present.
- `DELETE /cover` is idempotent for an existing audiobook: return `204` whether cover existed or not.

**Run GREEN:**

```bash
cd backend
pytest tests/test_e2e_api.py::test_e2e_live_cover_upload_get_and_delete -v
pytest tests/test_e2e_api.py -q
```

---

## Task 5: Add tests for job admin endpoints

**Objective:** Create failing tests for list, retry, and cancel jobs.

**Files:**
- Modify: `backend/tests/test_e2e_api.py`
- Modify: `backend/tests/test_queue_api.py` for service/unit-level checks if needed

**Tests to add:**

1. `test_e2e_live_list_retry_and_cancel_jobs`
   - Upload `.m4b` with processor disabled; job is queued
   - `GET /jobs` returns job
   - `GET /jobs?state=queued` returns job
   - `POST /jobs/{job_id}/cancel` returns job with state `cancelled`
   - `GET /jobs?state=cancelled` returns job
   - `POST /jobs/{job_id}/retry` returns job with state `queued` and queue position set

2. Conflict cases:
   - Retrying already queued job -> `409`
   - Cancelling processed job -> `409` or allow? Decision: return `409` for processed.
   - Missing job retry/cancel -> `404`

**Run RED:**

```bash
cd backend
pytest tests/test_e2e_api.py::test_e2e_live_list_retry_and_cancel_jobs -v
```

Expected: fail because endpoints/state do not exist.

---

## Task 6: Implement job admin service + routes

**Objective:** Make job admin tests pass with clear state transitions.

**Files:**
- Create: `backend/src/app/services/jobs.py`
- Modify: `backend/src/app/api/jobs.py`
- Modify: `backend/src/app/models.py`
- Modify: `backend/src/app/schema_init.py`

**Implementation notes:**

- Reuse a single `_next_queue_position(db)` helper. Prefer moving it to `app.services.queue` if both uploads/processor/jobs need it.
- `GET /jobs` supports `page`, `page_size`, `state`.
- `retry_job`:
  - allowed states: `failed`, `cancelled`
  - set `queued`, `queue_position=next`, clear `last_error`, `worker_id`, `lease_expires_at`
  - do not reset `attempt_count`
- `cancel_job`:
  - allowed states: `received`, `queued`, `processing`, `failed`
  - disallowed states: `processed`, `cancelled`
  - set `cancelled`, clear queue/worker/lease
  - for processing, this does not kill in-flight work yet; document as best-effort state cancellation.

**Run GREEN:**

```bash
cd backend
pytest tests/test_e2e_api.py::test_e2e_live_list_retry_and_cancel_jobs -v
pytest tests/test_queue_api.py -q
```

---

## Task 7: Full e2e + Docker verification

**Objective:** Prove all endpoints work both in tests and in the actual Docker container.

**Files:**
- Modify: `README.md` if endpoint docs are added
- Optional create: `backend/tests/test_e2e_library_management.py` if splitting keeps files cleaner

**Commands:**

```bash
cd backend
pytest -q
```

Then Docker:

```bash
cd ..
docker compose up -d --build
curl -fsS http://127.0.0.1:8000/health
```

Manual Docker API script should:

- Upload `.m4b`
- Patch metadata
- Upload cover
- Get cover
- Download audiobook
- List jobs
- Cancel job
- Retry job
- Reprocess audiobook
- Delete audiobook
- Confirm `404` after delete

---

## Task 8: Final cleanup, docs, and PR update

**Objective:** Keep the code neat/simple and update the existing PR.

**Files:**
- Modify: `README.md`
- Possibly modify: `docs/plans/2026-05-05-library-management-endpoints.md` if implementation differs

**Checklist:**

- No duplicated response mapping blocks if easy to avoid.
- No large abstractions/frameworks.
- Service helpers are small and named for behavior.
- Tests cover happy paths and useful errors.
- `pytest -q` passes.
- Docker manual verification passes.
- `git diff` is reviewed.
- Push branch and comment on PR with test results.
