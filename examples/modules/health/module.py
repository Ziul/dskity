from __future__ import annotations

from dataclasses import dataclass

import httpx
from fastapi import APIRouter, Request, HTTPException

from dskity import Module, ModuleMeta, DSkitySettings, TransportClients


@dataclass(frozen=True)
class HealthModule(Module):
    meta: ModuleMeta = ModuleMeta(name="health", base_path="/health")

    def register(self, clients: TransportClients, config: DSkitySettings) -> None:
        router = APIRouter(prefix=self.meta.base_path, tags=[self.meta.name])
        # Capture logger from app.state
        logger = getattr(clients.http.state, "logger", None)
        if not logger:
            import logging
            logger = logging.getLogger(__name__)
        logger.name = f"{logger.name}.health"

        @router.get("/live")
        def live() -> dict:
            return {"status": "ok"}

        @router.get("/ready")
        def ready() -> dict:
            return {"status": "ok"}

        @router.get("/fatorial/{number}")
        async def fatorial(number: int, request: Request) -> int:
            if not isinstance(number, int) or number < 0:
                logger.error(f"Invalid input for fatorial: {number}")
                raise HTTPException(status_code=400, detail="Invalid input: number must be a positive integer")

            logger.info(f"Received fatorial request for number={number}")
            echo = clients.http.modules.get("health")

            logger.debug(
                f"Fatorial called with number={number}, echo service at {echo}"
            )
            if number == 0 or number == 1:
                return 1

            url = str(echo) + f"/fatorial/{number - 1}"

            # Propagate x-request-id for tracking
            headers = {"x-request-id": request.state.request_id}
            logger.debug(f"Calling {url} with headers {headers}")

            try:
                async with httpx.AsyncClient(timeout=200.0) as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code != 200:
                        logger.error(f"Error response from echo service: {resp.status_code} - {resp.text}")
                        raise HTTPException(status_code=502, detail=f"fatorial_request_failed: echo service returned status code {resp.status_code}")

                result = resp.json()
                return number * result
            except httpx.HTTPError as e:
                raise HTTPException(
                    status_code=502, detail=f"fatorial_request_failed: {e}"
                ) from e

        clients.http.include_router(router)


def get_module() -> Module:
    return HealthModule()
