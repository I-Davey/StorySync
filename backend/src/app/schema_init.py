from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import AppMeta, Base


def initialize_schema() -> None:
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        schema_version = session.scalar(select(AppMeta).where(AppMeta.key == "schema_version"))
        if schema_version is None:
            session.add(AppMeta(key="schema_version", value="1"))
            session.commit()
