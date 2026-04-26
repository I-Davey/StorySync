from fastapi import FastAPI

from app.api.audiobooks import router as audiobooks_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.config import settings
from app.schema_init import initialize_schema
from app.services.processor import start_processor_thread

app = FastAPI(title="StorySync Backend")
app.include_router(health_router)
app.include_router(audiobooks_router)
app.include_router(jobs_router)
app.state.processor_thread = None
app.state.processor_stop_event = None


@app.on_event("startup")
def on_startup() -> None:
    initialize_schema()
    if settings.processor_enabled:
        thread, stop_event = start_processor_thread()
        app.state.processor_thread = thread
        app.state.processor_stop_event = stop_event


@app.on_event("shutdown")
def on_shutdown() -> None:
    stop_event = app.state.processor_stop_event
    thread = app.state.processor_thread
    if stop_event is not None:
        stop_event.set()
    if thread is not None:
        thread.join(timeout=5)
