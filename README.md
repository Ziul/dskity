# DSkity

[![Build](https://github.com/Ziul/dskity/actions/workflows/build.yaml/badge.svg)](https://github.com/Ziul/dskity/actions)
[![Release](https://img.shields.io/github/v/release/Ziul/dskity)](https://github.com/Ziul/dskity/releases)
[![PyPI](https://img.shields.io/pypi/v/dskity.svg)](https://pypi.org/project/dskity/)
[![Python Versions](https://img.shields.io/pypi/pyversions/dskity.svg)](https://pypi.org/project/dskity/)
[![License](https://img.shields.io/github/license/Ziul/dskity.svg)](https://github.com/Ziul/dskity/blob/main/LICENSE)
[![Issues](https://img.shields.io/github/issues/Ziul/dskity)](https://github.com/Ziul/dskity/issues)
[![Codecov](https://img.shields.io/codecov/c/gh/Ziul/dskity)](https://codecov.io/gh/Ziul/dskity)

A small, modular Python framework for building services with pluggable transports and modules.

**Key features:**
- Lightweight module system with a single `TransportClients` object (HTTP, gRPC, MQTT).
- Simple key-value backends (in-memory, Redis, Consul) with a unified interface.
- FastAPI-based HTTP transport and optional gRPC/MQTT clients.
- CI workflow with PyPI publishing support via GitHub Actions and OIDC.

**Table of Contents**
- **Overview**
- **Getting Started**
- **Configuration**
- **Running Locally**
- **Testing**
- **CI & Publishing**
- **Contributing**

## Overview

DSkity provides a minimal foundation to register independent modules that receive a single `TransportClients` object containing references to available transport clients (HTTP app, gRPC client, MQTT client). The design keeps optional dependencies lazy-loaded and avoids hard runtime requirements for gRPC or MQTT unless they are used.

## Getting Started

Prerequisites:
- Python 3.11+ (project tests are configured for modern Python versions)
- Optional: Redis or Consul if you plan to use those KV backends

Install project dependencies (development):

```bash
python -m pip install --upgrade pip
pip install -e .[dev]
```

## Configuration

Configuration is handled via the `DSkitySettings` pydantic settings model in `src/dskity/config`. You can provide a YAML or environment variables to configure transports and KV backends.

## Running Locally

Run the FastAPI app (when present) or import `dskity.bootstrap` to construct an application instance.

Example (development):

```bash
dskity
```

## Testing

Run the test suite with pytest:

```bash
pytest -q
```

## Module API

Modules must implement a `register(self, clients: TransportClients, config: DSkitySettings | dict) -> None` method. Use `clients.http` to access the FastAPI app (if available), `clients.grpc` for the gRPC client, and `clients.mqtt` for MQTT.

## Contributing

Contributions are welcome. Typical workflow:

```bash
git checkout -b feature/my-change
pytest
git push --set-upstream origin feature/my-change
```

Open a pull request for review. Please follow existing code style and update tests when adding or changing behavior.

## License

See `pyproject.toml` / `PKG-INFO` for license information.
