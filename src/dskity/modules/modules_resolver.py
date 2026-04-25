from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

from dskity.registry.service_registry import ServiceRegistry


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

    if isinstance(base_url, str) and base_url.strip() and isinstance(route, str) and route.strip():
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
        if not service:
            return []

        store = getattr(self.app.state, "registry_store", None)
        if store is not None:
            reg = ServiceRegistry(store=store)
            instances = reg.list_instances(service)
            urls: list[str] = []
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
                return urls

        # Fallback (config): allow defining fixed URLs per module when discovery is not shared.
        # E.g.: with kv.store=inmemory in separate processes.
        cfg: dict[str, Any] = getattr(self.app.state, "config", {}) or {}
        static_urls = _static_urls_from_config(cfg, service)
        if static_urls:
            return static_urls

        # Fallback: use common.internal_base_url and the module's known base_path.
        common = cfg.get("common", {}) if isinstance(cfg, dict) else {}
        internal_base_url = None
        if isinstance(common, dict):
            internal_base_url = common.get("internal_base_url")

        if not isinstance(internal_base_url, str) or not internal_base_url:
            return []

        base_path = None
        for m in getattr(self.app.state, "enabled_modules", []) or []:
            if getattr(m, "name", None) == service:
                base_path = getattr(m, "base_path", None)
                break

        if not isinstance(base_path, str) or not base_path:
            return []

        return [_join_url(internal_base_url, base_path)]

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
                    return {str(k): str(v) for k, v in headers.items() if isinstance(k, str) and isinstance(v, str)}

        return {}
