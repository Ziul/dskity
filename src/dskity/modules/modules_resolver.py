from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

import logging
import fastapi.routing
from fastapi import FastAPI

from dskity.registry.service_registry import ServiceRegistry
from dskity.network import get_current_host_port


def _join_url(base_url: str, route: str) -> str:
    base = (base_url or "").rstrip("/")
    path = (route or "").strip()
    if not path:
        return base
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def _urls_from_module_cfg(module_cfg: Any) -> list[str]:
    if not isinstance(module_cfg, dict):
        return []

    url = module_cfg.get("url")
    if isinstance(url, str):
        url = url.strip()
        if url:
            return [url.rstrip("/")]

    base_url = module_cfg.get("base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        base_url = module_cfg.get("advertise_url")

    route = module_cfg.get("route")
    if not isinstance(route, str) or not route.strip():
        route = module_cfg.get("base_path")

    if (
        isinstance(base_url, str)
        and base_url.strip()
        and isinstance(route, str)
        and route.strip()
    ):
        return [_join_url(base_url.strip(), route.strip())]

    return []


def _static_urls_from_config(cfg: Any, service: str) -> list[str]:
    if not isinstance(cfg, dict):
        return []

    urls: list[str] = []

    modules_cfg = cfg.get("modules")
    if isinstance(modules_cfg, dict):
        urls.extend(_urls_from_module_cfg(modules_cfg.get(service)))

    # Compat: some old overrides may have config at the top level (e.g. echo.url)
    urls.extend(_urls_from_module_cfg(cfg.get(service)))

    # remove duplicates while preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        ordered.append(u)
    return ordered


@dataclass(frozen=True)
class ModulesResolver:
    app: FastAPI

    def urls(self, service: str) -> list[str]:
        service = str(service).strip()
        urls: list[str] = []
        if not service:
            return urls

        store = getattr(self.app.state, "registry_store", None)
        if store is not None:
            logging.warning(f"Looking up service '{service}' in registry store")
            reg = ServiceRegistry(store=store)
            instances = reg.list_instances(service)
            for inst in instances:
                url = inst.get("url")
                if isinstance(url, str) and url:
                    urls.append(url)
                    continue
                base_url = inst.get("base_url")
                route = inst.get("route")
                if isinstance(base_url, str) and base_url:
                    urls.append(_join_url(base_url, str(route or "")))
            if urls:
                logging.warning(f"Found URLs for service '{service}' in registry store: {urls}")
                return urls

        # Fallback (config): allow defining fixed URLs per module when discovery is not shared.
        # E.g.: with kv.store=inmemory in separate processes.
        cfg: dict[str, Any] = getattr(self.app.state, "config", {}) or {}
        urls = _static_urls_from_config(cfg, service)
        if urls:
            logging.warning(f"Found URLs for service '{service}' in static config: {urls}")
            return urls
        logging.warning(f"No URLs found for service '{service}' in registry store or static config, trying internal base URL fallback")

        # Fallback: use internal base URL with current host and port. This allows modules to call each other using the internal network even if they are not registered in the registry store or configured with static URLs.
        host,port = get_current_host_port()
        base_url = f"http://{host}:{port}".rstrip("/")
        logging.warning(f"Using base URL for service '{service}': {base_url}")

        return [base_url]

    def paths(self, service: str) -> list[str]:
        results = []
        for route in self.app.router.routes:
            if isinstance(
                route, (fastapi.routing.APIRoute, fastapi.routing.APIWebSocketRoute)
            ):
                if route.tags and service in route.tags:
                    results.append(route.path)
        return results

    def base_path(self, service: str) -> str:
        urls = self.paths(service)
        if not urls:
            return ""
        # Return the longest common prefix of the paths as the base path
        split_paths = [u.strip("/").split("/") for u in urls]
        prefix = []

        for parts in zip(*split_paths):
            if all(p == parts[0] for p in parts):
                prefix.append(parts[0])
            else:
                break
        return "/" + "/".join(prefix) if prefix else ""

    def get(self, service: str, default: str | None = None) -> str | None:
        urls = self.urls(service)
        if not urls:
            return default
        return random.choice(urls)

    def get_request_headers(self, service: str) -> dict[str, str]:
        service = str(service).strip()
        if not service:
            return {}

        store = getattr(self.app.state, "registry_store", None)
        if store is not None:
            reg = ServiceRegistry(store=store)
            instances = reg.list_instances(service)
            for inst in instances:
                headers = inst.get("headers")
                if isinstance(headers, dict):
                    return {
                        str(k): str(v)
                        for k, v in headers.items()
                        if isinstance(k, str) and isinstance(v, str)
                    }

        return {}
