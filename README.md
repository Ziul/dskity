# DSkity

[![Build](https://github.com/Ziul/dskity/actions/workflows/flow.yaml/badge.svg)](https://github.com/Ziul/dskity/actions/workflows/flow.yaml)
[![Release](https://img.shields.io/github/v/release/Ziul/dskity)](https://github.com/Ziul/dskity/releases)
[![PyPI](https://img.shields.io/pypi/v/dskity.svg)](https://pypi.org/project/dskity/)
[![License](https://img.shields.io/github/license/Ziul/dskity.svg)](https://github.com/Ziul/dskity/blob/main/LICENSE)
[![Issues](https://img.shields.io/github/issues/Ziul/dskity)](https://github.com/Ziul/dskity/issues)

A modular Python framework for building FastAPI-based microservices with pluggable transports, lifecycle hooks, and built-in observability.

**Table of Contents**
- [Overview](#overview)
- [Key Features](#key-features)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [CLI Reference](#cli-reference)
- [Module API](#module-api)
- [Built-in Endpoints](#built-in-endpoints)
- [Security](#security)
- [Testing](#testing)
- [Contributing](#contributing)

---

## Overview

DSkity wraps FastAPI with a plugin system that lets you define **modules** — self-contained units that register routes, connect to shared transports, and participate in app lifecycle events. The framework handles bootstrap, service discovery, KV storage, health checks, metrics, and structured logging so your modules focus on business logic.

---

## Key Features

### Module System
- Pluggable modules discovered automatically from configurable search paths
- Module dependency ordering via `depends_on` (topological sort guarantees correct startup order)
- Lifecycle hooks: `async on_startup(clients)` and `async on_shutdown(clients)` called in registration/reverse order
- Per-module typed configuration via an optional `additional_settings_model()` hook
- `dskity init <name>` scaffolds a new module skeleton instantly

### Transports & Clients (`TransportClients`)
All modules receive a single `TransportClients` object with:

| Field | Type | Description |
|---|---|---|
| `http` | `FastAPI` | The running FastAPI app |
| `grpc` | `GRPCClient` | gRPC transport wrapper |
| `mqtt` | `MQTTClient \| None` | Singleton MQTT client (if enabled) |
| `http_client` | `HttpClientManager` | Shared async `httpx.AsyncClient` with connection pooling |
| `events` | `EventBus` | In-process async pub/sub event bus |

### Event Bus
Decouple modules with the built-in `EventBus`:

```python
# Subscribe
clients.events.on("order.created", my_handler)

# Publish (from any async context)
await clients.events.emit("order.created", {"id": 42})
```

Handlers run concurrently via `asyncio.gather`. Individual handler failures are logged and isolated — they never cancel other handlers.

### HTTP Client
A shared `httpx.AsyncClient` is available on `clients.http_client` (or `app.state.http_client`). It is started during bootstrap and closed on shutdown, reusing connections across all modules:

```python
resp = await clients.http_client.get("http://other-service/api/v1/data")
```

### KV Store
Unified key-value interface with async variants:

| Backend | Class | Notes |
|---|---|---|
| In-memory | `InMemoryKVBackend` / `AsyncInMemoryKVBackend` | Default; supports TTL |
| Redis | `RedisKVBackend` / `AsyncRedisKVBackend` | Requires `redis` extra |
| Consul | `ConsulKVBackend` / `AsyncConsulKVBackend` | Requires `requests` |

Consistent hashing ring (`HashRing`) distributes keys across registered KV instances for multi-node deployments.

### Health Checks
Built-in liveness and readiness endpoints (enabled by default):

- `GET /health/live` — always returns `200 OK`
- `GET /health/ready` — probes KV backend, MQTT, and any custom `app.state.readiness_checks`

Configure the path prefix in `settings.yaml`:

```yaml
common:
  health:
    enabled: true
    path_prefix: /health
```

### Error Handling (RFC 7807)
All unhandled errors are serialised as [Problem Details](https://datatracker.ietf.org/doc/html/rfc7807) JSON responses. Raise `ProblemDetail` for structured application errors:

```python
from dskity import ProblemDetail

raise ProblemDetail(status=422, title="Invalid order", detail="quantity must be > 0")
```

### Structured Logging
Switch between plain-text and JSON logging via config or env var:

```yaml
common:
  logging:
    format: json   # or "text"
    level: INFO
```

Every log record automatically includes `request_id`, `module`, `function`, and `line` fields.

### Metrics
Prometheus metrics are exposed at `GET /metrics` using `prometheus-client`. HTTP request counts and latencies are tracked automatically.

### Service Discovery & Registry
Modules are advertised to the built-in service registry. The `ModulesResolver` resolves service URLs with exponential-backoff retry and configurable timeout:

```yaml
common:
  resolver:
    timeout_seconds: 5.0
    retries: 3
```

Heartbeats keep entries alive; graceful deregistration happens automatically on shutdown.

### CORS
```yaml
common:
  cors:
    enabled: true
    allow_origins: ["https://my-frontend.example.com"]
    allow_methods: ["GET", "POST"]
```

### Security Headers
Add security response headers with a single config flag:

```yaml
common:
  security_headers:
    enabled: true
    x_content_type_options: nosniff
    x_frame_options: DENY
    strict_transport_security: "max-age=63072000; includeSubDomains"
    content_security_policy: "default-src 'self'"
    referrer_policy: strict-origin-when-cross-origin
    x_xss_protection: "1; mode=block"
    custom_headers:
      X-My-Header: my-value
```

---

## Getting Started

**Requirements:** Python 3.12+

```bash
pip install dskity
```

Create a `settings.yaml` in your project root and run:

```bash
dskity
```

Auto-reload is enabled by default in non-production environments (`DSKITY_ENV != production`).

---

## Configuration

DSkity reads configuration from (highest to lowest precedence):

1. Environment variables prefixed with `DSKITY_`
2. `--config` flag pointing to a YAML file
3. `settings.yaml` in the working directory
4. Built-in defaults

Use `__` (double underscore) as the hierarchy separator for env vars:

```bash
DSKITY_COMMON__LOG_LEVEL=DEBUG
DSKITY_KV__STORE=redis
DSKITY_KV__REDIS__URL=redis://localhost:6379/0
DSKITY_MODULES__ORDERS__DATABASE__URL=postgresql://user:pass@localhost/orders
```

### Full settings reference

```yaml
name: my-service

modules_search_paths:
  - dskity.modules     # Python package path
  - modules            # local directory (relative to settings.yaml)

common:
  internal_base_url: http://127.0.0.1:8000
  advertise_url: http://127.0.0.1:8000

  registry:
    enabled: true
    ttl_seconds: 60
    heartbeat_interval_seconds: 30

  mqtt:
    enabled: false
    broker: "mqtt://localhost"
    port: 1883

  cors:
    enabled: false
    allow_origins: ["*"]
    allow_methods: ["*"]
    allow_headers: ["*"]
    allow_credentials: false
    max_age: 600

  security_headers:
    enabled: false
    x_content_type_options: nosniff
    x_frame_options: DENY
    referrer_policy: strict-origin-when-cross-origin
    x_xss_protection: "1; mode=block"

  health:
    enabled: true
    path_prefix: /health

  logging:
    format: text    # or "json"
    level: INFO

  resolver:
    timeout_seconds: 5.0
    retries: 3

  admin:
    enabled: true
    show_config: false   # expose /_core/config (disabled by default)
    mask_secrets: true   # mask passwords/tokens in config output
    token: null          # if set, require Authorization: Bearer <token>

  http_client:
    timeout_seconds: 10.0
    max_connections: 100
    max_keepalive_connections: 20

kv:
  store: inmemory        # inmemory | redis | consul
  default_ttl_seconds: 60
  redis:
    url: redis://127.0.0.1:6379/0
    key_prefix: dskity
  consul:
    url: http://127.0.0.1:8500
    key_prefix: dskity

modules:
  health:
    enabled: true
```

---

## CLI Reference

```
dskity [command] [options]
```

| Command | Description |
|---|---|
| `dskity` / `dskity run` | Start the server (default) |
| `dskity init <name>` | Scaffold a new module skeleton |
| `dskity list` | List discovered modules and their enabled status |
| `dskity validate` | Validate configuration and module discovery |

### `dskity run`

```bash
dskity run \
  --config settings.yaml \
  --host 0.0.0.0 \
  --port 8000 \
  --log-level INFO \
  --target orders --target payments \   # enable only these modules
  --reload                              # auto-reload (default outside production)
```

Reload behaviour (highest to lowest precedence):
1. `--reload` / `--no-reload` flag
2. `DSKITY_RELOAD` env var (`true` / `false`)
3. Smart default: enabled unless `DSKITY_ENV=production`

### `dskity init`

```bash
dskity init orders --path services/
# Creates services/orders/__init__.py, module.py, config.py
```

### `dskity list`

```bash
dskity list                 # pretty table
dskity list --json          # machine-readable JSON
```

### `dskity validate`

```bash
dskity validate                         # check config + module discovery
dskity validate --strict                # also probe KV store connectivity
dskity validate --json                  # output as JSON (CI-friendly)
```

Exit codes: `0` = success, `1` = validation error, `2` = file not found / parse error.

---

## Module API

A module is any class with a `meta: ModuleMeta` attribute and a `register()` method:

```python
from __future__ import annotations

from dataclasses import dataclass
from fastapi import APIRouter
from pydantic import BaseModel, Field

from dskity import Module, ModuleMeta, TransportClients, DSkitySettings


class OrdersSettings(BaseModel):
    max_items: int = Field(default=100)


@dataclass(frozen=True)
class OrdersModule(Module):
    meta: ModuleMeta = ModuleMeta(
        name="orders",
        base_path="/orders",
        depends_on=("payments",),   # ensure payments starts first
    )

    def additional_settings_model(self):
        return OrdersSettings

    def register(self, clients: TransportClients, config: DSkitySettings) -> None:
        router = APIRouter(prefix=self.meta.base_path, tags=["orders"])
        settings: OrdersSettings = config.modules.orders.additional_settings

        @router.get("/")
        async def list_orders():
            # Use the shared async HTTP client to call another service
            resp = await clients.http_client.get("http://inventory/items")
            return resp.json()

        clients.http.include_router(router)

    async def on_startup(self, clients: TransportClients) -> None:
        # Subscribe to events from other modules
        clients.events.on("payment.confirmed", self._on_payment_confirmed)

    async def on_shutdown(self, clients: TransportClients) -> None:
        clients.events.off("payment.confirmed", self._on_payment_confirmed)

    async def _on_payment_confirmed(self, data: dict) -> None:
        # Handle the event
        ...
```

  ### Generated module clients (`get_client`)

  Every module can expose a generated async HTTP client built from its own routes.

  - Call `module.get_client(app)` to build a client instance.
  - Methods are generated from the module router paths.
  - Calls are routed through service discovery (`app.modules.get(module_name)`) and use the shared async HTTP client (`app.state.http_client`).

  Example:

  ```python
  from dskity.app import create_app
  from examples.modules.example.module import get_module

  app = create_app()
  module = get_module()

  client = module.get_client(app)
  result = await client.factorial(5)
  ```

  Bootstrap also exposes clients automatically:

  - `app.state.module_clients["examples"]`
  - `app.state.examples_modules`

  Method naming rules:

  - Path `/factorial/{n}` -> `factorial(n)`
  - Path `/events/emit` -> `events_emit(...)`
  - Name collision by HTTP method gets a suffix, e.g. `items()` (GET) and `items_post(...)` (POST)

### Module discovery

DSkity scans `modules_search_paths` for Python packages containing a `ModuleRegistry` or any class satisfying the `Module` protocol. Both local directories and importable package names are supported:

```yaml
modules_search_paths:
  - dskity.modules       # bundled modules
  - my_app.modules       # installed package
  - services             # local directory next to settings.yaml
```

### Dependency ordering

Use `depends_on` to declare inter-module dependencies. DSkity performs a topological sort before startup so dependent modules are always initialised after their dependencies:

```python
meta = ModuleMeta(name="reports", base_path="/reports", depends_on=("orders", "payments"))
```

---

## Built-in Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Service info and list of enabled modules |
| `GET /health/live` | Liveness probe — always `200 OK` |
| `GET /health/ready` | Readiness probe — checks KV, MQTT, custom checks |
| `GET /metrics` | Prometheus metrics |
| `GET /_core/services` | Service registry (HTML) |
| `GET /_core/services.json` | Service registry (JSON) |
| `GET /_core/config` | Current config (HTML) — requires `admin.show_config: true` |
| `GET /_core/config.json` | Current config (JSON) — requires `admin.show_config: true` |

Admin endpoints are protected by `admin.enabled` and an optional bearer token (`admin.token`). Sensitive values are masked automatically unless `admin.mask_secrets: false`.

---

## Security

### Admin endpoint protection

```yaml
common:
  admin:
    enabled: true
    token: "change-me-in-production"
    show_config: true
    mask_secrets: true
```

```bash
curl -H "Authorization: Bearer change-me-in-production" http://localhost:8000/_core/config.json
```

### Secret masking

When `admin.mask_secrets: true` (default), any field whose name contains `password`, `token`, `secret`, `apiKey`, `privateKey`, `accessKey`, or `credentials` is replaced with `***` in config output. Values that look like embedded credentials (URLs with `user:pass@`, Vault tokens, `sk-` API keys) are also masked regardless of key name.

---

## Testing

### Running the test suite

```bash
uv run pytest -q
```

### Built-in test utilities

DSkity ships testing helpers so you can write module tests without touching real services:

```python
from dskity.testing import create_test_app, create_test_client, create_test_settings

def test_my_module():
    with create_test_client() as client:
        resp = client.get("/health/live")
        assert resp.status_code == 200
```

### pytest fixtures

Install dskity in your project's dev dependencies and the following fixtures are auto-registered via the `pytest11` entry-point:

| Fixture | Scope | Description |
|---|---|---|
| `dskity_settings` | session | `DSkitySettings` with all external services disabled |
| `dskity_app` | session | Bootstrapped `FastAPI` app |
| `dskity_client` | function | `TestClient` wrapping `dskity_app` |

Override `dskity_settings` in your `conftest.py` to customise the app for your test suite:

```python
# conftest.py
import pytest
from dskity.testing import create_test_settings

@pytest.fixture(scope="session")
def dskity_settings():
    return create_test_settings(name="my-service")
```

---

## Contributing

```bash
git checkout -b feature/my-change
uv run pytest -q
git push --set-upstream origin feature/my-change
```

Open a pull request. Please follow existing code style and add or update tests for every behaviour change.

## License

See `LICENSE` for details.
