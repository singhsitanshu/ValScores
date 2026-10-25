"""The contract error envelope and the handlers that produce it."""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..services.errors import (
    AmbiguousRosterError,
    GameNotFoundError,
    MatchNotFoundError,
    ServiceError,
)
from .schemas import ErrorDetail, ErrorResponse


ERROR_RESPONSES = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}
# Framework-raised HTTP errors without an application code.
GENERIC_ERROR_CODES = {404: "not_found", 405: "method_not_allowed"}
SERVICE_ERROR_CODES = {
    MatchNotFoundError: (404, "match_not_found"),
    GameNotFoundError: (404, "game_not_found"),
    AmbiguousRosterError: (409, "ambiguous_roster"),
}

logger = logging.getLogger("valoreal.api")


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def service_api_error(exc: ServiceError) -> HTTPException:
    status_code, code = SERVICE_ERROR_CODES[type(exc)]
    return api_error(status_code, code, str(exc))


async def http_error_response(_request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and {"code", "message"}.issubset(detail):
        error = ErrorDetail(code=str(detail["code"]), message=str(detail["message"]))
    else:
        error = ErrorDetail(
            code=GENERIC_ERROR_CODES.get(exc.status_code, "http_error"),
            message=str(detail),
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error=error).model_dump(),
        headers=exc.headers,
    )


async def validation_error_response(_request: Request, exc: RequestValidationError):
    first_error = exc.errors()[0] if exc.errors() else None
    message = first_error.get("msg", "Invalid request") if first_error else "Invalid request"
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error=ErrorDetail(code="validation_error", message=message)
        ).model_dump(),
    )


async def internal_error_response(_request: Request, exc: Exception):
    logger.exception("Unhandled API error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=ErrorDetail(code="internal_error", message="An unexpected error occurred")
        ).model_dump(),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_error_response)
    app.add_exception_handler(RequestValidationError, validation_error_response)
    app.add_exception_handler(Exception, internal_error_response)
