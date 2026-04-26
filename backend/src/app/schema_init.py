from sqlalchemy.dialects.postgresql import insert

from app.db import SessionLocal, engine
from app.models import AppMeta, Base


def initialize_schema() -> None:
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        stmt = (
            insert(AppMeta)
            .values(key="schema_version", value="5")
            .on_conflict_do_nothing(index_elements=["key"])
        )
        session.execute(stmt)
        session.commit()
