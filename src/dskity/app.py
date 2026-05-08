from __future__ import annotations

import logging
from fastapi import FastAPI

from dskity.bootstrap import bootstrap
from dskity.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="dskity")
    # Store logger in app.state for consistent access throughout the application
    app.state.logger = logging.getLogger("dskity")
    bootstrap(app)
    return app


app = create_app()
