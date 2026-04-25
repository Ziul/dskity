from __future__ import annotations

import logging

from dskity.logging import RequestIdFilter
from dskity.request_id import _request_id_ctx


def test_logging_filter_injects_request_id() -> None:
    record = logging.LogRecord(
        name="dskity",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )

    token = _request_id_ctx.set("rid-xyz")
    try:
        ok = RequestIdFilter().filter(record)
    finally:
        _request_id_ctx.reset(token)

    assert ok is True
    assert getattr(record, "request_id") == "rid-xyz"
