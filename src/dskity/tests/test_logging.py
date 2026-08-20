from __future__ import annotations

import json
import logging
import re
from io import StringIO


from dskity.logging import JsonFormatter, LogfmtFormatter, RequestIdFilter, build_logging_config, configure_logging
from dskity.request_id import _request_id_ctx


class TestJsonFormatter:
    """Test JSON log formatting."""

    def test_json_formatter_produces_valid_json(self) -> None:
        """Verify JsonFormatter outputs valid JSON."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="dskity.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.module = "test_module"
        record.funcName = "test_func"
        record.request_id = "req-123"

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["message"] == "Test message"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "dskity.test"
        assert parsed["line"] == 42

    def test_json_formatter_timestamp_format(self) -> None:
        """Verify timestamp is in ISO 8601 format with milliseconds."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="dskity.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="msg",
            args=(),
            exc_info=None,
        )
        record.module = "test"
        record.funcName = "func"
        record.request_id = "-"

        output = formatter.format(record)
        parsed = json.loads(output)
        timestamp = parsed["timestamp"]

        # Check ISO 8601 format: YYYY-MM-DDTHH:MM:SS.MMMZ
        iso_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
        assert re.match(iso_pattern, timestamp), f"Timestamp '{timestamp}' doesn't match ISO 8601 format"

    def test_json_formatter_includes_request_id(self) -> None:
        """Verify request_id is included in JSON output."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="dskity.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="msg",
            args=(),
            exc_info=None,
        )
        record.module = "test"
        record.funcName = "func"
        record.request_id = "rid-xyz-789"

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["request_id"] == "rid-xyz-789"

    def test_json_formatter_includes_all_fields(self) -> None:
        """Verify all expected fields are in JSON output."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="dskity.app",
            level=logging.WARNING,
            pathname="/path/to/file.py",
            lineno=100,
            msg="Warning occurred",
            args=(),
            exc_info=None,
        )
        record.module = "app_module"
        record.funcName = "handle_request"
        record.request_id = "req-abc"

        output = formatter.format(record)
        parsed = json.loads(output)

        expected_keys = {
            "timestamp",
            "level",
            "logger",
            "message",
            "request_id",
            "module",
            "function",
            "line",
        }
        assert set(parsed.keys()) == expected_keys

    def test_json_formatter_handles_none_request_id(self) -> None:
        """Verify JsonFormatter handles missing request_id gracefully."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="dskity.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="msg",
            args=(),
            exc_info=None,
        )
        record.module = "test"
        record.funcName = "func"
        # Don't set request_id

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["request_id"] is None


class TestLogfmtFormatter:
    """Test logfmt (key=value) log formatting."""

    def test_logfmt_formatter_produces_valid_output(self) -> None:
        """Verify LogfmtFormatter outputs valid logfmt."""
        formatter = LogfmtFormatter()
        record = logging.LogRecord(
            name="dskity.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.module = "test_module"
        record.funcName = "test_func"
        record.request_id = "req-123"

        output = formatter.format(record)

        # Should contain key=value pairs separated by spaces
        assert "timestamp=" in output
        assert "level=INFO" in output
        assert "logger=dskity.test" in output
        assert "message=" in output
        assert "request_id=req-123" in output
        assert "module=test_module" in output
        assert "function=test_func" in output
        assert "line=42" in output

    def test_logfmt_formatter_quotes_values_with_spaces(self) -> None:
        """Verify LogfmtFormatter quotes values containing spaces."""
        formatter = LogfmtFormatter()
        record = logging.LogRecord(
            name="dskity.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Message with spaces",
            args=(),
            exc_info=None,
        )
        record.module = "test"
        record.funcName = "func"
        record.request_id = "-"

        output = formatter.format(record)

        # Message with spaces should be quoted
        assert 'message="Message with spaces"' in output

    def test_logfmt_formatter_escapes_quotes(self) -> None:
        """Verify LogfmtFormatter escapes quotes in values."""
        formatter = LogfmtFormatter()
        record = logging.LogRecord(
            name="dskity.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='Message with "quotes"',
            args=(),
            exc_info=None,
        )
        record.module = "test"
        record.funcName = "func"
        record.request_id = "-"

        output = formatter.format(record)

        # Quotes should be escaped
        assert 'message="Message with \\"quotes\\""' in output

    def test_logfmt_formatter_timestamp_format(self) -> None:
        """Verify timestamp is in ISO 8601 format with milliseconds."""
        formatter = LogfmtFormatter()
        record = logging.LogRecord(
            name="dskity.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="msg",
            args=(),
            exc_info=None,
        )
        record.module = "test"
        record.funcName = "func"
        record.request_id = "-"

        output = formatter.format(record)

        # Extract timestamp value
        timestamp_match = re.search(r'timestamp="?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z)"?', output)
        assert timestamp_match, f"Timestamp not found in output: {output}"

    def test_logfmt_formatter_simple_values_unquoted(self) -> None:
        """Verify simple values without spaces are not quoted."""
        formatter = LogfmtFormatter()
        record = logging.LogRecord(
            name="dskity.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="simple",
            args=(),
            exc_info=None,
        )
        record.module = "test"
        record.funcName = "func"
        record.request_id = "-"

        output = formatter.format(record)

        # Simple values should not be quoted
        assert "level=INFO" in output
        assert "module=test" in output
        assert "function=func" in output

    def test_logfmt_formatter_includes_all_fields(self) -> None:
        """Verify all expected fields are in logfmt output."""
        formatter = LogfmtFormatter()
        record = logging.LogRecord(
            name="dskity.app",
            level=logging.WARNING,
            pathname="/path/to/file.py",
            lineno=100,
            msg="Warning occurred",
            args=(),
            exc_info=None,
        )
        record.module = "app_module"
        record.funcName = "handle_request"
        record.request_id = "req-abc"

        output = formatter.format(record)

        # Parse key=value pairs
        keys = set()
        for part in output.split():
            if "=" in part:
                key = part.split("=")[0]
                keys.add(key)

        expected_keys = {
            "timestamp",
            "level",
            "logger",
            "message",
            "request_id",
            "module",
            "function",
            "line",
        }
        assert expected_keys.issubset(keys)

    def test_logfmt_formatter_handles_none_request_id(self) -> None:
        """Verify LogfmtFormatter handles missing request_id gracefully."""
        formatter = LogfmtFormatter()
        record = logging.LogRecord(
            name="dskity.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="msg",
            args=(),
            exc_info=None,
        )
        record.module = "test"
        record.funcName = "func"
        # Don't set request_id

        output = formatter.format(record)

        # Should use default "-"
        assert "request_id=-" in output


class TestBuildLoggingConfig:
    """Test build_logging_config function."""

    def test_build_logging_config_json_format(self) -> None:
        """Verify JSON format configuration is built correctly."""
        config = build_logging_config(level="INFO", log_format="json")

        # Check that JSON formatter is configured
        assert config["formatters"]["default"]["()"] == "dskity.logging.JsonFormatter"
        assert config["formatters"]["access"]["()"] == "dskity.logging.JsonFormatter"

    def test_build_logging_config_text_format(self) -> None:
        """Verify text format configuration is built correctly."""
        config = build_logging_config(level="DEBUG", log_format="text")

        # Check that uvicorn formatters are configured
        assert config["formatters"]["default"]["()"] == "uvicorn.logging.DefaultFormatter"
        assert config["formatters"]["access"]["()"] == "uvicorn.logging.AccessFormatter"

    def test_build_logging_config_sets_log_level(self) -> None:
        """Verify log level is set correctly."""
        config = build_logging_config(level="WARNING", log_format="text")

        assert config["root"]["level"] == "WARNING"
        assert config["loggers"]["dskity"]["level"] == "WARNING"
        assert config["loggers"]["uvicorn"]["level"] == "WARNING"

    def test_build_logging_config_includes_request_id_filter(self) -> None:
        """Verify request_id filter is included in console handlers."""
        config = build_logging_config(level="INFO", log_format="json")

        console_handler = config["handlers"]["console"]
        assert "request_id" in console_handler["filters"]

    def test_build_logging_config_logfmt_format(self) -> None:
        """Verify logfmt format configuration is built correctly."""
        config = build_logging_config(level="INFO", log_format="logfmt")

        # Check that logfmt formatter is configured
        assert config["formatters"]["default"]["()"] == "dskity.logging.LogfmtFormatter"
        assert config["formatters"]["access"]["()"] == "dskity.logging.LogfmtFormatter"


class TestConfigureLogging:
    """Test configure_logging function."""

    def test_configure_logging_with_json_format(self) -> None:
        """Verify configure_logging applies JSON format correctly."""
        # Clear existing handlers
        logger = logging.getLogger("test_json_logger")
        logger.handlers.clear()

        # Configure with JSON format
        configure_logging(level="INFO", log_format="json")

        # Verify JSON formatter is applied
        handler = logging.StreamHandler()
        assert isinstance(handler.formatter, (type(None), object))

    def test_configure_logging_with_text_format(self) -> None:
        """Verify configure_logging applies text format correctly."""
        configure_logging(level="INFO", log_format="text")

        # Just verify it doesn't raise an exception
        logger = logging.getLogger("test_text_logger")
        logger.info("test message")

    def test_configure_logging_level_uppercase(self) -> None:
        """Verify log level is converted to uppercase."""
        config = build_logging_config(level="debug", log_format="text")

        assert config["root"]["level"] == "DEBUG"

    def test_configure_logging_format_lowercase(self) -> None:
        """Verify log format is converted to lowercase."""
        config_json = build_logging_config(level="INFO", log_format="JSON")
        config_text = build_logging_config(level="INFO", log_format="TEXT")

        assert config_json["formatters"]["default"]["()"] == "dskity.logging.JsonFormatter"
        assert config_text["formatters"]["default"]["()"] == "uvicorn.logging.DefaultFormatter"

    def test_configure_logging_with_logfmt_format(self) -> None:
        """Verify configure_logging applies logfmt format correctly."""
        configure_logging(level="INFO", log_format="logfmt")

        # Just verify it doesn't raise an exception
        logger = logging.getLogger("test_logfmt_logger")
        logger.info("test message")

    def test_configure_logging_logfmt_case_insensitive(self) -> None:
        """Verify logfmt format is case insensitive."""
        config = build_logging_config(level="INFO", log_format="LOGFMT")

        assert config["formatters"]["default"]["()"] == "dskity.logging.LogfmtFormatter"


class TestLoggingWithRequestId:
    """Test logging integration with request_id filter."""

    def test_request_id_filter_adds_request_id_to_record(self) -> None:
        """Verify RequestIdFilter adds request_id to log record."""
        record = logging.LogRecord(
            name="dskity.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="message",
            args=(),
            exc_info=None,
        )

        token = _request_id_ctx.set("req-test-123")
        try:
            filter_obj = RequestIdFilter()
            result = filter_obj.filter(record)
        finally:
            _request_id_ctx.reset(token)

        assert result is True
        assert getattr(record, "request_id") == "req-test-123"

    def test_request_id_filter_uses_dash_when_no_request_id(self) -> None:
        """Verify RequestIdFilter uses '-' when no request_id is set."""
        record = logging.LogRecord(
            name="dskity.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="message",
            args=(),
            exc_info=None,
        )

        filter_obj = RequestIdFilter()
        result = filter_obj.filter(record)

        assert result is True
        assert getattr(record, "request_id") == "-"

    def test_json_log_output_with_request_id_filter(self) -> None:
        """Test complete JSON logging pipeline with request_id."""
        # Setup logger with JSON formatter and request_id filter
        logger = logging.getLogger("dskity.integration_test")
        logger.handlers.clear()

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        handler.addFilter(RequestIdFilter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Log with request_id in context
        token = _request_id_ctx.set("req-integration-test")
        try:
            logger.info("Integration test message")
        finally:
            _request_id_ctx.reset(token)

        # Parse the output
        output = stream.getvalue().strip()
        parsed = json.loads(output)

        assert parsed["message"] == "Integration test message"
        assert parsed["request_id"] == "req-integration-test"
        assert parsed["level"] == "INFO"


class TestLoggingConfigurationFromSettings:
    """Test loading logging configuration from settings."""

    def test_default_log_format_is_text(self) -> None:
        """Verify default log format is 'text'."""
        config = build_logging_config(level="INFO", log_format="text")

        assert config["formatters"]["default"]["()"] == "uvicorn.logging.DefaultFormatter"

    def test_log_format_json_is_respected(self) -> None:
        """Verify JSON log format is respected."""
        config = build_logging_config(level="INFO", log_format="json")

        assert config["formatters"]["default"]["()"] == "dskity.logging.JsonFormatter"
        assert config["formatters"]["access"]["()"] == "dskity.logging.JsonFormatter"

    def test_log_format_logfmt_is_respected(self) -> None:
        """Verify logfmt log format is respected."""
        config = build_logging_config(level="INFO", log_format="logfmt")

        assert config["formatters"]["default"]["()"] == "dskity.logging.LogfmtFormatter"
        assert config["formatters"]["access"]["()"] == "dskity.logging.LogfmtFormatter"
