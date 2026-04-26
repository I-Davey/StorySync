from fastapi import FastAPI

from app.api.health import router as health_router
from app.schema_init import initialize_schema

app = FastAPI(title="StorySync Backend")
app.include_router(health_router)


@app.on_event("startup")
def on_startup() -> None:
    initialize_schema()
