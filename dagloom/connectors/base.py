"""Base connector — abstract interface for data source connectors.

All connectors (PostgreSQL, MySQL, S3, HTTP) inherit from ``BaseConnector``
and implement the abstract methods for connection management, health checks,
and query/operation execution.

Example::

    class MyConnector(BaseConnector):
        async def connect(self) -> None: ...
        async def disconnect(self) -> None: ...
        async def health_check(self) -> bool: ...
        async def execute(self, query: str, **kwargs) -> Any: ...
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ConnectionConfig:
    """Common connection configuration.

    Attributes:
        host: Server hostname or IP.
        port: Server port.
        username: Authentication username.
        password: Authentication password.
        database: Database name or bucket name.
        ssl: Whether to use SSL/TLS.
        pool_size: Maximum connection pool size.
        timeout: Connection timeout in seconds.
        extra: Additional driver-specific parameters.
    """

    host: str = "localhost"
    port: int = 0
    username: str = ""
    password: str = ""
    database: str = ""
    ssl: bool = False
    pool_size: int = 5
    timeout: float = 30.0
    extra: dict[str, Any] = field(default_factory=dict)


class BaseConnector(ABC):
    """Abstract base class for data source connectors.

    Provides a standard interface for connecting to external data
    sources with connection pooling, credential management, and
    health checking.

    Args:
        config: Connection configuration.
    """

    def __init__(self, config: ConnectionConfig) -> None:
        self.config = config
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Whether the connector is currently connected."""
        return self._connected

    @abstractmethod
    async def connect(self) -> None:
        """Establish a connection to the data source.

        Raises:
            ConnectionError: If the connection fails.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection and release resources."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Check whether the connection is alive.

        Returns:
            True if the connection is healthy.
        """

    @abstractmethod
    async def execute(self, query: str, **kwargs: Any) -> Any:
        """Execute a query or operation against the data source.

        Args:
            query: The SQL query, API endpoint, or S3 key.
            **kwargs: Additional parameters.

        Returns:
            Query results (format depends on the connector).
        """

    async def __aenter__(self) -> BaseConnector:
        """Async context manager entry — connect."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit — disconnect."""
        await self.disconnect()

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"host={self.config.host!r}, "
            f"port={self.config.port}, "
            f"connected={self._connected})"
        )
