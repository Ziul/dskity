from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from biostation_api.core.kvstore.backends import backend_from_config
from biostation_api.core.kvstore.ring import ring_from_runtime
from biostation_api.core.modules.contracts import Module, ModuleMeta
from biostation_api.core.registry.store import RegistryStore

@dataclass(frozen=True)
class KvStoreModule(Module):
    meta: ModuleMeta = ModuleMeta(name="kvstore", base_path="")

    def register(self, clients, config: dict) -> None:
        app = getattr(clients, "http", None)
        ring, node_id = ring_from_runtime(app, config)

        backend = getattr(app.state, "kvstore_backend", None)
        store_name = getattr(app.state, "kvstore_store", None)
        if backend is None or store_name is None:
            try:
                store_name, backend = backend_from_config(config)
            except (ValueError, NotImplementedError) as e:
                raise RuntimeError(str(e)) from e
            app.state.kvstore_backend = backend
            app.state.kvstore_store = store_name
            app.state.registry_store = RegistryStore(backend=backend)

        # Reuse the global instance_id (if present) for consistency between modules.
        node_id = getattr(app.state, "instance_id", node_id)

        router = APIRouter(tags=[self.meta.name])

        def owner_redirect(key: str) -> RedirectResponse | None:
            owner = ring.owner_for_key(key)
            if owner is None:
                return None
            if owner.id == node_id:
                return None
            # 307 preserves method and body (also for PUT/DELETE).
            return RedirectResponse(url=f"{owner.base_url}/kv/{key}", status_code=307)

        @router.get("/kv/ring")
        def ring_info() -> dict:
            return {
                "node_id": node_id,
                "store": store_name,
                "nodes_count": len(ring.nodes),
                "vnodes": ring.vnodes,
                "nodes": [{"id": n.id, "base_url": n.base_url} for n in ring.nodes],
            }

        @router.get("/kv")
        def list_keys(prefix: str = "") -> dict:
            return {"prefix": prefix, "keys": backend.keys(prefix=prefix)}

        @router.get("/kv/{key}")
        def get_value(key: str) -> dict:
            redirect = owner_redirect(key)
            if redirect:
                return redirect

            value = backend.get(key)
            if value is None:
                raise HTTPException(status_code=404, detail="key_not_found")
            return {"key": key, "value": value}

        @router.put("/kv/{key}")
        def put_value(key: str, body: dict) -> dict:
            redirect = owner_redirect(key)
            if redirect:
                return redirect

            if "value" not in body:
                raise HTTPException(status_code=400, detail="missing_value")
            backend.put(key, body["value"])
            return {"key": key, "stored": True}

        @router.delete("/kv/{key}")
        def delete_value(key: str) -> dict:
            redirect = owner_redirect(key)
            if redirect:
                return redirect

            backend.delete(key)
            return {"key": key, "deleted": True}

        app.include_router(router)


def get_module() -> Module:
    return KvStoreModule()
