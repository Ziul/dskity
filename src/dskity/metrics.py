from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import PlainTextResponse

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest


_HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    labelnames=("method", "route", "status"),
)

_HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration (seconds)",
    labelnames=("method", "route", "status"),
)


def _route_template_from_scope(scope: dict[str, Any]) -> str:
    route = scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    path = scope.get("path")
    if isinstance(path, str) and path:
        return path
    return "unknown"


def install_metrics(app: FastAPI) -> None:
    router = APIRouter(tags=["metrics"])

    @router.get("/metrics")
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.middleware("http")
    async def _metrics_middleware(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        route = _route_template_from_scope(request.scope)
        status = str(getattr(response, "status_code", 0))
        method = request.method

        _HTTP_REQUESTS_TOTAL.labels(method=method, route=route, status=status).inc()
        _HTTP_REQUEST_DURATION_SECONDS.labels(
            method=method, route=route, status=status
        ).observe(elapsed)
        return response

    app.include_router(router)
