from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import secrets
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings, settings as app_settings
from app.models import User

PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 260_000


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS)
    return f"{PASSWORD_HASH_ALGORITHM}${PASSWORD_HASH_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected_digest = encoded_hash.split("$", 3)
        if algorithm != PASSWORD_HASH_ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _b64decode(salt), int(iterations))
        return hmac.compare_digest(_b64encode(digest), expected_digest)
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, *, settings: Settings = app_settings) -> str:
    now = int(dt.datetime.now(dt.UTC).timestamp())
    payload = {"sub": subject, "iat": now, "exp": now + settings.auth_token_ttl_seconds}
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(settings.auth_token_secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64encode(signature)}"


def decode_access_token(token: str, *, settings: Settings = app_settings) -> dict[str, Any] | None:
    try:
        body, supplied_signature = token.split(".", 1)
        expected_signature = hmac.new(
            settings.auth_token_secret.encode("utf-8"),
            body.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(_b64encode(expected_signature), supplied_signature):
            return None
        payload = json.loads(_b64decode(body))
        if int(payload["exp"]) < int(dt.datetime.now(dt.UTC).timestamp()):
            return None
        return payload
    except (ValueError, KeyError, json.JSONDecodeError, TypeError):
        return None


def bootstrap_first_admin(db: Session, *, settings: Settings = app_settings) -> User | None:
    if not settings.storysync_admin_password:
        return None
    if db.query(User).count() > 0:
        return None

    user = User(
        email=normalize_email(settings.storysync_admin_email),
        password_hash=hash_password(settings.storysync_admin_password),
        is_admin=True,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
