from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from app.db import SessionLocal, engine
from app.models import AppMeta, Base

SCHEMA_VERSION = "6"


def initialize_schema() -> None:
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        session.execute(text("ALTER TABLE audiobooks ADD COLUMN IF NOT EXISTS cover_path TEXT"))
        session.execute(text("ALTER TABLE audiobooks ADD COLUMN IF NOT EXISTS cover_media_type VARCHAR(64)"))

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
