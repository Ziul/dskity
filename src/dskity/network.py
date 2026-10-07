import logging
import os
import socket
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _is_wildcard(host: str | None) -> bool:
    return not host or host.strip() in {"0.0.0.0", "::", "[::]"}


def _is_loopback(host: str | None) -> bool:
    """Return True for loopback addresses (127.0.0.0/8, ::1).

    These are never valid for advertising an instance to other replicas:
    besides the obvious "127.0.0.1 means something different on every pod"
    problem, ASGI servers (uvicorn/hypercorn) report the *connection's own*
    local address as ``scope["server"]``. When a request reaches the app
    through anything that proxies over loopback inside the pod's network
    namespace — a service-mesh sidecar (Istio/Envoy, Linkerd) intercepting
    inbound traffic, or ``kubectl port-forward`` — the ASGI server sees the
    connection as if it originated on ``127.0.0.1``, even though the pod has
    a real routable IP. Treating loopback like a wildcard forces a fallback
    to actual local-IP discovery instead of advertising a useless address.
    """
    if not host:
        return False
    host = host.strip().strip("[]")
    return host == "::1" or host.startswith("127.")


def _is_unroutable(host: str | None) -> bool:
    return _is_wildcard(host) or _is_loopback(host)


def get_local_ip() -> str:
    """Best-effort discovery of this instance's routable IP address.

    Order of resolution:
    1. Explicit override via ``DSKITY_ADVERTISE_HOST`` (recommended in
       Kubernetes: expose the pod IP via the Downward API, e.g.
       ``fieldRef: status.podIP``). This is independent from
       ``DSKITY_HOST``, which is the *listen* address and is commonly
       ``0.0.0.0`` (not usable for advertising/discovery).
    2. UDP "connect" trick: asks the kernel to pick the outbound local
       address for a route, without sending any actual traffic. Can fail
       (e.g. ENETUNREACH/EPERM) under restrictive CNIs/NetworkPolicies
       (Cilium, etc.) that intercept the connect() syscall.
    3. Hostname resolution: in Kubernetes the pod hostname resolves to the
       pod IP via /etc/hosts, so this works even without any egress.
    4. Interface/addrinfo scan for a non-loopback IPv4 address.
    5. Last resort: ``DSKITY_HOST`` env var (only if not a wildcard
       address), otherwise ``0.0.0.0`` with a warning, since that value is
       meaningless for service discovery.
    """
    advertise_host = os.getenv("DSKITY_ADVERTISE_HOST")
    if advertise_host and not _is_wildcard(advertise_host):
        return advertise_host.strip()

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        if local_ip and not _is_wildcard(local_ip):
            return local_ip
    except OSError as e:
        logger.debug("UDP route-lookup failed while fetching local IP: %s", e)

    try:
        hostname_ip = socket.gethostbyname(socket.gethostname())
        if hostname_ip and not hostname_ip.startswith("127.") and not _is_wildcard(hostname_ip):
            return hostname_ip
    except OSError as e:
        logger.debug("Hostname resolution failed while fetching local IP: %s", e)

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidate = info[4][0]
            if candidate and not candidate.startswith("127.") and not _is_wildcard(candidate):
                return candidate
    except OSError as e:
        logger.debug("Address-info scan failed while fetching local IP: %s", e)

    fallback = os.getenv("DSKITY_HOST", "")
    if fallback and not _is_wildcard(fallback):
        return fallback

    logger.warning(
        "Could not determine a routable local IP; falling back to 0.0.0.0. "
        "Service discovery URLs for this instance will be invalid. "
        "Set DSKITY_ADVERTISE_HOST (e.g. from the Kubernetes Downward API "
        "status.podIP) to fix this."
    )
    return "0.0.0.0"


def _parse_port(value: Any, default: int = 8000) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_host(host: str | None, *, app: Any | None = None) -> str:
    host = (host or "").strip()
    if host and not _is_unroutable(host):
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
