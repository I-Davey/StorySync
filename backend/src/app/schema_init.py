from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from app.db import SessionLocal, engine
from app.models import AppMeta, Base

SCHEMA_VERSION = "8"


def initialize_schema() -> None:
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        session.execute(text("ALTER TABLE audiobooks ADD COLUMN IF NOT EXISTS cover_path TEXT"))
        session.execute(text("ALTER TABLE audiobooks ADD COLUMN IF NOT EXISTS cover_media_type VARCHAR(64)"))
        session.execute(text("ALTER TABLE processing_jobs DROP CONSTRAINT IF EXISTS ck_processing_jobs_state"))
        session.execute(text("ALTER TABLE processing_jobs DROP COLUMN IF EXISTS queue_position"))
        session.execute(
            text(
                "ALTER TABLE processing_jobs ADD CONSTRAINT ck_processing_jobs_state "
                "CHECK (state IN ('queued', 'processing', 'processed', 'failed', 'cancelled'))"
            )
        )

        stmt = (
            insert(AppMeta)
            .values(key="schema_version", value=SCHEMA_VERSION)
            .on_conflict_do_update(
                index_elements=["key"],
                set_={"value": SCHEMA_VERSION},
            )
        )
        session.execute(stmt)
        session.commit()
