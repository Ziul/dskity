"""RFC 7807 ProblemDetails error handling for DSkity."""

from __future__ import annotations

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"


class ProblemDetail(Exception):
    """RFC 7807 Problem Details exception.

    Raise this from route handlers or middleware to return a structured error
    response with ``Content-Type: application/problem+json``.
    """

    def __init__(
        self,
        *,
        status: int,
        title: str | None = None,
        detail: str | None = None,
        instance: str | None = None,
        type_uri: str = "about:blank",
    ) -> None:
        self.status = status
        self.title = title or _default_title(status)
        self.detail = detail
        self.instance = instance
        self.type_uri = type_uri
        super().__init__(self.detail or self.title)

    def to_dict(self) -> dict:
        """Return the RFC 7807 representation."""
        body: dict = {
            "type": self.type_uri,
            "title": self.title,
            "status": self.status,
        }
        if self.detail is not None:
            body["detail"] = self.detail
        if self.instance is not None:
            body["instance"] = self.instance
        return body


def _default_title(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"


def _request_id_header(request: Request) -> dict[str, str]:
    rid = getattr(request.state, "request_id", None)
    if rid:
        return {"X-Request-Id": str(rid)}
    return {}


def install_error_handlers(app: FastAPI) -> None:
    """Register global error handlers on the FastAPI app."""

    @app.exception_handler(ProblemDetail)
    async def _problem_detail_handler(request: Request, exc: ProblemDetail) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content=exc.to_dict(),
            headers={
                "Content-Type": PROBLEM_CONTENT_TYPE,
                **_request_id_header(request),
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        body = {
            "type": "about:blank",
            "title": _default_title(exc.status_code),
            "status": exc.status_code,
            "detail": str(exc.detail) if exc.detail else None,
            "instance": str(request.url.path),
        }
        if body["detail"] is None:
            del body["detail"]
        return JSONResponse(
            status_code=exc.status_code,
            content=body,
            headers={
                "Content-Type": PROBLEM_CONTENT_TYPE,
                **_request_id_header(request),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        body = {
            "type": "about:blank",
            "title": "Unprocessable Entity",
            "status": 422,
            "detail": "Request validation failed.",
            "instance": str(request.url.path),
            "errors": exc.errors(),
        }
        return JSONResponse(
            status_code=422,
            content=body,
            headers={
                "Content-Type": PROBLEM_CONTENT_TYPE,
                **_request_id_header(request),
            },
        )

    @app.exception_handler(Exception)
    async def _generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception for %s %s", request.method, request.url.path)
        body = {
            "type": "about:blank",
            "title": "Internal Server Error",
            "status": 500,
            "detail": "An unexpected error occurred.",
            "instance": str(request.url.path),
        }
        return JSONResponse(
            status_code=500,
            content=body,
            headers={
                "Content-Type": PROBLEM_CONTENT_TYPE,
                **_request_id_header(request),
            },
        )
