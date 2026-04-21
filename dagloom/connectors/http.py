"""HTTP API connector using httpx.

Requires the ``connectors`` extra: ``pip install dagloom[connectors]``

Example::

    config = ConnectionConfig(host="api.example.com", extra={"base_url": "https://api.example.com/v1"})
    async with HTTPConnector(config) as http:
        data = await http.execute("GET", path="/users", params={"active": True})

        # Paginated fetch (yields pages until exhausted):
        all_items = []
        async for page in http.paginate("GET", path="/users", strategy="page_number"):
            all_items.extend(page)
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from dagloom.connectors.base import BaseConnector, ConnectionConfig

logger = logging.getLogger(__name__)

# Supported pagination strategies.
PAGINATION_STRATEGIES = frozenset({"page_number", "link_header", "cursor"})


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

    async def execute_raw(self, method: str, **kwargs: Any) -> Any:
        """Execute an HTTP request and return the raw httpx Response.

        Same arguments as :meth:`execute`, but the caller gets the full
        response object (status, headers, body) for custom processing.
        """
        if not self._client:
            raise ConnectionError("Not connected. Call connect() first.")

        path = kwargs.pop("path", "/")
        resp = await self._client.request(method, path, **kwargs)
        resp.raise_for_status()
        return resp

    async def paginate(
        self,
        method: str,
        *,
        path: str = "/",
        strategy: str = "page_number",
        per_page: int = 100,
        max_pages: int = 100,
        page_param: str = "page",
        per_page_param: str = "per_page",
        cursor_param: str = "cursor",
        cursor_field: str = "next_cursor",
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        """Paginate through an HTTP API endpoint.

        Yields one page of results per iteration until exhausted or
        ``max_pages`` is reached.

        Strategies:

        - ``"page_number"`` (default): Increments a ``page`` query param
          starting at 1. Stops when a page returns an empty list or fewer
          items than ``per_page``.
        - ``"link_header"``: Follows the ``rel="next"`` URL from the
          ``Link`` response header (used by GitHub, GitLab, etc.). Stops
          when no ``next`` link is present.
        - ``"cursor"``: Reads a cursor/token from the JSON response body
          (at ``cursor_field``) and passes it as ``cursor_param`` in the
          next request. Stops when the cursor is ``None`` or empty.

        Args:
            method: HTTP method (usually ``"GET"``).
            path: URL path.
            strategy: Pagination strategy name.
            per_page: Items per page (for ``page_number`` and ``link_header``).
            max_pages: Safety limit on the number of pages to fetch.
            page_param: Query param name for page number.
            per_page_param: Query param name for per_page.
            cursor_param: Query param name for cursor value.
            cursor_field: JSON response field containing the next cursor.
            **kwargs: Additional kwargs forwarded to ``execute_raw``
                (e.g., ``params``, ``headers``).

        Yields:
            Parsed JSON response for each page (usually a list).

        Raises:
            ConnectionError: If not connected.
            ValueError: If *strategy* is not recognized.
        """
        if not self._client:
            raise ConnectionError("Not connected. Call connect() first.")
        if strategy not in PAGINATION_STRATEGIES:
            raise ValueError(
                f"Unknown pagination strategy {strategy!r}. "
                f"Choose from: {', '.join(sorted(PAGINATION_STRATEGIES))}"
            )

        if strategy == "page_number":
            async for page in self._paginate_page_number(
                method, path, per_page, max_pages, page_param, per_page_param, **kwargs
            ):
                yield page
        elif strategy == "link_header":
            async for page in self._paginate_link_header(
                method, path, per_page, max_pages, per_page_param, **kwargs
            ):
                yield page
        elif strategy == "cursor":
            async for page in self._paginate_cursor(
                method, path, max_pages, cursor_param, cursor_field, **kwargs
            ):
                yield page

    # -- Pagination strategy implementations ---------------------------------

    async def _paginate_page_number(
        self,
        method: str,
        path: str,
        per_page: int,
        max_pages: int,
        page_param: str,
        per_page_param: str,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        """Page-number pagination: ?page=1&per_page=100."""
        params = dict(kwargs.pop("params", {}) or {})
        for page_num in range(1, max_pages + 1):
            params[page_param] = page_num
            params[per_page_param] = per_page
            resp = await self.execute_raw(method, path=path, params=params, **kwargs)
            data = resp.json()
            if not data:
                return
            yield data
            if isinstance(data, list) and len(data) < per_page:
                return

    async def _paginate_link_header(
        self,
        method: str,
        path: str,
        per_page: int,
        max_pages: int,
        per_page_param: str,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        """Link-header pagination: follows rel="next" URLs (GitHub-style)."""
        params = dict(kwargs.pop("params", {}) or {})
        params[per_page_param] = per_page
        next_url: str | None = path

        for _ in range(max_pages):
            if next_url is None:
                return

            # First request uses path + params; subsequent use full URL from Link.
            if next_url == path:
                resp = await self.execute_raw(method, path=path, params=params, **kwargs)
            else:
                # next_url is a full URL; use it directly.
                resp = await self._client.request(method, next_url)
                resp.raise_for_status()

            data = resp.json()
            if not data:
                return
            yield data

            next_url = _parse_link_next(resp.headers.get("link", ""))

    async def _paginate_cursor(
        self,
        method: str,
        path: str,
        max_pages: int,
        cursor_param: str,
        cursor_field: str,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        """Cursor-based pagination: reads next_cursor from response body."""
        params = dict(kwargs.pop("params", {}) or {})
        cursor: str | None = None

        for _ in range(max_pages):
            if cursor:
                params[cursor_param] = cursor
            resp = await self.execute_raw(method, path=path, params=params, **kwargs)
            body = resp.json()

            # Extract data and cursor from response.
            if isinstance(body, dict):
                # Cursor is a field in the response object.
                cursor = body.get(cursor_field)
                # Yield the data (the whole body, or a "data"/"items" sub-key).
                data = body.get("data", body.get("items", body))
                yield data
            else:
                yield body
                return

            if not cursor:
                return


def _parse_link_next(link_header: str) -> str | None:
    """Extract the ``rel="next"`` URL from an HTTP Link header.

    Args:
        link_header: The raw ``Link`` header value.

    Returns:
        The next URL, or ``None`` if not found.
    """
    if not link_header:
        return None
    # Pattern: <URL>; rel="next"
    for part in link_header.split(","):
        match = re.search(r'<([^>]+)>;\s*rel="next"', part)
        if match:
            return match.group(1)
    return None
