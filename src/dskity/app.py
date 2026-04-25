from __future__ import annotations

from fastapi import FastAPI

from dskity.bootstrap import bootstrap
from dskity.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="dskity")
    bootstrap(app)
    return app


app = create_app()
