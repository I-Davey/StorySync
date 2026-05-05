from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.api.admin_users import router as admin_users_router
from app.api.auth import router as auth_router
from app.api.audiobooks import router as audiobooks_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.progress import router as progress_router
from app.config import settings
from app.db import SessionLocal
from app.schema_init import initialize_schema
from app.services.auth import bootstrap_first_admin
from app.services.processor import start_processor_thread


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    initialize_schema()
    with SessionLocal() as db:
        bootstrap_first_admin(db)
    if settings.processor_enabled:
        thread, stop_event = start_processor_thread()
        app.state.processor_thread = thread
        app.state.processor_stop_event = stop_event
    else:
        app.state.processor_thread = None
        app.state.processor_stop_event = None
    try:
        yield
    finally:
        stop_event = app.state.processor_stop_event
        thread = app.state.processor_thread
        if stop_event is not None:
            stop_event.set()
        if thread is not None:
            thread.join(timeout=5)

app = FastAPI(title="StorySync Backend", lifespan=lifespan)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(admin_users_router)
app.include_router(progress_router)
app.include_router(audiobooks_router)
app.include_router(jobs_router)
