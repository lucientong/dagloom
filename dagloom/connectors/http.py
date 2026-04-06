"""HTTP API connector using httpx.

Requires the ``connectors`` extra: ``pip install dagloom[connectors]``

Example::

    config = ConnectionConfig(host="api.example.com", extra={"base_url": "https://api.example.com/v1"})
    async with HTTPConnector(config) as http:
        data = await http.execute("GET", path="/users", params={"active": True})
"""

from __future__ import annotations

import logging
from typing import Any

from dagloom.connectors.base import BaseConnector, ConnectionConfig

logger = logging.getLogger(__name__)


class HTTPConnector(BaseConnector):
    """HTTP API async connector using httpx.

    Args:
        config: Connection configuration. Use ``extra`` dict for additional
                settings: ``{"base_url": "...", "headers": {...}, ...}``
    """

    def __init__(self, config: ConnectionConfig) -> None:
        super().__init__(config)
        self._client: Any = None

    async def connect(self) -> None:
        """Create an httpx async client."""
        try:
            import httpx
        except ImportError as exc:
            raise ImportError(
                "httpx is required for HTTPConnector. "
                "Install it with: pip install dagloom[connectors]"
            ) from exc

        extra = self.config.extra
        base_url = extra.get("base_url", f"https://{self.config.host}")
        headers = extra.get("headers", {})

        if self.config.username and self.config.password:
            # Basic auth.
            import base64

            credentials = base64.b64encode(
                f"{self.config.username}:{self.config.password}".encode()
            ).decode()
            headers.setdefault("Authorization", f"Basic {credentials}")

        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=self.config.timeout,
        )
        self._connected = True
        logger.info("HTTP connected: %s", base_url)

    async def disconnect(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False
        logger.info("HTTP disconnected.")

    async def health_check(self) -> bool:
        """Send a HEAD request to the base URL."""
        if not self._client:
            return False
        try:
            resp = await self._client.head("/")
            return resp.status_code < 500
        except Exception:
            return False

    async def execute(self, method: str, **kwargs: Any) -> Any:
        """Execute an HTTP request.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.).
            **kwargs:
                - path: URL path (relative to base_url).
                - params: Query parameters dict.
                - json: JSON body dict.
                - data: Form data dict.
                - headers: Extra headers dict.

        Returns:
            Parsed JSON response or response text.
        """
        if not self._client:
            raise ConnectionError("Not connected. Call connect() first.")

        path = kwargs.pop("path", "/")
        resp = await self._client.request(method, path, **kwargs)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            return resp.json()
        return resp.text
