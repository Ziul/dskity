from __future__ import annotations

import logging
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBearer, HTTPAuthCredentials

from dskity.bootstrap import bootstrap
from dskity.logging import configure_logging


def create_app() -> FastAPI:
    # Only configure logging if not already configured (to avoid overwriting CLI config)
    # Check if any handler already exists on root logger
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        configure_logging()

    # Add HTTPBearer security scheme to enable auth header input in Swagger UI
    app = FastAPI(
        title="dskity",
        security=[{"HTTPBearer": []}],
    )
    
    # Store logger in app.state for consistent access throughout the application
    app.state.logger = logging.getLogger("dskity")
    
    # Add custom OpenAPI schema to include Bearer token security scheme
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        openapi_schema = get_openapi(
            title="dskity",
            version="1.0.0",
            description="API with Bearer token authentication",
            routes=app.routes,
        )
        openapi_schema["components"]["securitySchemes"] = {
            "HTTPBearer": {
                "type": "http",
                "scheme": "bearer",
                "description": "Enter your JWT or Bearer token",
            }
        }
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
    
    bootstrap(app)
    return app


app = create_app()
