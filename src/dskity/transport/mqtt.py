from __future__ import annotations

from typing import Any


class MQTTClient:
    """Lightweight singleton placeholder for an MQTT client.

    This implementation intentionally avoids external dependencies. It provides
    a single shared instance that modules can use to implement MQTT-related
    integrations. Connection management is left to the consumer (module).
    """

    _instance: "MQTTClient" | None = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "MQTTClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        # State fields can be added as needed (connected flag, client lib, etc.)
        self.connected = False

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def publish(self, topic: str, payload: Any) -> None:
        # Placeholder: modules should implement real publish using a concrete client
        if not self.connected:
            raise RuntimeError("MQTTClient not connected")
        # noop for now
        return None
