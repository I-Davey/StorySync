# Self-Hosted Auth and Progress Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add simple admin-created user accounts for a self-hosted global audiobook library, plus per-user listening progress.

**Architecture:** Audiobooks remain global. Authentication uses signed bearer tokens and password hashes. Admin users manage users and library mutations; normal users can browse/download the global library and manage only their own progress.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, pytest, stdlib HMAC/PBKDF2 for MVP auth primitives.

---

## Security decision

The requested default admin email is `admin@mail.com`. The requested default password must not be hardcoded into source or committed docs. Bootstrap reads it from `STORYSYNC_ADMIN_PASSWORD`. Local Docker/manual verification may provide it via runtime environment only.

## Scope

Build now:

- `users` table
- `user_audiobook_progress` table
- password hashing/verification
- bearer token issue/verify
- first admin bootstrap from env
- login and me endpoints
- admin user management endpoints
- auth/admin protection around existing audiobook/job endpoints
- per-user progress endpoints

Do not build now:

- public registration
- OAuth
- refresh tokens
- email verification
- password reset emails
- user-owned audiobooks
- roles beyond `is_admin`
- bookmarks

## Permission model

Authenticated users:

- `GET /audiobooks`
- `GET /audiobooks/{id}`
- `GET /audiobooks/{id}/download`
- `GET /audiobooks/{id}/cover`
- own progress endpoints

Admins only:

- upload/create audiobook
- patch/delete audiobook
- cover upload/delete
- reprocess
- job list/get/cancel/retry
- user management

Public:

- `GET /health`
- `POST /auth/login`

## Tasks

### Task 1: Data models and schema init

Files:

- Modify `backend/src/app/models.py`
- Modify `backend/src/app/schema_init.py`
- Add tests in `backend/tests/test_auth_models.py`

Add:

- `User`
- `UserAudiobookProgress`
- DB constraints:
  - unique lower-case email
  - progress unique `(user_id, audiobook_id)`
  - progress position non-negative
  - completed progress has `completed_at`

Schema init:

- bump version
- create tables
- add relevant indexes/checks

### Task 2: Auth primitives and bootstrap

Files:

- Create `backend/src/app/services/auth.py`
- Modify `backend/src/app/config.py`
- Add tests in `backend/tests/test_auth_service.py`

Implement:

- `normalize_email`
- `hash_password`
- `verify_password`
- `create_access_token`
- `decode_access_token`
- `bootstrap_first_admin`

Config:

- `auth_token_secret`
- `auth_token_ttl_seconds`
- `storysync_admin_email`, default `admin@mail.com`
- `storysync_admin_password`, default empty string

Bootstrap behavior:

- if no users exist and env email/password are present, create active admin
- if users exist, do nothing
- if no password, do nothing

### Task 3: Auth API and dependencies

Files:

- Create `backend/src/app/api/auth.py`
- Create `backend/src/app/dependencies.py`
- Modify `backend/src/app/main.py`
- Add tests in `backend/tests/test_auth_api.py`

Endpoints:

- `POST /auth/login`
- `GET /auth/me`

Dependencies:

- `get_current_user`
- `require_admin`

### Task 4: Admin user management

Files:

- Create `backend/src/app/api/admin_users.py`
- Add tests in `backend/tests/test_admin_users_api.py`
- Modify `backend/src/app/main.py`

Endpoints:

- `POST /admin/users`
- `GET /admin/users`
- `GET /admin/users/{user_id}`
- `PATCH /admin/users/{user_id}`
- `POST /admin/users/{user_id}/deactivate`
- `POST /admin/users/{user_id}/reset-password`

Keep simple: no delete endpoint.

### Task 5: Protect existing global-library endpoints

Files:

- Modify `backend/src/app/api/audiobooks.py`
- Modify `backend/src/app/api/jobs.py`
- Update existing tests

Rules:

- read/download/cover-get endpoints require any active user
- library mutation endpoints require admin
- job endpoints require admin
- health remains public

### Task 6: Progress API

Files:

- Create `backend/src/app/services/progress.py`
- Create `backend/src/app/api/progress.py`
- Add tests in `backend/tests/test_progress_api.py`
- Modify `backend/src/app/main.py`

Endpoints:

- `GET /me/progress`
- `GET /me/continue-listening`
- `GET /audiobooks/{audiobook_id}/progress`
- `PUT /audiobooks/{audiobook_id}/progress`
- `DELETE /audiobooks/{audiobook_id}/progress`

Behavior:

- progress is per current user
- first `PUT` creates a row
- later `PUT` updates existing row
- `started_at` remains stable
- `last_played_at` updates
- delete resets only current user progress

### Task 7: Docs, e2e, PR update

- Update README API surface and auth setup docs
- Run `pytest -q`
- Run `ruff check backend`
- Run Docker rebuild
- Manually verify:
  - bootstrap admin
  - login
  - unauthenticated protected routes reject
  - admin creates user
  - user login
  - user can list/download global books
  - user cannot mutate library/admin routes
  - progress create/list/continue/get/delete
  - admin-only job routes
- Push and update PR
