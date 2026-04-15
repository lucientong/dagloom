"""Redis connector using redis-py (async mode).

Requires the ``redis`` extra: ``pip install dagloom[redis]``

Example::

    config = ConnectionConfig(host="localhost", port=6379, password="secret")
    async with RedisConnector(config) as r:
        await r.execute("set", "mykey", "myvalue")
        value = await r.execute("get", "mykey")
"""

from __future__ import annotations

import logging
from typing import Any

from dagloom.connectors.base import BaseConnector, ConnectionConfig

logger = logging.getLogger(__name__)


class RedisConnector(BaseConnector):
    """Redis async connector using redis-py.

    Args:
        config: Connection configuration (host, port, password).
            ``config.database`` is used as the Redis DB index (default 0).
    """

    def __init__(self, config: ConnectionConfig) -> None:
        if config.port == 0:
            config.port = 6379
        super().__init__(config)
        self._client: Any = None

    async def connect(self) -> None:
        """Create a Redis async client."""
        try:
            import redis.asyncio as aioredis  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "redis is required for RedisConnector. Install it with: pip install dagloom[redis]"
            ) from exc

        db_index = int(self.config.database) if self.config.database else 0
        password = self.config.password or self.config.extra.get("password")

        self._client = aioredis.Redis(
            host=self.config.host,
            port=self.config.port,
            db=db_index,
            password=password or None,
            ssl=self.config.ssl,
            socket_timeout=self.config.timeout,
            socket_connect_timeout=self.config.timeout,
            max_connections=self.config.pool_size,
            decode_responses=True,
        )
        self._connected = True
        logger.info("Redis connected: %s:%d/%d", self.config.host, self.config.port, db_index)

    async def disconnect(self) -> None:
        """Close the Redis client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False
        logger.info("Redis disconnected.")

    async def health_check(self) -> bool:
        """Ping the Redis server."""
        if not self._client:
            return False
        try:
            return await self._client.ping()
        except Exception:
            return False

    async def execute(self, command: str, *args: Any, **kwargs: Any) -> Any:
        """Execute a Redis command.

        Args:
            command: Redis command name (e.g., ``get``, ``set``, ``delete``,
                ``hget``, ``hset``, ``lpush``, ``rpush``, ``lrange``,
                ``keys``, ``exists``, ``expire``, ``ttl``).
            *args: Positional arguments for the command.
            **kwargs: Keyword arguments for the command.

        Returns:
            Command result (type depends on the command).

        Raises:
            ConnectionError: If not connected.
            ValueError: If the command is not supported.
        """
        if not self._client:
            raise ConnectionError("Not connected. Call connect() first.")

        cmd = command.lower()
        method = getattr(self._client, cmd, None)
        if method is None:
            raise ValueError(f"Unsupported Redis command: {command!r}")

        return await method(*args, **kwargs)
