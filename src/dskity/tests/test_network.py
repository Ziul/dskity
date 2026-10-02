from __future__ import annotations

from types import SimpleNamespace

from dskity.network import (
    _is_loopback,
    _is_wildcard,
    _normalize_host,
    get_current_host_port,
    update_runtime_host_port,
)


def test_is_loopback_detects_ipv4_and_ipv6():
    assert _is_loopback("127.0.0.1")
    assert _is_loopback("127.0.0.53")
    assert _is_loopback("::1")
    assert not _is_loopback("10.20.12.55")
    assert not _is_loopback("0.0.0.0")
    assert not _is_loopback(None)


def test_is_wildcard_unchanged_for_bind_all_addresses():
    assert _is_wildcard("0.0.0.0")
    assert _is_wildcard("::")
    assert not _is_wildcard("127.0.0.1")


def test_normalize_host_falls_back_for_loopback_when_cached_local_ip_available():
    app = SimpleNamespace(state=SimpleNamespace(local_ip="10.20.12.55"))

    assert _normalize_host("127.0.0.1", app=app) == "10.20.12.55"


def test_normalize_host_keeps_real_routable_addresses():
    app = SimpleNamespace(state=SimpleNamespace(local_ip="10.20.12.55"))

    # A genuinely routable address (e.g. seen on real, non-proxied traffic)
    # must be trusted as-is, not replaced by the cached local IP.
    assert _normalize_host("10.20.12.99", app=app) == "10.20.12.99"


def test_update_runtime_host_port_ignores_loopback_from_sidecar_or_port_forward():
    """Regression test.

    When traffic reaches the app through a service-mesh sidecar
    (Istio/Envoy, Linkerd) or via `kubectl port-forward`, the ASGI server
    sees the connection as originating on 127.0.0.1 — even though the pod
    has a real routable IP. Before this fix, `update_runtime_host_port`
    trusted that loopback address verbatim, which made
    `ModulesResolver.urls()` fall back to advertising
    `http://127.0.0.1:<port>` for inter-module calls whenever the shared
    registry had no instances yet, breaking cross-replica discovery.
    """

    app = SimpleNamespace(state=SimpleNamespace(local_ip="10.20.12.55"))
    scope = {"server": ("127.0.0.1", 8000)}

    update_runtime_host_port(app, scope)

    assert app.state.runtime_host == "10.20.12.55"
    assert app.state.runtime_port == 8000


def test_get_current_host_port_prefers_runtime_state_over_loopback():
    app = SimpleNamespace(
        state=SimpleNamespace(
            runtime_host="127.0.0.1",
            runtime_port=8000,
            advertise_url=None,
            local_ip="10.20.12.55",
        )
    )

    host, port = get_current_host_port(app)

    assert host == "10.20.12.55"
    assert port == 8000
