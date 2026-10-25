"""Injectable collaborators for routes; tests replace them with app.dependency_overrides."""

from ..database.connection import SessionLocal
from ..services.refresh import RefreshService


_refresh_service = RefreshService(session_factory=SessionLocal)


def get_session_factory():
    return SessionLocal


def get_refresh_service():
    return _refresh_service
