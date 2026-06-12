"""In-process event bus for decoupled inter-module communication."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

Handler = Callable[..., Awaitable[None]]


class EventBus:
    """Simple async pub/sub event bus for module-to-module communication.

    All handlers for an event are called concurrently via :func:`asyncio.gather`.
    Individual handler errors are caught and logged without cancelling other handlers.

    Example usage::

        bus = EventBus()

        async def on_order_created(data):
            print("order created:", data)

        bus.on("order.created", on_order_created)

        await bus.emit("order.created", {"id": 1})
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def on(self, event: str, handler: Handler) -> None:
        """Register *handler* for *event*. No-op if already registered."""
        if handler not in self._handlers[event]:
            self._handlers[event].append(handler)
            logger.debug("EventBus: registered handler %r for event %r", handler, event)

    def off(self, event: str, handler: Handler) -> None:
        """Unregister *handler* from *event*. No-op if not registered."""
        try:
            self._handlers[event].remove(handler)
            logger.debug("EventBus: removed handler %r from event %r", handler, event)
        except ValueError:
            pass

    async def emit(self, event: str, data: Any = None) -> int:
        """Emit *event* to all registered handlers concurrently.

        Args:
            event: Event name to emit.
            data: Arbitrary payload forwarded to each handler.

        Returns:
            Number of handlers that were invoked.
        """
        handlers = list(self._handlers.get(event, []))
        if not handlers:
            logger.debug("EventBus: no handlers for event %r", event)
            return 0

        async def _safe_call(h: Handler) -> None:
            try:
                await h(data)
            except Exception:
                logger.exception(
                    "EventBus: handler %r raised an error for event %r",
                    h,
                    event,
                )

        await asyncio.gather(*(_safe_call(h) for h in handlers))
        return len(handlers)

    def list_events(self) -> list[str]:
        """Return all event names with at least one registered handler."""
        return [event for event, handlers in self._handlers.items() if handlers]

    def handler_count(self, event: str) -> int:
        """Return the number of handlers registered for *event*."""
        return len(self._handlers.get(event, []))
