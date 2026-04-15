"""Kafka connector using aiokafka (async producer/consumer).

Requires the ``kafka`` extra: ``pip install dagloom[kafka]``

Example::

    config = ConnectionConfig(host="localhost", port=9092)
    async with KafkaConnector(config) as kafka:
        await kafka.execute("send", topic="events", value=b'{"event": "click"}')
        messages = await kafka.execute(
            "consume", topic="events", group_id="my-group", max_messages=10
        )
"""

from __future__ import annotations

import logging
from typing import Any

from dagloom.connectors.base import BaseConnector, ConnectionConfig

logger = logging.getLogger(__name__)


class KafkaConnector(BaseConnector):
    """Kafka async connector using aiokafka.

    Creates an ``AIOKafkaProducer`` on connect. For consuming, a temporary
    ``AIOKafkaConsumer`` is created per ``consume`` operation.

    Args:
        config: Connection configuration.
            ``config.host`` is the bootstrap server(s), comma-separated for multiple.
    """

    def __init__(self, config: ConnectionConfig) -> None:
        if config.port == 0:
            config.port = 9092
        super().__init__(config)
        self._producer: Any = None

    def _bootstrap_servers(self) -> str:
        """Build the bootstrap server string."""
        host = self.config.host
        # If host already contains port (e.g., "broker1:9092,broker2:9092"), use as-is.
        if ":" in host:
            return host
        return f"{host}:{self.config.port}"

    async def connect(self) -> None:
        """Create and start an aiokafka producer."""
        try:
            from aiokafka import AIOKafkaProducer  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "aiokafka is required for KafkaConnector. "
                "Install it with: pip install dagloom[kafka]"
            ) from exc

        bootstrap = self._bootstrap_servers()
        ssl_context = self.config.extra.get("ssl_context")

        self._producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap,
            request_timeout_ms=int(self.config.timeout * 1000),
            security_protocol="SSL" if self.config.ssl else "PLAINTEXT",
            ssl_context=ssl_context,
        )
        await self._producer.start()
        self._connected = True
        logger.info("Kafka producer connected: %s", bootstrap)

    async def disconnect(self) -> None:
        """Stop the producer."""
        if self._producer:
            await self._producer.stop()
            self._producer = None
        self._connected = False
        logger.info("Kafka producer disconnected.")

    async def health_check(self) -> bool:
        """Check if the producer is alive by inspecting its internal state."""
        if not self._producer:
            return False
        try:
            # partitions_for returns None if topic doesn't exist,
            # but the call itself validates broker connectivity.
            await self._producer.partitions_for("__consumer_offsets")
            return True
        except Exception:
            return False

    async def execute(self, operation: str, **kwargs: Any) -> Any:
        """Execute a Kafka operation.

        Args:
            operation: Operation name — ``send`` or ``consume``.
            **kwargs:
                For ``send``:
                    - topic (str): Target topic (required).
                    - value (bytes): Message value (required).
                    - key (bytes | None): Optional message key.
                    - partition (int | None): Optional partition number.
                    - headers (list | None): Optional message headers.
                For ``consume``:
                    - topic (str): Topic to consume from (required).
                    - group_id (str): Consumer group ID (default: ``"dagloom-temp"``).
                    - max_messages (int): Max messages to read (default: 10).
                    - timeout (float): Poll timeout in seconds (default: 5.0).

        Returns:
            For ``send``: ``RecordMetadata`` dict (topic, partition, offset).
            For ``consume``: List of message dicts.

        Raises:
            ConnectionError: If not connected (for send).
            ValueError: If operation is unknown or required args are missing.
        """
        if operation == "send":
            return await self._send(**kwargs)
        if operation == "consume":
            return await self._consume(**kwargs)
        raise ValueError(f"Unknown Kafka operation: {operation!r}")

    async def _send(self, **kwargs: Any) -> dict[str, Any]:
        """Produce a message to Kafka."""
        if not self._producer:
            raise ConnectionError("Not connected. Call connect() first.")

        topic = kwargs.get("topic")
        if not topic:
            raise ValueError("'topic' is required for send operation.")

        value = kwargs.get("value", b"")
        key = kwargs.get("key")
        partition = kwargs.get("partition")
        headers = kwargs.get("headers")

        record = await self._producer.send_and_wait(
            topic,
            value=value,
            key=key,
            partition=partition,
            headers=headers,
        )
        return {
            "topic": record.topic,
            "partition": record.partition,
            "offset": record.offset,
        }

    async def _consume(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Consume messages from Kafka using a temporary consumer."""
        try:
            from aiokafka import AIOKafkaConsumer  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "aiokafka is required for KafkaConnector. "
                "Install it with: pip install dagloom[kafka]"
            ) from exc

        topic = kwargs.get("topic")
        if not topic:
            raise ValueError("'topic' is required for consume operation.")

        group_id = kwargs.get("group_id", "dagloom-temp")
        max_messages = kwargs.get("max_messages", 10)
        timeout_ms = int(kwargs.get("timeout", 5.0) * 1000)
        bootstrap = self._bootstrap_servers()

        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=bootstrap,
            group_id=group_id,
            auto_offset_reset="earliest",
            consumer_timeout_ms=timeout_ms,
            security_protocol="SSL" if self.config.ssl else "PLAINTEXT",
        )
        await consumer.start()
        messages: list[dict[str, Any]] = []
        try:
            async for msg in consumer:
                messages.append(
                    {
                        "topic": msg.topic,
                        "partition": msg.partition,
                        "offset": msg.offset,
                        "key": msg.key,
                        "value": msg.value,
                        "timestamp": msg.timestamp,
                    }
                )
                if len(messages) >= max_messages:
                    break
        finally:
            await consumer.stop()

        return messages
