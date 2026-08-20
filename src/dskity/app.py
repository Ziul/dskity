from __future__ import annotations

import logging
from fastapi import FastAPI

from dskity.bootstrap import bootstrap
from dskity.logging import configure_logging


def create_app() -> FastAPI:
    # Only configure logging if not already configured (to avoid overwriting CLI config)
    # Check if any handler already exists on root logger
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        configure_logging()

    app = FastAPI(title="dskity")
    # Store logger in app.state for consistent access throughout the application
    app.state.logger = logging.getLogger("dskity")
    bootstrap(app)
    return app


app = create_app()
