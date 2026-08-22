from opentelemetry import trace, context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from logging import getLogger
from dskity.config.settings import DSkitySettings
from fastapi import FastAPI, Request
from contextvars import ContextVar
from importlib.metadata import version


# Context variables for tracing attributes
_request_id_ctx: ContextVar[str | None] = ContextVar("trace_request_id", default=None)
_module_name_ctx: ContextVar[str | None] = ContextVar("trace_module_name", default=None)


def get_trace_request_id() -> str | None:
    """Get the current request ID from trace context."""
    return _request_id_ctx.get()


def get_trace_module_name() -> str | None:
    """Get the current module name from trace context."""
    return _module_name_ctx.get()


def set_trace_request_id(request_id: str | None) -> None:
    """Set the request ID in trace context."""
    _request_id_ctx.set(request_id)


def set_trace_module_name(module_name: str | None) -> None:
    """Set the module name in trace context."""
    _module_name_ctx.set(module_name)


def add_span_attributes(**kwargs) -> None:
    """Add attributes to the current active span."""
    span = trace.get_current_span()
    if span and span.is_recording():
        for key, value in kwargs.items():
            if value is not None:
                span.set_attribute(key, value)


def initialize_tracer(config: DSkitySettings) -> None:
    """
    Initializes the OpenTelemetry tracer provider with OTLP exporter and batch span processor.
    This function sets up the tracer provider to send traces to an OTLP endpoint.
    """

    otel_cfg = config.common.otel
    logger = getLogger(__name__)
    
    resource = Resource.create({
        "service.name": otel_cfg.service_name or config.name or "dskity",
        "service.version": otel_cfg.service_version or version(config.name),
        "deployment.environment": otel_cfg.deployment_environment or "unknown",
    })

    provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(
        endpoint=otel_cfg.endpoint,
        insecure=otel_cfg.insecure,
    )
    logger.info("OTLPSpanExporter initialized with endpoint: %s", exporter._endpoint)

    provider.add_span_processor(
        BatchSpanProcessor(exporter)
    )

    trace.set_tracer_provider(provider)
    logger.info("Tracer provider set with OTLP exporter and batch span processor.")


def install_request_id_middleware(app: FastAPI) -> None:
    """
    Install middleware that injects request_id and module_name into OpenTelemetry trace context.
    This is a single global middleware that handles all trace attributes.
    
    Module name is extracted from the request path based on enabled modules.
    """
    
    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        from dskity.request_id import get_request_id
        
        # Get request_id from request context (set by request_id middleware)
        request_id = get_request_id() or request.headers.get("x-request-id")
        set_trace_request_id(request_id)
        
        # Try to extract module name from path and enabled modules
        # Get enabled modules from app state if available
        enabled_module_names = set()
        if hasattr(request.app.state, "enabled_modules"):
            enabled_module_names = {m.name for m in request.app.state.enabled_modules}
        
        module_name = None
        path_parts = request.url.path.strip("/").split("/")
        
        # Try first part if it's an enabled module
        if path_parts and path_parts[0] in enabled_module_names:
            module_name = path_parts[0]
        # Try second part if first is 'api'
        elif path_parts and path_parts[0] == "api" and len(path_parts) > 1:
            if path_parts[1] in enabled_module_names:
                module_name = path_parts[1]
        
        set_trace_module_name(module_name)
        
        # Add all attributes to current span in one call
        add_span_attributes(
            **{
                "http.request.x_request_id": request_id,
                "http.request.module": module_name,
                "http.method": request.method,
                "http.url.path": request.url.path,
            }
        )
        
        try:
            response = await call_next(request)
            # Add response status to span
            add_span_attributes(**{"http.response.status_code": response.status_code})
            return response
        finally:
            # Clean up context
            set_trace_request_id(None)
            set_trace_module_name(None)


def install_trace_middleware(app: FastAPI) -> None:
    """
    Install global trace middleware that handles request_id and module_name.
    This replaces the need for per-module middleware.
    """
    install_request_id_middleware(app)