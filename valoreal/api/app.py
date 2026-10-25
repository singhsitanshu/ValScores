"""FastAPI application wiring: lifespan, error handlers and routes."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..database.connection import engine
from ..database.migrator import ensure_schema_current
from .errors import register_error_handlers
from .routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Never modifies the schema: an incompatible database stops startup with a
    # message naming the migration command to run.
    ensure_schema_current(getattr(app.state, "database_engine", engine))
    yield


app = FastAPI(title="ValScores API", version="1.0.0", lifespan=lifespan)
register_error_handlers(app)
app.include_router(router)
