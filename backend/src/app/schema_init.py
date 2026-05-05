from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from app.db import engine
from app.models import AppMeta, Base

SCHEMA_VERSION = "11"
SCHEMA_INIT_LOCK_KEY = 2026050510


def _drop_constraint_sql(table: str, name: str) -> str:
    return f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"


def _add_constraint_sql(table: str, name: str, check_sql: str) -> str:
    return f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({check_sql})"


def initialize_schema() -> None:
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SCHEMA_INIT_LOCK_KEY})
        Base.metadata.create_all(bind=connection)

        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT"))

        connection.execute(text("ALTER TABLE audiobooks ADD COLUMN IF NOT EXISTS cover_path TEXT"))
        connection.execute(text("ALTER TABLE audiobooks ADD COLUMN IF NOT EXISTS cover_media_type VARCHAR(64)"))
        connection.execute(text("ALTER TABLE processing_jobs DROP COLUMN IF EXISTS queue_position"))

        constraints = [
            ("processing_jobs", "ck_processing_jobs_state", "state IN ('queued', 'processing', 'processed', 'failed', 'cancelled')"),
            ("processing_jobs", "ck_processing_jobs_attempt_nonnegative", "attempt_count >= 0"),
            (
                "processing_jobs",
                "ck_processing_jobs_processing_has_lease",
                "state != 'processing' OR (worker_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            ),
            (
                "processing_jobs",
                "ck_processing_jobs_terminal_fields_clear",
                "state NOT IN ('processed', 'failed', 'cancelled') OR (worker_id IS NULL AND lease_expires_at IS NULL)",
            ),
            ("audiobooks", "ck_audiobooks_file_size_nonnegative", "file_size_bytes >= 0"),
            ("audiobooks", "ck_audiobooks_checksum_length", "length(checksum_sha256) = 64"),
            ("users", "ck_users_email_lowercase", "email = lower(email)"),
            (
                "user_audiobook_progress",
                "ck_user_audiobook_progress_position_nonnegative",
                "position_seconds >= 0",
            ),
            (
                "user_audiobook_progress",
                "ck_user_audiobook_progress_completed_at",
                "completed = false OR completed_at IS NOT NULL",
            ),
        ]
        for table, name, check_sql in constraints:
            connection.execute(text(_drop_constraint_sql(table, name)))
            connection.execute(text(_add_constraint_sql(table, name, check_sql)))

        stmt = (
            insert(AppMeta)
            .values(key="schema_version", value=SCHEMA_VERSION)
            .on_conflict_do_update(
                index_elements=["key"],
                set_={"value": SCHEMA_VERSION},
            )
        )
        connection.execute(stmt)
