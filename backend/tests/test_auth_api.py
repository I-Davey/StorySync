from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.db import get_db
from app.dependencies import require_admin
from app.main import app
from app.models import User
from app.services.auth import hash_password


def _user(*, is_admin: bool = False, is_active: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        email="admin@mail.com" if is_admin else "user@mail.com",
        password_hash=hash_password("test-only-password"),
        is_admin=is_admin,
        is_active=is_active,
    )


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _AuthDb:
    def __init__(self, user):
        self.user = user

    def execute(self, stmt):
        return _ScalarResult(self.user)


def test_login_returns_bearer_token_and_me_returns_current_user(monkeypatch) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.bootstrap_first_admin", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    user = _user(is_admin=True)
    db = _AuthDb(user)
    app.dependency_overrides[get_db] = lambda: db

    try:
        with TestClient(app) as client:
            login = client.post("/auth/login", json={"email": "ADMIN@MAIL.COM", "password": "test-only-password"})
            me = client.get("/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    finally:
        app.dependency_overrides.clear()

    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"
    assert login.json()["access_token"]
    assert me.status_code == 200
    assert me.json() == {"id": str(user.id), "email": "admin@mail.com", "is_admin": True, "is_active": True}


def test_login_rejects_bad_password_and_inactive_user(monkeypatch) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.bootstrap_first_admin", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    app.dependency_overrides[get_db] = lambda: _AuthDb(_user(is_active=False))

    try:
        with TestClient(app) as client:
            inactive = client.post("/auth/login", json={"email": "user@mail.com", "password": "test-only-password"})
        app.dependency_overrides[get_db] = lambda: _AuthDb(_user())
        with TestClient(app) as client:
            bad_password = client.post("/auth/login", json={"email": "user@mail.com", "password": "wrong"})
    finally:
        app.dependency_overrides.clear()

    assert inactive.status_code == 401
    assert bad_password.status_code == 401


def test_me_requires_valid_bearer_token(monkeypatch) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.bootstrap_first_admin", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    app.dependency_overrides[get_db] = lambda: _AuthDb(None)

    try:
        with TestClient(app) as client:
            missing = client.get("/auth/me")
            invalid = client.get("/auth/me", headers={"Authorization": "Bearer invalid"})
    finally:
        app.dependency_overrides.clear()

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_require_admin_dependency_rejects_non_admin() -> None:
    user = _user(is_admin=False)

    try:
        require_admin(user)
    except Exception as exc:
        assert getattr(exc, "status_code") == 403
    else:
        raise AssertionError("expected require_admin to reject non-admin")

    assert require_admin(_user(is_admin=True)).is_admin is True
