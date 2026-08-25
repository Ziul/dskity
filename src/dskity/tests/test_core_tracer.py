"""Tests for OpenTelemetry tracer initialization and middleware."""
from __future__ import annotations

from unittest.mock import patch, Mock
import pytest

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from opentelemetry import trace

from dskity.config.settings import DSkitySettings, OtelSettings, CommonSettings
from dskity.tracer import (
    initialize_tracer,
    install_trace_middleware,
    get_trace_request_id,
    set_trace_request_id,
    get_trace_module_name,
    set_trace_module_name,
    add_span_attributes,
)
from dskity.request_id import install_request_id


class FakeModule:
    """Fake module for testing."""
    def __init__(self, name: str):
        self.name = name
        self.meta = type("Meta", (), {"name": name})()


@pytest.fixture(autouse=True)
def reset_tracer_provider():
    """Reset tracer provider before each test to avoid conflicts."""
    # Save original provider
    original_provider = trace.get_tracer_provider()
    yield
    # Restore original provider after test
    trace.set_tracer_provider(original_provider)


def test_context_vars_request_id() -> None:
    """Test setting and getting request_id from context."""
    set_trace_request_id(None)  # Clean up
    assert get_trace_request_id() is None
    
    set_trace_request_id("req-123")
    assert get_trace_request_id() == "req-123"
    
    set_trace_request_id(None)
    assert get_trace_request_id() is None


def test_context_vars_module_name() -> None:
    """Test setting and getting module_name from context."""
    set_trace_module_name(None)  # Clean up
    assert get_trace_module_name() is None
    
    set_trace_module_name("person")
    assert get_trace_module_name() == "person"
    
    set_trace_module_name(None)
    assert get_trace_module_name() is None


def test_initialize_tracer_with_config() -> None:
    """Test that tracer provider is initialized with correct settings."""
    otel_config = OtelSettings(
        enabled=True,
        endpoint="http://localhost:4317",
        insecure=True,
        service_name="test-service",
        service_version="1.0.0",
        deployment_environment="test",
    )
    common_config = CommonSettings(otel=otel_config)
    config = DSkitySettings(name="test-app", common=common_config)
    
    # Mock OTLP exporter to avoid actual network calls
    with patch("dskity.tracer.OTLPSpanExporter") as mock_exporter:
        initialize_tracer(config)
        
        # Verify exporter was created with correct parameters
        mock_exporter.assert_called_once()
        call_kwargs = mock_exporter.call_args.kwargs
        assert call_kwargs["endpoint"] == "http://localhost:4317"
        assert call_kwargs["insecure"] is True


def test_initialize_tracer_sets_global_provider() -> None:
    """Test that initialize_tracer successfully initializes without errors."""
    otel_config = OtelSettings(
        enabled=True,
        endpoint="http://localhost:4317",
        insecure=True,
        service_name="test-service",
    )
    common_config = CommonSettings(otel=otel_config)
    config = DSkitySettings(name="test-app", common=common_config)
    
    with patch("dskity.tracer.OTLPSpanExporter"):
        with patch("dskity.tracer.version", return_value="1.0.0"):
            # Should not raise an exception
            initialize_tracer(config)
            
            # Provider should exist
            provider = trace.get_tracer_provider()
            assert provider is not None


def test_middleware_captures_request_id_from_context() -> None:
    """Test that middleware captures request_id from request context."""
    app = FastAPI()
    
    # Install request_id middleware first
    install_request_id(app)
    
    # Install trace middleware
    install_trace_middleware(app)
    
    @app.get("/test")
    def test_handler(request: Request):
        # Check that request_id was set in trace context
        trace_rid = get_trace_request_id()
        return {"trace_request_id": trace_rid}
    
    client = TestClient(app)
    resp = client.get("/test", headers={"X-Request-Id": "test-123"})
    
    assert resp.status_code == 200
    data = resp.json()
    assert data["trace_request_id"] == "test-123"


def test_middleware_extracts_module_name_from_first_path_segment() -> None:
    """Test that middleware extracts module name from first path segment."""
    app = FastAPI()
    install_request_id(app)
    install_trace_middleware(app)
    
    # Simulate enabled modules
    app.state.enabled_modules = [FakeModule("person"), FakeModule("order")]
    
    @app.get("/person/list")
    def person_list():
        return {"module": get_trace_module_name()}
    
    @app.get("/order/details")
    def order_details():
        return {"module": get_trace_module_name()}
    
    client = TestClient(app)
    
    # Test person module
    resp1 = client.get("/person/list")
    assert resp1.status_code == 200
    assert resp1.json()["module"] == "person"
    
    # Test order module
    resp2 = client.get("/order/details")
    assert resp2.status_code == 200
    assert resp2.json()["module"] == "order"


def test_middleware_extracts_module_name_from_api_path() -> None:
    """Test that middleware extracts module name from /api/{module} paths."""
    app = FastAPI()
    install_request_id(app)
    install_trace_middleware(app)
    
    # Simulate enabled modules
    app.state.enabled_modules = [FakeModule("person"), FakeModule("order")]
    
    @app.get("/api/person/list")
    def api_person_list():
        return {"module": get_trace_module_name()}
    
    client = TestClient(app)
    resp = client.get("/api/person/list")
    
    assert resp.status_code == 200
    assert resp.json()["module"] == "person"


def test_middleware_returns_none_module_for_non_module_paths() -> None:
    """Test that middleware returns None for paths not matching any module."""
    app = FastAPI()
    install_request_id(app)
    install_trace_middleware(app)
    
    app.state.enabled_modules = [FakeModule("person")]
    
    @app.get("/health")
    def health():
        return {"module": get_trace_module_name()}
    
    client = TestClient(app)
    resp = client.get("/health")
    
    assert resp.status_code == 200
    assert resp.json()["module"] is None


def test_middleware_cleans_up_context_after_request() -> None:
    """Test that middleware cleans up context variables after request completes."""
    app = FastAPI()
    install_request_id(app)
    install_trace_middleware(app)
    
    app.state.enabled_modules = [FakeModule("test")]
    
    @app.get("/test")
    def test_handler():
        return {"ok": True}
    
    # Ensure context is clean before
    set_trace_request_id(None)
    set_trace_module_name(None)
    assert get_trace_request_id() is None
    assert get_trace_module_name() is None
    
    client = TestClient(app)
    client.get("/test")
    
    # Ensure context is clean after
    assert get_trace_request_id() is None
    assert get_trace_module_name() is None


def test_add_span_attributes_with_mock_span() -> None:
    """Test that add_span_attributes calls set_attribute on the active span."""
    with patch("dskity.tracer.trace.get_current_span") as mock_get_span:
        mock_span = Mock()
        mock_span.is_recording.return_value = True
        mock_get_span.return_value = mock_span
        
        add_span_attributes(
            **{
                "test.key": "test_value",
                "test.number": 42,
            }
        )
        
        # Verify set_attribute was called for each non-None value
        assert mock_span.set_attribute.call_count == 2
        
        # Check that both attributes were set
        calls = [call.args for call in mock_span.set_attribute.call_args_list]
        assert ("test.key", "test_value") in calls
        assert ("test.number", 42) in calls


def test_middleware_adds_all_span_attributes() -> None:
    """Test that middleware calls add_span_attributes with all expected attributes."""
    app = FastAPI()
    install_request_id(app)
    
    # Mock add_span_attributes to track what was called
    with patch("dskity.tracer.add_span_attributes") as mock_add_attrs:
        install_trace_middleware(app)
        
        app.state.enabled_modules = [FakeModule("test")]
        
        @app.get("/test/path")
        def test_handler():
            return {"ok": True}
        
        client = TestClient(app)
        resp = client.get("/test/path", headers={"X-Request-Id": "req-xyz"})
        
        assert resp.status_code == 200
        
        # Verify add_span_attributes was called with expected attributes
        mock_add_attrs.assert_called()
        call_args = mock_add_attrs.call_args_list[0]
        attrs = call_args[1]  # kwargs passed
        
        assert attrs["http.request.x_request_id"] == "req-xyz"
        assert attrs["http.request.module"] == "test"
        assert attrs["http.method"] == "GET"
        assert attrs["http.url.path"] == "/test/path"


def test_middleware_handles_missing_enabled_modules() -> None:
    """Test that middleware gracefully handles missing enabled_modules in app state."""
    app = FastAPI()
    install_request_id(app)
    install_trace_middleware(app)
    
    # Don't set app.state.enabled_modules
    
    @app.get("/test")
    def test_handler():
        return {"module": get_trace_module_name()}
    
    client = TestClient(app)
    resp = client.get("/test")
    
    assert resp.status_code == 200
    assert resp.json()["module"] is None


def test_otel_settings_defaults() -> None:
    """Test OtelSettings default values."""
    config = OtelSettings()
    
    assert config.enabled is False
    assert config.endpoint == "http://localhost:4317"
    assert config.insecure is True
    assert config.service_name is None
    assert config.service_version is None
    assert config.deployment_environment is None


def test_initialize_tracer_uses_service_name_from_config() -> None:
    """Test that initialize_tracer falls back to config.name when service_name not set."""
    otel_config = OtelSettings(
        enabled=True,
        endpoint="http://localhost:4317",
        insecure=True,
        # service_name not set, should use config.name
    )
    common_config = CommonSettings(otel=otel_config)
    config = DSkitySettings(name="my-app", common=common_config)
    
    with patch("dskity.tracer.OTLPSpanExporter"):
        with patch("dskity.tracer.version", return_value="1.0.0"):
            with patch("dskity.tracer.TracerProvider") as mock_provider_class:
                initialize_tracer(config)
                
                # Get the Resource that was passed to TracerProvider
                mock_provider_class.assert_called_once()
                resource = mock_provider_class.call_args[1]["resource"]
                
                assert resource.attributes["service.name"] == "my-app"


def test_initialize_tracer_uses_otel_service_name_when_set() -> None:
    """Test that initialize_tracer uses OtelSettings.service_name when set."""
    otel_config = OtelSettings(
        enabled=True,
        endpoint="http://localhost:4317",
        insecure=True,
        service_name="custom-service",
    )
    common_config = CommonSettings(otel=otel_config)
    config = DSkitySettings(name="my-app", common=common_config)
    
    with patch("dskity.tracer.OTLPSpanExporter"):
        with patch("dskity.tracer.version", return_value="1.0.0"):
            with patch("dskity.tracer.TracerProvider") as mock_provider_class:
                initialize_tracer(config)
                
                resource = mock_provider_class.call_args[1]["resource"]
                assert resource.attributes["service.name"] == "custom-service"


def test_add_span_attributes_skips_none_values() -> None:
    """Test that add_span_attributes skips None values."""
    with patch("dskity.tracer.trace.get_current_span") as mock_get_span:
        mock_span = Mock()
        mock_span.is_recording.return_value = True
        mock_get_span.return_value = mock_span
        
        add_span_attributes(
            **{
                "test.key": "value",
                "test.none": None,  # Should be skipped
            }
        )
        
        # Verify set_attribute was only called for non-None value
        assert mock_span.set_attribute.call_count == 1
        mock_span.set_attribute.assert_called_once_with("test.key", "value")
