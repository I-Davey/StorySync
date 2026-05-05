from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.db import get_db
from app.dependencies import require_admin
from app.main import app
from app.models import User
from app.services.auth import hash_password, verify_password


class _UserQuery:
    def __init__(self, users: list[User]) -> None:
        self._users = users
        self._offset = 0
        self._limit: int | None = None

    def filter(self, condition):
        key = getattr(getattr(condition, "left", None), "key", None)
        value = getattr(getattr(condition, "right", None), "value", None)
        if key == "email":
            return _UserQuery([user for user in self._users if user.email == value])
        return self

    def order_by(self, *args):
        return self

    def offset(self, value: int):
        self._offset = value
        return self

    def limit(self, value: int):
        self._limit = value
        return self

    def first(self):
        return self._users[0] if self._users else None

    def all(self):
        users = self._users[self._offset :]
        if self._limit is not None:
            users = users[: self._limit]
        return users


class _AdminUsersDb:
    def __init__(self, users: list[User] | None = None) -> None:
        self.users = users or []
        self.commits = 0

    def query(self, model):
        assert model is User
        return _UserQuery(self.users)

    def get(self, model, user_id):
        assert model is User
        return next((user for user in self.users if user.id == user_id), None)

    def add(self, user: User) -> None:
        if user.id is None:
            user.id = uuid.uuid4()
        self.users.append(user)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, user: User) -> None:
        pass


def _user(
    *,
    email: str = "user@mail.com",
    display_name: str | None = "User",
    is_admin: bool = False,
    is_active: bool = True,
    password: str = "test-only-password",
) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        display_name=display_name,
        password_hash=hash_password(password),
        is_admin=is_admin,
        is_active=is_active,
    )


def _client(db: _AdminUsersDb, *, admin: User | None = None):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_admin] = lambda: admin or _user(email="admin@mail.com", is_admin=True)
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_admin_users_endpoints_require_admin(monkeypatch) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.bootstrap_first_admin", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)

    def reject_admin():
        raise HTTPException(status_code=403, detail="Admin privileges required")

    app.dependency_overrides[require_admin] = reject_admin
    try:
        with TestClient(app) as client:
            response = client.get("/admin/users")
    finally:
        _clear_overrides()

    assert response.status_code == 403


def test_admin_can_create_user_with_normalized_email_defaults_and_hashed_password(monkeypatch) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.bootstrap_first_admin", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    db = _AdminUsersDb()

    try:
        with _client(db) as client:
            response = client.post(
                "/admin/users",
                json={"email": " New.User@Mail.COM ", "password": "new-password", "display_name": "New User"},
            )
    finally:
        _clear_overrides()

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new.user@mail.com"
    assert body["display_name"] == "New User"
    assert body["is_admin"] is False
    assert body["is_active"] is True
    assert "password_hash" not in body
    assert db.users[0].email == "new.user@mail.com"
    assert db.users[0].password_hash != "new-password"
    assert verify_password("new-password", db.users[0].password_hash)


def test_admin_can_create_explicit_admin_and_duplicate_email_conflicts(monkeypatch) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.bootstrap_first_admin", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    db = _AdminUsersDb([_user(email="taken@mail.com")])

    try:
        with _client(db) as client:
            duplicate = client.post("/admin/users", json={"email": "TAKEN@mail.com", "password": "password"})
            admin = client.post("/admin/users", json={"email": "admin2@mail.com", "password": "password", "is_admin": True})
    finally:
        _clear_overrides()

    assert duplicate.status_code == 409
    assert admin.status_code == 201
    assert admin.json()["is_admin"] is True


def test_admin_can_list_and_get_users_without_password_hashes(monkeypatch) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.bootstrap_first_admin", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    first = _user(email="first@mail.com")
    second = _user(email="second@mail.com", display_name=None, is_active=False)
    db = _AdminUsersDb([first, second])

    try:
        with _client(db) as client:
            listed = client.get("/admin/users", params={"offset": 1, "limit": 1})
            fetched = client.get(f"/admin/users/{first.id}")
            missing = client.get(f"/admin/users/{uuid.uuid4()}")
    finally:
        _clear_overrides()

    assert listed.status_code == 200
    assert listed.json() == [
        {
            "id": str(second.id),
            "email": "second@mail.com",
            "display_name": None,
            "is_admin": False,
            "is_active": False,
        }
    ]
    assert fetched.status_code == 200
    assert fetched.json()["email"] == "first@mail.com"
    assert "password_hash" not in fetched.json()
    assert missing.status_code == 404


def test_admin_can_patch_deactivate_and_reset_password(monkeypatch) -> None:
    monkeypatch.setattr("app.main.initialize_schema", MagicMock())
    monkeypatch.setattr("app.main.bootstrap_first_admin", MagicMock())
    monkeypatch.setattr("app.main.settings.processor_enabled", False)
    user = _user(email="patch@mail.com", is_admin=False, is_active=True, password="old-password")
    db = _AdminUsersDb([user])

    try:
        with _client(db) as client:
            patched = client.patch(
                f"/admin/users/{user.id}",
                json={"display_name": "Patched", "is_admin": True, "is_active": False, "password": "ignored"},
            )
            assert verify_password("old-password", user.password_hash)

            deactivated = client.post(f"/admin/users/{user.id}/deactivate")
            reset = client.post(f"/admin/users/{user.id}/reset-password", json={"password": "new-password"})
            missing = client.post(f"/admin/users/{uuid.uuid4()}/deactivate")
    finally:
        _clear_overrides()

    assert patched.status_code == 200
    assert patched.json()["display_name"] == "Patched"
    assert patched.json()["is_admin"] is True
    assert patched.json()["is_active"] is False
    assert deactivated.status_code == 200
    assert user.is_active is False
    assert reset.status_code == 200
    assert verify_password("new-password", user.password_hash)
    assert "password_hash" not in reset.json()
    assert missing.status_code == 404
