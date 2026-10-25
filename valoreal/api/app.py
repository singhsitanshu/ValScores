"""FastAPI application wiring: lifespan, error handlers and routes."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..database.connection import engine, initialize_database
from .errors import register_error_handlers
from .routes import router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database(engine)
    yield


app = FastAPI(title="ValScores API", version="1.0.0", lifespan=lifespan)
register_error_handlers(app)
app.include_router(router)
