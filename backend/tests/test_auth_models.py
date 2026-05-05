from __future__ import annotations

from app.models import User, UserAudiobookProgress


def _constraint_names(model) -> set[str]:
    return {constraint.name for constraint in model.__table__.constraints if constraint.name}


def _index_names(model) -> set[str]:
    return {index.name for index in model.__table__.indexes if index.name}


def test_user_model_has_auth_columns_and_lowercase_email_constraint() -> None:
    assert User.__tablename__ == "users"
    assert "email" in User.__table__.columns
    assert "password_hash" in User.__table__.columns
    assert "is_admin" in User.__table__.columns
    assert "is_active" in User.__table__.columns

    names = _constraint_names(User)
    assert "uq_users_email" in names
    assert "ck_users_email_lowercase" in names


def test_user_progress_model_has_integrity_constraints() -> None:
    assert UserAudiobookProgress.__tablename__ == "user_audiobook_progress"

    names = _constraint_names(UserAudiobookProgress)
    indexes = _index_names(UserAudiobookProgress)

    assert "uq_user_audiobook_progress_user_audiobook" in names
    assert "ck_user_audiobook_progress_position_nonnegative" in names
    assert "ck_user_audiobook_progress_completed_at" in names
    assert "idx_user_audiobook_progress_user_last_played" in indexes
