from __future__ import annotations

from dataclasses import dataclass

import logging
import httpx
from fastapi import APIRouter, Request, HTTPException

from dskity import Module, ModuleMeta, DSkitySettings, TransportClients


@dataclass(frozen=True)
class HealthModule(Module):
    meta: ModuleMeta = ModuleMeta(name="health", base_path="/health")

    def register(self, clients: TransportClients, config: DSkitySettings) -> None:
        router = APIRouter(prefix=self.meta.base_path, tags=[self.meta.name])

        @router.get("/live")
        def live() -> dict:
            return {"status": "ok"}

        @router.get("/ready")
        def ready() -> dict:
            return {"status": "ok"}

        @router.get("/fatorial/{number}")
        async def fatorial(number: int, request: Request) -> int:

            echo = clients.http.modules.get("echo")

            logging.info(
                f"Fatorial called with number={number}, echo service at {echo}"
            )
            if number == 0 or number == 1:
                return 1

            url = str(echo) + f"/fatorial/{number - 1}"

            # propagate x-request-id for tracking
            headers = {"x-request-id": request.state.request_id}
            logging.info(f"Calling {url} with headers {headers}")

            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.get(url, headers=headers)

                result = resp.json()
                return number * result
            except httpx.HTTPError as e:
                raise HTTPException(
                    status_code=502, detail=f"fatorial_request_failed: {e}"
                ) from e

        clients.http.include_router(router)


def get_module() -> Module:
    return HealthModule()
