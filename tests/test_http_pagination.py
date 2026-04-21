"""Tests for HTTPConnector pagination (FB-007).

Covers:
- page_number strategy: basic, empty first page, partial last page
- link_header strategy: GitHub-style Link header following
- cursor strategy: cursor-based pagination from response body
- Error cases: unknown strategy, not connected
- Helper: _parse_link_next
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dagloom.connectors.base import ConnectionConfig
from dagloom.connectors.http import _parse_link_next


def _make_mock_module(name: str, attrs: dict[str, Any]) -> ModuleType:
    mod = ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _mock_response(
    json_data: Any = None,
    headers: dict[str, str] | None = None,
    status_code: int = 200,
) -> MagicMock:
    """Build a fake httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {"content-type": "application/json"}
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


class TestPaginatePageNumber:
    """Tests for page_number pagination strategy."""

    @pytest.fixture(autouse=True)
    def _mock_httpx(self) -> Any:  # type: ignore[misc]
        self.mock_client = MagicMock()
        self.mock_client.head = AsyncMock(return_value=_mock_response())
        self.mock_client.aclose = AsyncMock()
        self.mock_client_cls = MagicMock(return_value=self.mock_client)
        httpx_mod = _make_mock_module("httpx", {"AsyncClient": self.mock_client_cls})
        with patch.dict(sys.modules, {"httpx": httpx_mod}):
            yield

    def _config(self) -> ConnectionConfig:
        return ConnectionConfig(host="api.example.com")

    @pytest.mark.asyncio
    async def test_page_number_basic(self) -> None:
        """Fetches multiple pages until empty page."""
        from dagloom.connectors.http import HTTPConnector

        page1 = _mock_response([{"id": 1}, {"id": 2}])
        page2 = _mock_response([{"id": 3}])
        page3 = _mock_response([])
        self.mock_client.request = AsyncMock(side_effect=[page1, page2, page3])

        conn = HTTPConnector(self._config())
        await conn.connect()
        pages = []
        async for page in conn.paginate("GET", path="/items", strategy="page_number", per_page=2):
            pages.append(page)
        assert len(pages) == 2
        assert pages[0] == [{"id": 1}, {"id": 2}]
        assert pages[1] == [{"id": 3}]

    @pytest.mark.asyncio
    async def test_page_number_empty_first_page(self) -> None:
        """Empty first page yields nothing."""
        from dagloom.connectors.http import HTTPConnector

        self.mock_client.request = AsyncMock(return_value=_mock_response([]))
        conn = HTTPConnector(self._config())
        await conn.connect()
        pages = []
        async for page in conn.paginate("GET", path="/items", strategy="page_number"):
            pages.append(page)
        assert pages == []

    @pytest.mark.asyncio
    async def test_page_number_partial_last_page(self) -> None:
        """Stops when page has fewer items than per_page."""
        from dagloom.connectors.http import HTTPConnector

        full = _mock_response([{"id": i} for i in range(5)])
        partial = _mock_response([{"id": 5}, {"id": 6}])
        self.mock_client.request = AsyncMock(side_effect=[full, partial])

        conn = HTTPConnector(self._config())
        await conn.connect()
        pages = []
        async for page in conn.paginate("GET", path="/items", strategy="page_number", per_page=5):
            pages.append(page)
        assert len(pages) == 2

    @pytest.mark.asyncio
    async def test_page_number_max_pages(self) -> None:
        """Respects max_pages limit."""
        from dagloom.connectors.http import HTTPConnector

        full = _mock_response([{"id": 1}] * 10)
        self.mock_client.request = AsyncMock(return_value=full)

        conn = HTTPConnector(self._config())
        await conn.connect()
        pages = []
        async for page in conn.paginate(
            "GET", path="/items", strategy="page_number", per_page=10, max_pages=3
        ):
            pages.append(page)
        assert len(pages) == 3


class TestPaginateLinkHeader:
    """Tests for link_header pagination strategy (GitHub-style)."""

    @pytest.fixture(autouse=True)
    def _mock_httpx(self) -> Any:  # type: ignore[misc]
        self.mock_client = MagicMock()
        self.mock_client.head = AsyncMock(return_value=_mock_response())
        self.mock_client.aclose = AsyncMock()
        self.mock_client_cls = MagicMock(return_value=self.mock_client)
        httpx_mod = _make_mock_module("httpx", {"AsyncClient": self.mock_client_cls})
        with patch.dict(sys.modules, {"httpx": httpx_mod}):
            yield

    def _config(self) -> ConnectionConfig:
        return ConnectionConfig(host="api.github.com")

    @pytest.mark.asyncio
    async def test_link_header_follows_next(self) -> None:
        """Follows Link: rel=next until no next link."""
        from dagloom.connectors.http import HTTPConnector

        page1 = _mock_response(
            [{"id": 1}],
            headers={
                "content-type": "application/json",
                "link": '<https://api.github.com/items?page=2>; rel="next"',
            },
        )
        page2 = _mock_response(
            [{"id": 2}],
            headers={"content-type": "application/json"},
        )
        self.mock_client.request = AsyncMock(side_effect=[page1, page2])

        conn = HTTPConnector(self._config())
        await conn.connect()
        pages = []
        async for page in conn.paginate("GET", path="/items", strategy="link_header", per_page=1):
            pages.append(page)
        assert len(pages) == 2

    @pytest.mark.asyncio
    async def test_link_header_no_link(self) -> None:
        """Single page when no Link header present."""
        from dagloom.connectors.http import HTTPConnector

        resp = _mock_response(
            [{"id": 1}],
            headers={"content-type": "application/json"},
        )
        self.mock_client.request = AsyncMock(return_value=resp)

        conn = HTTPConnector(self._config())
        await conn.connect()
        pages = []
        async for page in conn.paginate("GET", path="/items", strategy="link_header"):
            pages.append(page)
        assert len(pages) == 1


class TestPaginateCursor:
    """Tests for cursor-based pagination strategy."""

    @pytest.fixture(autouse=True)
    def _mock_httpx(self) -> Any:  # type: ignore[misc]
        self.mock_client = MagicMock()
        self.mock_client.head = AsyncMock(return_value=_mock_response())
        self.mock_client.aclose = AsyncMock()
        self.mock_client_cls = MagicMock(return_value=self.mock_client)
        httpx_mod = _make_mock_module("httpx", {"AsyncClient": self.mock_client_cls})
        with patch.dict(sys.modules, {"httpx": httpx_mod}):
            yield

    def _config(self) -> ConnectionConfig:
        return ConnectionConfig(host="api.example.com")

    @pytest.mark.asyncio
    async def test_cursor_basic(self) -> None:
        """Follows cursor until null."""
        from dagloom.connectors.http import HTTPConnector

        page1 = _mock_response({"data": [1, 2], "next_cursor": "abc"})
        page2 = _mock_response({"data": [3], "next_cursor": None})
        self.mock_client.request = AsyncMock(side_effect=[page1, page2])

        conn = HTTPConnector(self._config())
        await conn.connect()
        pages = []
        async for page in conn.paginate("GET", path="/items", strategy="cursor"):
            pages.append(page)
        assert len(pages) == 2
        assert pages[0] == [1, 2]
        assert pages[1] == [3]

    @pytest.mark.asyncio
    async def test_cursor_custom_field(self) -> None:
        """Custom cursor_field and cursor_param."""
        from dagloom.connectors.http import HTTPConnector

        page1 = _mock_response({"items": ["a"], "token": "xyz"})
        page2 = _mock_response({"items": ["b"], "token": ""})
        self.mock_client.request = AsyncMock(side_effect=[page1, page2])

        conn = HTTPConnector(self._config())
        await conn.connect()
        pages = []
        async for page in conn.paginate(
            "GET",
            path="/items",
            strategy="cursor",
            cursor_field="token",
            cursor_param="next_token",
        ):
            pages.append(page)
        assert len(pages) == 2


class TestPaginateErrors:
    """Tests for pagination error handling."""

    @pytest.fixture(autouse=True)
    def _mock_httpx(self) -> Any:  # type: ignore[misc]
        self.mock_client = MagicMock()
        self.mock_client.aclose = AsyncMock()
        self.mock_client_cls = MagicMock(return_value=self.mock_client)
        httpx_mod = _make_mock_module("httpx", {"AsyncClient": self.mock_client_cls})
        with patch.dict(sys.modules, {"httpx": httpx_mod}):
            yield

    @pytest.mark.asyncio
    async def test_unknown_strategy(self) -> None:
        """Unknown strategy raises ValueError."""
        from dagloom.connectors.http import HTTPConnector

        conn = HTTPConnector(ConnectionConfig(host="x"))
        await conn.connect()
        with pytest.raises(ValueError, match="Unknown pagination strategy"):
            async for _ in conn.paginate("GET", path="/", strategy="unknown"):
                pass

    @pytest.mark.asyncio
    async def test_not_connected(self) -> None:
        """Paginate raises ConnectionError when not connected."""
        from dagloom.connectors.http import HTTPConnector

        conn = HTTPConnector(ConnectionConfig(host="x"))
        with pytest.raises(ConnectionError, match="Not connected"):
            async for _ in conn.paginate("GET", path="/"):
                pass


class TestParseLinkNext:
    """Tests for _parse_link_next helper."""

    def test_github_style(self) -> None:
        """Parses GitHub-style Link header."""
        header = (
            '<https://api.github.com/repos/org/repo/pulls?page=2>; rel="next", '
            '<https://api.github.com/repos/org/repo/pulls?page=5>; rel="last"'
        )
        assert _parse_link_next(header) == "https://api.github.com/repos/org/repo/pulls?page=2"

    def test_no_next(self) -> None:
        """Returns None when no rel=next."""
        header = '<https://example.com?page=1>; rel="prev"'
        assert _parse_link_next(header) is None

    def test_empty_header(self) -> None:
        """Returns None for empty header."""
        assert _parse_link_next("") is None
        assert _parse_link_next(None) is None  # type: ignore[arg-type]
