"""Tests for PostgreSQL, MySQL, S3, and HTTP connectors.

All tests use mocks — no external services required.

Covers:
- PostgresConnector: connect, disconnect, health_check, execute, execute_one, execute_val
- MySQLConnector: connect, disconnect, health_check, execute (cursor-based)
- S3Connector: connect, disconnect, health_check, execute (get/put/delete/list)
- HTTPConnector: connect, disconnect, health_check, execute (GET/POST/PUT/DELETE)
- Common: context manager, repr, default port, import error, not-connected error
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dagloom.connectors.base import ConnectionConfig


def _make_mock_module(name: str, attrs: dict[str, Any]) -> ModuleType:
    """Create a fake module with the given attributes."""
    mod = ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


# ===========================================================================
# PostgresConnector Tests
# ===========================================================================


class TestPostgresConnector:
    """Tests for dagloom.connectors.postgres.PostgresConnector."""

    @pytest.fixture(autouse=True)
    def _mock_asyncpg(self) -> Any:  # type: ignore[misc]
        """Inject a fake asyncpg module."""
        self.mock_pool = MagicMock()
        self.mock_conn = MagicMock()
        self.mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=self.mock_conn)
        self.mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        self.mock_pool.close = AsyncMock()
        self.mock_conn.fetch = AsyncMock(return_value=[{"id": 1, "name": "test"}])
        self.mock_conn.fetchrow = AsyncMock(return_value={"id": 1})
        self.mock_conn.fetchval = AsyncMock(return_value=1)

        asyncpg_mod = _make_mock_module(
            "asyncpg", {"create_pool": AsyncMock(return_value=self.mock_pool)}
        )
        with patch.dict(sys.modules, {"asyncpg": asyncpg_mod}):
            yield

    def _config(self, **kw: Any) -> ConnectionConfig:
        return ConnectionConfig(host="localhost", database="testdb", **kw)

    @pytest.mark.asyncio
    async def test_default_port(self) -> None:
        """Default port is 5432."""
        from dagloom.connectors.postgres import PostgresConnector

        conn = PostgresConnector(self._config())
        assert conn.config.port == 5432

    @pytest.mark.asyncio
    async def test_connect_disconnect(self) -> None:
        """Connect creates pool; disconnect closes it."""
        from dagloom.connectors.postgres import PostgresConnector

        conn = PostgresConnector(self._config())
        await conn.connect()
        assert conn.is_connected

        await conn.disconnect()
        assert not conn.is_connected

    @pytest.mark.asyncio
    async def test_health_check_success(self) -> None:
        """Health check runs SELECT 1."""
        from dagloom.connectors.postgres import PostgresConnector

        conn = PostgresConnector(self._config())
        await conn.connect()
        assert await conn.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self) -> None:
        """Health check returns False when not connected."""
        from dagloom.connectors.postgres import PostgresConnector

        conn = PostgresConnector(self._config())
        assert await conn.health_check() is False

    @pytest.mark.asyncio
    async def test_execute(self) -> None:
        """Execute returns rows via conn.fetch."""
        from dagloom.connectors.postgres import PostgresConnector

        conn = PostgresConnector(self._config())
        await conn.connect()
        result = await conn.execute("SELECT * FROM users WHERE id = $1", 1)
        assert result == [{"id": 1, "name": "test"}]

    @pytest.mark.asyncio
    async def test_execute_one(self) -> None:
        """Execute_one returns a single row."""
        from dagloom.connectors.postgres import PostgresConnector

        conn = PostgresConnector(self._config())
        await conn.connect()
        result = await conn.execute_one("SELECT * FROM users WHERE id = $1", 1)
        assert result == {"id": 1}

    @pytest.mark.asyncio
    async def test_execute_val(self) -> None:
        """Execute_val returns a scalar value."""
        from dagloom.connectors.postgres import PostgresConnector

        conn = PostgresConnector(self._config())
        await conn.connect()
        result = await conn.execute_val("SELECT COUNT(*) FROM users")
        assert result == 1

    @pytest.mark.asyncio
    async def test_execute_not_connected(self) -> None:
        """Execute raises ConnectionError when not connected."""
        from dagloom.connectors.postgres import PostgresConnector

        conn = PostgresConnector(self._config())
        with pytest.raises(ConnectionError, match="Not connected"):
            await conn.execute("SELECT 1")

    @pytest.mark.asyncio
    async def test_execute_one_not_connected(self) -> None:
        """Execute_one raises ConnectionError when not connected."""
        from dagloom.connectors.postgres import PostgresConnector

        conn = PostgresConnector(self._config())
        with pytest.raises(ConnectionError, match="Not connected"):
            await conn.execute_one("SELECT 1")

    @pytest.mark.asyncio
    async def test_execute_val_not_connected(self) -> None:
        """Execute_val raises ConnectionError when not connected."""
        from dagloom.connectors.postgres import PostgresConnector

        conn = PostgresConnector(self._config())
        with pytest.raises(ConnectionError, match="Not connected"):
            await conn.execute_val("SELECT 1")

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Async context manager connects and disconnects."""
        from dagloom.connectors.postgres import PostgresConnector

        conn = PostgresConnector(self._config())
        async with conn:
            assert conn.is_connected
        assert not conn.is_connected

    def test_repr(self) -> None:
        """Repr includes class name and host."""
        from dagloom.connectors.postgres import PostgresConnector

        conn = PostgresConnector(self._config())
        assert "PostgresConnector" in repr(conn)
        assert "localhost" in repr(conn)


# ===========================================================================
# MySQLConnector Tests
# ===========================================================================


class TestMySQLConnector:
    """Tests for dagloom.connectors.mysql.MySQLConnector."""

    @pytest.fixture(autouse=True)
    def _mock_aiomysql(self) -> Any:  # type: ignore[misc]
        """Inject a fake aiomysql module."""
        self.mock_cursor = MagicMock()
        self.mock_cursor.execute = AsyncMock()
        self.mock_cursor.fetchall = AsyncMock(return_value=[(1, "test")])
        self.mock_cursor.__aenter__ = AsyncMock(return_value=self.mock_cursor)
        self.mock_cursor.__aexit__ = AsyncMock(return_value=False)

        self.mock_conn = MagicMock()
        self.mock_conn.cursor.return_value = self.mock_cursor
        self.mock_conn.__aenter__ = AsyncMock(return_value=self.mock_conn)
        self.mock_conn.__aexit__ = AsyncMock(return_value=False)

        self.mock_pool = MagicMock()
        self.mock_pool.acquire.return_value = self.mock_conn
        self.mock_pool.close = MagicMock()
        self.mock_pool.wait_closed = AsyncMock()

        aiomysql_mod = _make_mock_module(
            "aiomysql", {"create_pool": AsyncMock(return_value=self.mock_pool)}
        )
        with patch.dict(sys.modules, {"aiomysql": aiomysql_mod}):
            yield

    def _config(self, **kw: Any) -> ConnectionConfig:
        return ConnectionConfig(host="localhost", database="testdb", **kw)

    @pytest.mark.asyncio
    async def test_default_port(self) -> None:
        """Default port is 3306."""
        from dagloom.connectors.mysql import MySQLConnector

        conn = MySQLConnector(self._config())
        assert conn.config.port == 3306

    @pytest.mark.asyncio
    async def test_connect_disconnect(self) -> None:
        """Connect creates pool; disconnect closes it."""
        from dagloom.connectors.mysql import MySQLConnector

        conn = MySQLConnector(self._config())
        await conn.connect()
        assert conn.is_connected

        await conn.disconnect()
        assert not conn.is_connected

    @pytest.mark.asyncio
    async def test_health_check_success(self) -> None:
        """Health check runs SELECT 1 via cursor."""
        from dagloom.connectors.mysql import MySQLConnector

        conn = MySQLConnector(self._config())
        await conn.connect()
        assert await conn.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self) -> None:
        """Health check returns False when not connected."""
        from dagloom.connectors.mysql import MySQLConnector

        conn = MySQLConnector(self._config())
        assert await conn.health_check() is False

    @pytest.mark.asyncio
    async def test_execute(self) -> None:
        """Execute returns rows via cursor.fetchall."""
        from dagloom.connectors.mysql import MySQLConnector

        conn = MySQLConnector(self._config())
        await conn.connect()
        result = await conn.execute("SELECT * FROM users WHERE id = %s", 1)
        assert result == [(1, "test")]

    @pytest.mark.asyncio
    async def test_execute_not_connected(self) -> None:
        """Execute raises ConnectionError when not connected."""
        from dagloom.connectors.mysql import MySQLConnector

        conn = MySQLConnector(self._config())
        with pytest.raises(ConnectionError, match="Not connected"):
            await conn.execute("SELECT 1")

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Async context manager connects and disconnects."""
        from dagloom.connectors.mysql import MySQLConnector

        conn = MySQLConnector(self._config())
        async with conn:
            assert conn.is_connected
        assert not conn.is_connected

    def test_repr(self) -> None:
        """Repr includes class name."""
        from dagloom.connectors.mysql import MySQLConnector

        conn = MySQLConnector(self._config())
        assert "MySQLConnector" in repr(conn)


# ===========================================================================
# S3Connector Tests
# ===========================================================================


class TestS3Connector:
    """Tests for dagloom.connectors.s3.S3Connector."""

    @pytest.fixture(autouse=True)
    def _mock_aiobotocore(self) -> Any:  # type: ignore[misc]
        """Inject a fake aiobotocore module."""
        self.mock_client = MagicMock()
        self.mock_client.__aenter__ = AsyncMock(return_value=self.mock_client)
        self.mock_client.__aexit__ = AsyncMock(return_value=False)
        self.mock_client.list_buckets = AsyncMock(return_value={"Buckets": []})

        # Mock get_object with streaming body.
        mock_body = MagicMock()
        mock_body.read = AsyncMock(return_value=b"file-content")
        mock_body.__aenter__ = AsyncMock(return_value=mock_body)
        mock_body.__aexit__ = AsyncMock(return_value=False)
        self.mock_client.get_object = AsyncMock(return_value={"Body": mock_body})
        self.mock_client.put_object = AsyncMock(return_value={"ETag": '"abc"'})
        self.mock_client.delete_object = AsyncMock(return_value={})
        self.mock_client.list_objects_v2 = AsyncMock(
            return_value={"Contents": [{"Key": "file1.csv"}]}
        )

        self.mock_session = MagicMock()
        self.mock_session.create_client.return_value = self.mock_client

        session_mod = _make_mock_module(
            "aiobotocore.session", {"get_session": MagicMock(return_value=self.mock_session)}
        )
        aiobotocore_mod = _make_mock_module("aiobotocore", {"session": session_mod})

        with patch.dict(
            sys.modules,
            {"aiobotocore": aiobotocore_mod, "aiobotocore.session": session_mod},
        ):
            yield

    def _config(self, **kw: Any) -> ConnectionConfig:
        kw.setdefault("host", "s3.amazonaws.com")
        return ConnectionConfig(**kw)

    @pytest.mark.asyncio
    async def test_connect_disconnect(self) -> None:
        """Connect creates S3 client; disconnect closes it."""
        from dagloom.connectors.s3 import S3Connector

        conn = S3Connector(self._config())
        await conn.connect()
        assert conn.is_connected

        await conn.disconnect()
        assert not conn.is_connected

    @pytest.mark.asyncio
    async def test_health_check_success(self) -> None:
        """Health check calls list_buckets."""
        from dagloom.connectors.s3 import S3Connector

        conn = S3Connector(self._config())
        await conn.connect()
        assert await conn.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self) -> None:
        """Health check returns False when not connected."""
        from dagloom.connectors.s3 import S3Connector

        conn = S3Connector(self._config())
        assert await conn.health_check() is False

    @pytest.mark.asyncio
    async def test_execute_get(self) -> None:
        """GET operation returns file bytes."""
        from dagloom.connectors.s3 import S3Connector

        conn = S3Connector(self._config())
        await conn.connect()
        result = await conn.execute("get", bucket="my-bucket", key="file.csv")
        assert result == b"file-content"

    @pytest.mark.asyncio
    async def test_execute_put(self) -> None:
        """PUT operation uploads data."""
        from dagloom.connectors.s3 import S3Connector

        conn = S3Connector(self._config())
        await conn.connect()
        result = await conn.execute("put", bucket="my-bucket", key="f.csv", body=b"data")
        assert "ETag" in result

    @pytest.mark.asyncio
    async def test_execute_delete(self) -> None:
        """DELETE operation removes object."""
        from dagloom.connectors.s3 import S3Connector

        conn = S3Connector(self._config())
        await conn.connect()
        result = await conn.execute("delete", bucket="my-bucket", key="f.csv")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_execute_list(self) -> None:
        """LIST operation returns object list."""
        from dagloom.connectors.s3 import S3Connector

        conn = S3Connector(self._config())
        await conn.connect()
        result = await conn.execute("list", bucket="my-bucket", prefix="data/")
        assert len(result) == 1
        assert result[0]["Key"] == "file1.csv"

    @pytest.mark.asyncio
    async def test_execute_unknown_operation(self) -> None:
        """Unknown operation raises ValueError."""
        from dagloom.connectors.s3 import S3Connector

        conn = S3Connector(self._config())
        await conn.connect()
        with pytest.raises(ValueError, match="Unknown S3 operation"):
            await conn.execute("purge", bucket="b")

    @pytest.mark.asyncio
    async def test_execute_not_connected(self) -> None:
        """Execute raises ConnectionError when not connected."""
        from dagloom.connectors.s3 import S3Connector

        conn = S3Connector(self._config())
        with pytest.raises(ConnectionError, match="Not connected"):
            await conn.execute("get", bucket="b", key="k")

    @pytest.mark.asyncio
    async def test_minio_endpoint(self) -> None:
        """Localhost host uses HTTP endpoint for MinIO."""
        from dagloom.connectors.s3 import S3Connector

        conn = S3Connector(self._config(host="localhost", port=9000))
        await conn.connect()
        # Verify create_client was called (connection succeeded).
        assert conn.is_connected

    def test_repr(self) -> None:
        """Repr includes class name."""
        from dagloom.connectors.s3 import S3Connector

        conn = S3Connector(self._config())
        assert "S3Connector" in repr(conn)


# ===========================================================================
# HTTPConnector Tests
# ===========================================================================


class TestHTTPConnector:
    """Tests for dagloom.connectors.http.HTTPConnector."""

    @pytest.fixture(autouse=True)
    def _mock_httpx(self) -> Any:  # type: ignore[misc]
        """Inject a fake httpx module."""
        self.mock_response = MagicMock()
        self.mock_response.status_code = 200
        self.mock_response.headers = {"content-type": "application/json"}
        self.mock_response.json.return_value = {"data": "result"}
        self.mock_response.text = '{"data": "result"}'
        self.mock_response.raise_for_status = MagicMock()

        self.mock_client = MagicMock()
        self.mock_client.request = AsyncMock(return_value=self.mock_response)
        self.mock_client.head = AsyncMock(return_value=self.mock_response)
        self.mock_client.aclose = AsyncMock()

        self.mock_async_client_cls = MagicMock(return_value=self.mock_client)

        httpx_mod = _make_mock_module("httpx", {"AsyncClient": self.mock_async_client_cls})
        with patch.dict(sys.modules, {"httpx": httpx_mod}):
            yield

    def _config(self, **kw: Any) -> ConnectionConfig:
        kw.setdefault("host", "api.example.com")
        return ConnectionConfig(**kw)

    @pytest.mark.asyncio
    async def test_connect_disconnect(self) -> None:
        """Connect creates httpx client; disconnect closes it."""
        from dagloom.connectors.http import HTTPConnector

        conn = HTTPConnector(self._config())
        await conn.connect()
        assert conn.is_connected

        await conn.disconnect()
        assert not conn.is_connected

    @pytest.mark.asyncio
    async def test_health_check_success(self) -> None:
        """Health check sends HEAD /."""
        from dagloom.connectors.http import HTTPConnector

        conn = HTTPConnector(self._config())
        await conn.connect()
        assert await conn.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self) -> None:
        """Health check returns False when not connected."""
        from dagloom.connectors.http import HTTPConnector

        conn = HTTPConnector(self._config())
        assert await conn.health_check() is False

    @pytest.mark.asyncio
    async def test_execute_get_json(self) -> None:
        """GET returns parsed JSON."""
        from dagloom.connectors.http import HTTPConnector

        conn = HTTPConnector(self._config())
        await conn.connect()
        result = await conn.execute("GET", path="/users")
        assert result == {"data": "result"}

    @pytest.mark.asyncio
    async def test_execute_get_text(self) -> None:
        """GET returns text when content-type is not JSON."""
        from dagloom.connectors.http import HTTPConnector

        self.mock_response.headers = {"content-type": "text/plain"}

        conn = HTTPConnector(self._config())
        await conn.connect()
        result = await conn.execute("GET", path="/text")
        assert result == '{"data": "result"}'

    @pytest.mark.asyncio
    async def test_execute_post(self) -> None:
        """POST sends JSON body."""
        from dagloom.connectors.http import HTTPConnector

        conn = HTTPConnector(self._config())
        await conn.connect()
        result = await conn.execute("POST", path="/users", json={"name": "test"})
        assert result is not None
        self.mock_client.request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_not_connected(self) -> None:
        """Execute raises ConnectionError when not connected."""
        from dagloom.connectors.http import HTTPConnector

        conn = HTTPConnector(self._config())
        with pytest.raises(ConnectionError, match="Not connected"):
            await conn.execute("GET", path="/test")

    @pytest.mark.asyncio
    async def test_connect_with_basic_auth(self) -> None:
        """Basic auth header is set when username/password provided."""
        from dagloom.connectors.http import HTTPConnector

        conn = HTTPConnector(self._config(username="user", password="pass"))
        await conn.connect()
        assert conn.is_connected
        # Verify AsyncClient was created (auth headers set internally).
        self.mock_async_client_cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_with_base_url(self) -> None:
        """Base URL from extra dict is used."""
        from dagloom.connectors.http import HTTPConnector

        cfg = self._config(extra={"base_url": "https://custom.api.com/v2"})
        conn = HTTPConnector(cfg)
        await conn.connect()
        call_kwargs = self.mock_async_client_cls.call_args[1]
        assert call_kwargs["base_url"] == "https://custom.api.com/v2"

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Async context manager connects and disconnects."""
        from dagloom.connectors.http import HTTPConnector

        conn = HTTPConnector(self._config())
        async with conn:
            assert conn.is_connected
        assert not conn.is_connected

    def test_repr(self) -> None:
        """Repr includes class name."""
        from dagloom.connectors.http import HTTPConnector

        conn = HTTPConnector(self._config())
        assert "HTTPConnector" in repr(conn)


# ===========================================================================
# Import Error Tests
# ===========================================================================


class TestOriginalImportErrors:
    """Test that connectors raise helpful ImportError when deps missing."""

    @pytest.mark.asyncio
    async def test_postgres_import_error(self) -> None:
        """PostgresConnector raises ImportError with install hint."""
        with patch.dict(sys.modules, {"asyncpg": None}):
            if "dagloom.connectors.postgres" in sys.modules:
                del sys.modules["dagloom.connectors.postgres"]
            from dagloom.connectors.postgres import PostgresConnector

            conn = PostgresConnector(ConnectionConfig(database="test"))
            with pytest.raises(ImportError, match="asyncpg"):
                await conn.connect()

    @pytest.mark.asyncio
    async def test_mysql_import_error(self) -> None:
        """MySQLConnector raises ImportError with install hint."""
        with patch.dict(sys.modules, {"aiomysql": None}):
            if "dagloom.connectors.mysql" in sys.modules:
                del sys.modules["dagloom.connectors.mysql"]
            from dagloom.connectors.mysql import MySQLConnector

            conn = MySQLConnector(ConnectionConfig(database="test"))
            with pytest.raises(ImportError, match="aiomysql"):
                await conn.connect()

    @pytest.mark.asyncio
    async def test_s3_import_error(self) -> None:
        """S3Connector raises ImportError with install hint."""
        with patch.dict(sys.modules, {"aiobotocore": None, "aiobotocore.session": None}):
            if "dagloom.connectors.s3" in sys.modules:
                del sys.modules["dagloom.connectors.s3"]
            from dagloom.connectors.s3 import S3Connector

            conn = S3Connector(ConnectionConfig())
            with pytest.raises(ImportError, match="aiobotocore"):
                await conn.connect()

    @pytest.mark.asyncio
    async def test_http_import_error(self) -> None:
        """HTTPConnector raises ImportError with install hint."""
        with patch.dict(sys.modules, {"httpx": None}):
            if "dagloom.connectors.http" in sys.modules:
                del sys.modules["dagloom.connectors.http"]
            from dagloom.connectors.http import HTTPConnector

            conn = HTTPConnector(ConnectionConfig())
            with pytest.raises(ImportError, match="httpx"):
                await conn.connect()
