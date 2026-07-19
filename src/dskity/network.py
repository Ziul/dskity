import os
import socket
import logging
from typing import Any
from urllib.parse import urlparse


def get_local_ip() -> str:
    """Get the local IP address of the machine."""
    try:
        # Connect to an external host to determine the local IP
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        return local_ip
    except Exception as e:
        logging.error(f"Error occurred while fetching local IP: {e}")
        return os.getenv("DSKITY_HOST", "0.0.0.0")


def _parse_port(value: Any, default: int = 8000) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_host(host: str | None, *, app: Any | None = None) -> str:
    host = (host or "").strip()
    if host and host not in {"0.0.0.0", "::", "[::]"}:
        return host

    if app is not None:
        state = getattr(app, "state", None)
        local_ip = getattr(state, "local_ip", None) if state is not None else None
        if isinstance(local_ip, str) and local_ip.strip():
            return local_ip.strip()

    return get_local_ip()


def _host_port_from_server(server: Any, *, app: Any | None = None) -> tuple[str, int] | None:
    if not isinstance(server, (tuple, list)) or len(server) < 2:
        return None
    host = _normalize_host(str(server[0]) if server[0] is not None else None, app=app)
    port = _parse_port(server[1], default=8000)
    return host, port


def update_runtime_host_port(app: Any, scope: dict[str, Any]) -> None:
    """Persist best-effort host/port discovered from ASGI scope in app.state."""
    state = getattr(app, "state", None)
    if state is None:
        return
    resolved = _host_port_from_server(scope.get("server"), app=app)
    if resolved is None:
        return
    host, port = resolved
    state.runtime_host = host
    state.runtime_port = port


def get_current_host_port(app: Any | None = None) -> tuple[str, int]:
    """Resolve current host/port preferring runtime FastAPI state over env vars."""
    if app is not None:
        state = getattr(app, "state", None)
        if state is not None:
            runtime_port = getattr(state, "runtime_port", None)
            if runtime_port is not None:
                runtime_host = _normalize_host(getattr(state, "runtime_host", None), app=app)
                return runtime_host, _parse_port(runtime_port, default=8000)

            advertise_url = getattr(state, "advertise_url", None)
            if isinstance(advertise_url, str) and advertise_url.strip():
                parsed = urlparse(advertise_url.strip())
                if parsed.port is not None:
                    return _normalize_host(parsed.hostname, app=app), int(parsed.port)

    host = _normalize_host(os.getenv("DSKITY_HOST", "0.0.0.0"), app=app)
    port = _parse_port(os.getenv("DSKITY_PORT", "8000"), default=8000)
    return host, port
