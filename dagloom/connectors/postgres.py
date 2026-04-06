"""PostgreSQL connector using asyncpg.

Requires the ``connectors`` extra: ``pip install dagloom[connectors]``

Example::

    config = ConnectionConfig(host="localhost", port=5432, database="mydb", username="user", password="pass")
    async with PostgresConnector(config) as pg:
        rows = await pg.execute("SELECT * FROM users WHERE active = $1", True)
"""

from __future__ import annotations

import logging
from typing import Any

from dagloom.connectors.base import BaseConnector, ConnectionConfig

logger = logging.getLogger(__name__)


class PostgresConnector(BaseConnector):
    """PostgreSQL async connector using asyncpg.

    Args:
        config: Connection configuration (host, port, database, credentials).
    """

    def __init__(self, config: ConnectionConfig) -> None:
        if config.port == 0:
            config.port = 5432
        super().__init__(config)
        self._pool: Any = None

    async def connect(self) -> None:
        """Create an asyncpg connection pool."""
        try:
            import asyncpg  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "asyncpg is required for PostgresConnector. "
                "Install it with: pip install dagloom[connectors]"
            ) from exc

        self._pool = await asyncpg.create_pool(
            host=self.config.host,
            port=self.config.port,
            user=self.config.username,
            password=self.config.password,
            database=self.config.database,
            ssl=self.config.ssl if self.config.ssl else None,
            min_size=1,
            max_size=self.config.pool_size,
            timeout=self.config.timeout,
        )
        self._connected = True
        logger.info("PostgreSQL connected: %s:%d/%s", self.config.host, self.config.port, self.config.database)

    async def disconnect(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
        self._connected = False
        logger.info("PostgreSQL disconnected.")

    async def health_check(self) -> bool:
        """Verify the connection is alive with a simple query."""
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    async def execute(self, query: str, *args: Any, **kwargs: Any) -> Any:
        """Execute a SQL query and return rows.

        Args:
            query: A parameterized SQL query (use $1, $2, ... for params).
            *args: Query parameter values.

        Returns:
            A list of Record objects.
        """
        if not self._pool:
            raise ConnectionError("Not connected. Call connect() first.")
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def execute_one(self, query: str, *args: Any) -> Any:
        """Execute and return a single row."""
        if not self._pool:
            raise ConnectionError("Not connected.")
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def execute_val(self, query: str, *args: Any) -> Any:
        """Execute and return a single scalar value."""
        if not self._pool:
            raise ConnectionError("Not connected.")
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *args)
