from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import require_admin
from app.models import User
from app.services.auth import hash_password, normalize_email

router = APIRouter(prefix="/admin/users", tags=["admin-users"], dependencies=[Depends(require_admin)])


class AdminUserCreateRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None
    is_admin: bool = False


class AdminUserUpdateRequest(BaseModel):
    display_name: str | None = None
    is_admin: bool | None = None
    is_active: bool | None = None


class AdminUserResetPasswordRequest(BaseModel):
    password: str


class AdminUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    is_admin: bool
    is_active: bool


def _user_response(user: User) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        is_active=user.is_active,
    )


def _get_user_or_404(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.post("", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
def create_user(payload: AdminUserCreateRequest, db: Session = Depends(get_db)) -> AdminUserResponse:
    email = normalize_email(payload.email)
    if db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    user = User(
        email=email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        is_admin=payload.is_admin,
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists") from exc
    db.refresh(user)
    return _user_response(user)


@router.get("", response_model=list[AdminUserResponse])
def list_users(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[AdminUserResponse]:
    users = db.query(User).order_by(User.created_at, User.id).offset(offset).limit(limit).all()
    return [_user_response(user) for user in users]


@router.get("/{user_id}", response_model=AdminUserResponse)
def get_user(user_id: uuid.UUID, db: Session = Depends(get_db)) -> AdminUserResponse:
    return _user_response(_get_user_or_404(db, user_id))


@router.patch("/{user_id}", response_model=AdminUserResponse)
def update_user(user_id: uuid.UUID, payload: AdminUserUpdateRequest, db: Session = Depends(get_db)) -> AdminUserResponse:
    user = _get_user_or_404(db, user_id)
    updates = payload.model_dump(exclude_unset=True)
    if "display_name" in updates:
        user.display_name = updates["display_name"]
    if "is_admin" in updates:
        user.is_admin = updates["is_admin"]
    if "is_active" in updates:
        user.is_active = updates["is_active"]
    db.commit()
    db.refresh(user)
    return _user_response(user)


@router.post("/{user_id}/deactivate", response_model=AdminUserResponse)
def deactivate_user(user_id: uuid.UUID, db: Session = Depends(get_db)) -> AdminUserResponse:
    user = _get_user_or_404(db, user_id)
    user.is_active = False
    db.commit()
    db.refresh(user)
    return _user_response(user)


@router.post("/{user_id}/reset-password", response_model=AdminUserResponse)
def reset_password(
    user_id: uuid.UUID,
    payload: AdminUserResetPasswordRequest,
    db: Session = Depends(get_db),
) -> AdminUserResponse:
    user = _get_user_or_404(db, user_id)
    user.password_hash = hash_password(payload.password)
    db.commit()
    db.refresh(user)
    return _user_response(user)
