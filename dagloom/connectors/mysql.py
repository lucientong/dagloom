"""MySQL connector using aiomysql.

Requires the ``connectors`` extra: ``pip install dagloom[connectors]``

Example::

    config = ConnectionConfig(
        host="localhost", port=3306, database="mydb",
        username="root", password="pass"
    )
    async with MySQLConnector(config) as mysql:
        rows = await mysql.execute("SELECT * FROM users WHERE active = %s", (True,))
"""

from __future__ import annotations

import logging
from typing import Any

from dagloom.connectors.base import BaseConnector, ConnectionConfig

logger = logging.getLogger(__name__)


class MySQLConnector(BaseConnector):
    """MySQL async connector using aiomysql.

    Args:
        config: Connection configuration.
    """

    def __init__(self, config: ConnectionConfig) -> None:
        if config.port == 0:
            config.port = 3306
        super().__init__(config)
        self._pool: Any = None

    async def connect(self) -> None:
        """Create an aiomysql connection pool."""
        try:
            import aiomysql  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "aiomysql is required for MySQLConnector. "
                "Install it with: pip install dagloom[connectors]"
            ) from exc

        self._pool = await aiomysql.create_pool(
            host=self.config.host,
            port=self.config.port,
            user=self.config.username,
            password=self.config.password,
            db=self.config.database,
            minsize=1,
            maxsize=self.config.pool_size,
            connect_timeout=int(self.config.timeout),
        )
        self._connected = True
        logger.info(
            "MySQL connected: %s:%d/%s", self.config.host, self.config.port, self.config.database
        )

    async def disconnect(self) -> None:
        """Close the connection pool."""
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
        self._connected = False
        logger.info("MySQL disconnected.")

    async def health_check(self) -> bool:
        """Verify the connection is alive."""
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn, conn.cursor() as cur:
                await cur.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def execute(self, query: str, *args: Any, **kwargs: Any) -> Any:
        """Execute a SQL query and return rows.

        Args:
            query: A parameterized SQL query (use %s for params).
            *args: Query parameter values.

        Returns:
            A list of tuple rows.
        """
        if not self._pool:
            raise ConnectionError("Not connected. Call connect() first.")
        async with self._pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(query, args or None)
            return await cur.fetchall()
