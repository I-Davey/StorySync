from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AppMeta(Base):
    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Audiobook(Base):
    __tablename__ = "audiobooks"
    __table_args__ = (
        CheckConstraint("file_size_bytes >= 0", name="ck_audiobooks_file_size_nonnegative"),
        CheckConstraint("length(checksum_sha256) = 64", name="ck_audiobooks_checksum_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    metadata_title: Mapped[str | None] = mapped_column(Text)
    metadata_album: Mapped[str | None] = mapped_column(Text)
    metadata_artist: Mapped[str | None] = mapped_column(Text)
    metadata_genre: Mapped[str | None] = mapped_column(Text)
    metadata_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    metadata_track_number: Mapped[int | None] = mapped_column(Integer)
    metadata_year: Mapped[int | None] = mapped_column(Integer)
    metadata_raw: Mapped[dict | None] = mapped_column(JSON)
    cover_path: Mapped[str | None] = mapped_column(Text)
    cover_media_type: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        Index("idx_users_email", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UserAudiobookProgress(Base):
    __tablename__ = "user_audiobook_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "audiobook_id", name="uq_user_audiobook_progress_user_audiobook"),
        CheckConstraint("position_seconds >= 0", name="ck_user_audiobook_progress_position_nonnegative"),
        CheckConstraint("completed = false OR completed_at IS NOT NULL", name="ck_user_audiobook_progress_completed_at"),
        Index("idx_user_audiobook_progress_user_last_played", "user_id", "last_played_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    audiobook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audiobooks.id", ondelete="CASCADE"),
        nullable=False,
    )
    position_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_played_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        CheckConstraint("state IN ('queued', 'processing', 'processed', 'failed', 'cancelled')", name="ck_processing_jobs_state"),
        CheckConstraint("attempt_count >= 0", name="ck_processing_jobs_attempt_nonnegative"),
        CheckConstraint(
            "state != 'processing' OR (worker_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_processing_jobs_processing_has_lease",
        ),
        CheckConstraint(
            "state NOT IN ('processed', 'failed', 'cancelled') OR "
            "(worker_id IS NULL AND lease_expires_at IS NULL)",
            name="ck_processing_jobs_terminal_fields_clear",
        ),
        Index("idx_processing_jobs_state_created", "state", "created_at", "id"),
        Index("idx_processing_jobs_lease", "lease_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audiobook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audiobooks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
