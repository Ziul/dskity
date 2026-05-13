"""MQTT client singleton for Biostation API."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable
from concurrent.futures import Future

try:
    import paho.mqtt.client as mqtt
    HAS_PAHO = True
except ImportError:
    HAS_PAHO = False
    mqtt = None

from dskity.config.settings import MQTTSettings

logger = logging.getLogger(__name__)


def _reason_code_value(reason_code) -> int | None:
    value = getattr(reason_code, "value", reason_code)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

# Global singleton instance
_mqtt_client_instance: MQTTClient | None = None
_mqtt_client_lock = asyncio.Lock()


class MQTTClient:
    """MQTT client wrapper using paho-mqtt library.
    
    Implements singleton pattern for connection management.
    Supports callbacks for message reception and connection state changes.
    """

    def __init__(self, config: MQTTSettings):
        """Initialize MQTT client.
        
        Args:
            config: MQTTSettings with broker, port, credentials, etc.
        """
        self.config = config
        self.client = None
        self.is_connected = False
        self.message_handlers: dict[str, list[Callable]] = {}
        self._connect_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._reconnect_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        if not HAS_PAHO:
            raise ImportError(
                "paho-mqtt is not installed. "
                "Install it with: uv add paho-mqtt"
            )

    async def start(self) -> None:
        """Start MQTT connection manager.

        Behavior:
        - Tries to connect immediately.
        - Keeps retrying periodically while enabled and disconnected.
        """
        if not self.config.enabled:
            logger.debug("MQTT is disabled in configuration")
            return

        # Capture application event loop. MQTT callbacks run in paho thread,
        # so async handlers must be marshaled back to this loop.
        self._loop = asyncio.get_running_loop()

        self._stop_event.clear()

        # Immediate first attempt.
        try:
            await self.connect()
        except Exception as e:
            logger.warning("Initial MQTT connect failed, will retry periodically: %s", e)

        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Background loop to keep MQTT connected."""
        interval = max(int(getattr(self.config, "reconnect_interval_seconds", 10)), 1)

        while not self._stop_event.is_set():
            if not self.is_connected:
                try:
                    await self.connect()
                except Exception as e:
                    logger.warning("MQTT reconnect attempt failed: %s", e)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except TimeoutError:
                continue

    async def connect(self) -> None:
        """Establish connection to MQTT broker.
        
        Raises:
            RuntimeError: If connection fails or MQTT is disabled.
        """
        if not self.config.enabled:
            logger.warning("MQTT is disabled in configuration")
            return

        if mqtt is None:
            raise ImportError("paho-mqtt is not installed")

        async with self._connect_lock:
            if self.is_connected:
                logger.debug("MQTT client already connected")
                return

            try:
                # Clean previous client (if any)
                if self.client is not None:
                    try:
                        self.client.loop_stop()
                    except Exception:
                        pass
                    try:
                        self.client.disconnect()
                    except Exception:
                        pass

                # Create client instance
                self.client = mqtt.Client(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id=self.config.client_id,
                )

                # Set callbacks
                self.client.on_connect = self._on_connect
                self.client.on_disconnect = self._on_disconnect
                self.client.on_message = self._on_message

                # Set credentials if provided
                if self.config.username and self.config.password:
                    self.client.username_pw_set(self.config.username, self.config.password)

                # Connect to broker
                # Extract hostname from broker URL (mqtt://host or mqtt+tls://host)
                broker_url = self.config.broker
                if "://" in broker_url:
                    broker_host = broker_url.split("://", maxsplit=1)[1]
                else:
                    broker_host = broker_url

                # Remove path, if provided in URL (e.g. mqtt://host/path)
                broker_host = broker_host.split("/", maxsplit=1)[0]

                logger.debug(
                    "Connecting to MQTT broker at %s:%d (client_id=%s)",
                    broker_host,
                    self.config.port,
                    self.config.client_id,
                )

                self.client.connect(
                    broker_host,
                    self.config.port,
                    keepalive=self.config.keepalive,
                )

                # Start network loop
                self.client.loop_start()

                # Wait a bit for connection to establish
                await asyncio.sleep(0.5)

                if not self.is_connected:
                    raise RuntimeError("Failed to connect to MQTT broker")

                logger.debug("Successfully connected to MQTT broker")

            except Exception as e:
                logger.error("MQTT connection error: %s", e)
                self.is_connected = False
                raise

    async def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        self._stop_event.set()

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        self._reconnect_task = None

        try:
            if self.client:
                self.client.loop_stop()
                self.client.disconnect()
                self.is_connected = False
                logger.debug("Disconnected from MQTT broker")
        except Exception as e:
            logger.error("MQTT disconnection error: %s", e)

    async def publish(self, topic: str, payload: str | bytes, qos: int = 0) -> None:
        """Publish message to MQTT topic.
        
        Args:
            topic: MQTT topic
            payload: Message payload (string or bytes)
            qos: Quality of Service (0, 1, or 2)
        """
        if not self.is_connected:
            raise RuntimeError("MQTT client not connected")

        if not self.client:
            raise RuntimeError("MQTT client not initialized")

        try:
            self.client.publish(topic, payload, qos=qos)
            logger.debug("Published message to topic %s", topic)
        except Exception as e:
            logger.error("Failed to publish MQTT message: %s", e)
            raise

    async def subscribe(self, topic: str, qos: int = 0) -> None:
        """Subscribe to MQTT topic.
        
        Args:
            topic: MQTT topic (supports wildcards like topic/+/subtopic)
            qos: Quality of Service (0, 1, or 2)
        """
        if not self.is_connected:
            raise RuntimeError("MQTT client not connected")

        if not self.client:
            raise RuntimeError("MQTT client not initialized")

        try:
            self.client.subscribe(topic, qos=qos)
            logger.debug("Subscribed to topic %s", topic)
        except Exception as e:
            logger.error("Failed to subscribe to MQTT topic: %s", e)
            raise

    def add_message_handler(self, topic: str, handler: Callable) -> None:
        """Register a callback for messages on a specific topic.
        
        Args:
            topic: MQTT topic pattern
            handler: Async callable(topic, payload, properties) or sync callable(topic, payload)
        """
        if topic not in self.message_handlers:
            self.message_handlers[topic] = []
        self.message_handlers[topic].append(handler)
        logger.debug("Registered message handler for topic %s", topic)

    def _on_connect(self, client, userdata, *args, **kwargs):
        """Callback for when client connects to broker.

        Paho may call this with different signatures depending on
        callback API version and MQTT protocol version. Accept
        variable args and extract the reason code robustly.
        """
        # Possible forms:
        # - (client, userdata, flags, reason_code)
        # - (client, userdata, flags, reason_code, properties)
        # - kwargs may contain 'rc' or 'reason_code' or 'reasonCode'
        reason_code = None
        if "reason_code" in kwargs:
            reason_code = kwargs.get("reason_code")
        elif "rc" in kwargs:
            reason_code = kwargs.get("rc")
        elif "reasonCode" in kwargs:
            reason_code = kwargs.get("reasonCode")
        elif len(args) >= 2:
            # flags, reason_code[, properties]
            reason_code = args[1]
        elif len(args) == 1:
            # Some variants may pass only rc as single arg
            reason_code = args[0]

        if _reason_code_value(reason_code) == 0:
            logger.debug("MQTT client connected successfully")
            self.is_connected = True

            # Re-subscribe to configured topics
            for topic in self.config.subscribe_topics:
                try:
                    client.subscribe(topic)
                    logger.debug("Re-subscribed to topic %s", topic)
                except Exception as e:
                    logger.error("Failed to re-subscribe to topic %s: %s", topic, e)
        else:
            logger.error("MQTT connection failed with result code %s", reason_code)
            self.is_connected = False

    def _on_disconnect(self, client, userdata, *args, **kwargs):
        """Callback for when client disconnects from broker.

        Accept variable args to be compatible with paho-mqtt calling
        conventions across versions (MQTT v3/v5 and different callback
        API shapes).
        """
        self.is_connected = False

        # Extract reason code similarly to _on_connect
        reason_code = None
        if "reason_code" in kwargs:
            reason_code = kwargs.get("reason_code")
        elif "rc" in kwargs:
            reason_code = kwargs.get("rc")
        elif "reasonCode" in kwargs:
            reason_code = kwargs.get("reasonCode")
        elif len(args) >= 1:
            # common forms: (reason_code) or (reason_code, properties)
            reason_code = args[0]

        if _reason_code_value(reason_code) not in (0, None):
            logger.warning("Unexpected MQTT disconnection with result code %s", reason_code)
        else:
            logger.debug("MQTT client disconnected")

    def _on_message(self, client, userdata, msg):
        """Callback for when message is received."""
        topic = msg.topic
        payload = msg.payload.decode("utf-8") if isinstance(msg.payload, bytes) else msg.payload

        logger.debug("Received MQTT message on topic %s", topic)

        # Call registered handlers
        if topic in self.message_handlers:
            for handler in self.message_handlers[topic]:
                try:
                    # Check if handler is async
                    if asyncio.iscoroutinefunction(handler):
                        self._schedule_coroutine(handler(topic, payload))
                    else:
                        handler(topic, payload)
                except Exception as e:
                    logger.error("Error in MQTT message handler: %s", e)

        # Call handlers for wildcard patterns
        for pattern in self.message_handlers:
            if pattern != topic and _topic_matches(topic, pattern):
                for handler in self.message_handlers[pattern]:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            self._schedule_coroutine(handler(topic, payload))
                        else:
                            handler(topic, payload)
                    except Exception as e:
                        logger.error("Error in MQTT wildcard handler: %s", e)

    def _schedule_coroutine(self, coro) -> None:
        """Schedule coroutine from MQTT callback thread into app event loop."""
        if self._loop is None or self._loop.is_closed():
            logger.error("Error in MQTT message handler: no running event loop")
            return

        try:
            future: Future = asyncio.run_coroutine_threadsafe(coro, self._loop)

            def _done(f: Future) -> None:
                try:
                    f.result()
                except Exception as e:  # pragma: no cover
                    logger.error("Error in MQTT async handler execution: %s", e)

            future.add_done_callback(_done)
        except Exception as e:
            logger.error("Error scheduling MQTT async handler: %s", e)


def _topic_matches(topic: str, pattern: str) -> bool:
    """Check if topic matches MQTT pattern with wildcards.
    
    Supports:
    - `+`: Matches exactly one level
    - `#`: Matches remaining levels (only at end)
    
    Args:
        topic: Actual MQTT topic (e.g., "sensor/temperature/room1")
        pattern: Pattern with wildcards (e.g., "sensor/+/room1", "sensor/#")
    
    Returns:
        True if topic matches pattern
    """
    topic_parts = topic.split("/")
    pattern_parts = pattern.split("/")

    for i, part in enumerate(pattern_parts):
        if part == "#":
            # Matches all remaining levels (must be at end)
            return True
        elif part == "+":
            # Matches exactly one level
            if i >= len(topic_parts):
                return False
        else:
            # Exact match required
            if i >= len(topic_parts) or topic_parts[i] != part:
                return False

    return len(topic_parts) == len(pattern_parts)


async def get_mqtt_client(config: MQTTSettings) -> MQTTClient:
    """Get or create MQTT client singleton.
    
    This function implements the singleton pattern, ensuring only one
    MQTT client instance exists per application lifetime.
    
    Args:
        config: MQTT configuration
    
    Returns:
        MQTTClient singleton instance
    """
    global _mqtt_client_instance

    if _mqtt_client_instance is not None:
        return _mqtt_client_instance

    async with _mqtt_client_lock:
        # Double-check pattern
        if _mqtt_client_instance is not None:
            return _mqtt_client_instance

        logger.debug("Creating MQTT client singleton instance")
        _mqtt_client_instance = MQTTClient(config)
        return _mqtt_client_instance


async def shutdown_mqtt_client() -> None:
    """Shutdown and cleanup MQTT client singleton."""
    global _mqtt_client_instance

    if _mqtt_client_instance is None:
        return

    async with _mqtt_client_lock:
        if _mqtt_client_instance is not None:
            await _mqtt_client_instance.disconnect()
            _mqtt_client_instance = None
            logger.debug("MQTT client singleton shutdown")
