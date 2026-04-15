"""Tests for MongoDB, Redis, and Kafka connectors.

All tests use mocks — no external services required.

Covers:
- MongoDBConnector: connect, disconnect, health_check, execute (all operations)
- RedisConnector: connect, disconnect, health_check, execute (get/set/delete/...)
- KafkaConnector: connect, disconnect, health_check, execute (send/consume)
- Common: context manager, repr, default port, import error, not-connected error
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dagloom.connectors.base import ConnectionConfig

# ---------------------------------------------------------------------------
# Helper: mock module factory
# ---------------------------------------------------------------------------


def _make_mock_module(name: str, attrs: dict[str, Any]) -> ModuleType:
    """Create a fake module with the given attributes."""
    mod = ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


# ===========================================================================
# MongoDBConnector Tests
# ===========================================================================


class TestMongoDBConnector:
    """Tests for dagloom.connectors.mongodb.MongoDBConnector."""

    @pytest.fixture(autouse=True)
    def _mock_motor(self) -> Any:  # type: ignore[misc]
        """Inject a fake motor module into sys.modules."""
        self.mock_client_cls = MagicMock()
        self.mock_client = MagicMock()
        self.mock_client_cls.return_value = self.mock_client

        # Mock database and collection.
        self.mock_collection = MagicMock()
        self.mock_db = MagicMock()
        self.mock_db.__getitem__ = MagicMock(return_value=self.mock_collection)
        self.mock_client.__getitem__ = MagicMock(return_value=self.mock_db)

        # Mock admin.command("ping").
        self.mock_client.admin.command = AsyncMock(return_value={"ok": 1})

        motor_mod = _make_mock_module("motor", {})
        motor_asyncio_mod = _make_mock_module(
            "motor.motor_asyncio",
            {"AsyncIOMotorClient": self.mock_client_cls},
        )

        with patch.dict(
            sys.modules,
            {"motor": motor_mod, "motor.motor_asyncio": motor_asyncio_mod},
        ):
            yield

    def _config(self, **overrides: Any) -> ConnectionConfig:
        return ConnectionConfig(
            host="localhost",
            database="testdb",
            **overrides,
        )

    @pytest.mark.asyncio
    async def test_default_port(self) -> None:
        """Default port is 27017."""
        from dagloom.connectors.mongodb import MongoDBConnector

        cfg = self._config()
        conn = MongoDBConnector(cfg)
        assert conn.config.port == 27017

    @pytest.mark.asyncio
    async def test_connect_disconnect(self) -> None:
        """Connect creates a motor client; disconnect cleans up."""
        from dagloom.connectors.mongodb import MongoDBConnector

        conn = MongoDBConnector(self._config())
        assert not conn.is_connected

        await conn.connect()
        assert conn.is_connected
        self.mock_client_cls.assert_called_once()

        await conn.disconnect()
        assert not conn.is_connected
        self.mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_success(self) -> None:
        """Health check pings the server."""
        from dagloom.connectors.mongodb import MongoDBConnector

        conn = MongoDBConnector(self._config())
        await conn.connect()
        result = await conn.health_check()
        assert result is True
        self.mock_client.admin.command.assert_awaited_with("ping")

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self) -> None:
        """Health check returns False when not connected."""
        from dagloom.connectors.mongodb import MongoDBConnector

        conn = MongoDBConnector(self._config())
        assert await conn.health_check() is False

    @pytest.mark.asyncio
    async def test_execute_not_connected(self) -> None:
        """Execute raises ConnectionError when not connected."""
        from dagloom.connectors.mongodb import MongoDBConnector

        conn = MongoDBConnector(self._config())
        with pytest.raises(ConnectionError, match="Not connected"):
            await conn.execute("find", collection="users")

    @pytest.mark.asyncio
    async def test_execute_missing_collection(self) -> None:
        """Execute raises ValueError when collection is missing."""
        from dagloom.connectors.mongodb import MongoDBConnector

        conn = MongoDBConnector(self._config())
        await conn.connect()
        with pytest.raises(ValueError, match="collection"):
            await conn.execute("find")

    @pytest.mark.asyncio
    async def test_execute_find(self) -> None:
        """Find operation returns list of documents."""
        from dagloom.connectors.mongodb import MongoDBConnector

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"name": "Alice"}])
        self.mock_collection.find.return_value = mock_cursor

        conn = MongoDBConnector(self._config())
        await conn.connect()
        result = await conn.execute("find", collection="users", filter={"active": True})
        assert result == [{"name": "Alice"}]
        self.mock_collection.find.assert_called_once_with({"active": True})

    @pytest.mark.asyncio
    async def test_execute_find_one(self) -> None:
        """Find_one returns a single document."""
        from dagloom.connectors.mongodb import MongoDBConnector

        self.mock_collection.find_one = AsyncMock(return_value={"name": "Bob"})

        conn = MongoDBConnector(self._config())
        await conn.connect()
        result = await conn.execute("find_one", collection="users", filter={"_id": 1})
        assert result == {"name": "Bob"}

    @pytest.mark.asyncio
    async def test_execute_insert_one(self) -> None:
        """Insert_one returns inserted_id."""
        from dagloom.connectors.mongodb import MongoDBConnector

        mock_result = MagicMock()
        mock_result.inserted_id = "abc123"
        self.mock_collection.insert_one = AsyncMock(return_value=mock_result)

        conn = MongoDBConnector(self._config())
        await conn.connect()
        result = await conn.execute("insert_one", collection="users", document={"name": "Charlie"})
        assert result == {"inserted_id": "abc123"}

    @pytest.mark.asyncio
    async def test_execute_insert_many(self) -> None:
        """Insert_many returns list of inserted_ids."""
        from dagloom.connectors.mongodb import MongoDBConnector

        mock_result = MagicMock()
        mock_result.inserted_ids = ["id1", "id2"]
        self.mock_collection.insert_many = AsyncMock(return_value=mock_result)

        conn = MongoDBConnector(self._config())
        await conn.connect()
        result = await conn.execute(
            "insert_many", collection="users", documents=[{"a": 1}, {"b": 2}]
        )
        assert result == {"inserted_ids": ["id1", "id2"]}

    @pytest.mark.asyncio
    async def test_execute_update_one(self) -> None:
        """Update_one returns matched/modified counts."""
        from dagloom.connectors.mongodb import MongoDBConnector

        mock_result = MagicMock()
        mock_result.matched_count = 1
        mock_result.modified_count = 1
        self.mock_collection.update_one = AsyncMock(return_value=mock_result)

        conn = MongoDBConnector(self._config())
        await conn.connect()
        result = await conn.execute(
            "update_one",
            collection="users",
            filter={"_id": 1},
            update={"$set": {"name": "Dave"}},
        )
        assert result == {"matched_count": 1, "modified_count": 1}

    @pytest.mark.asyncio
    async def test_execute_update_many(self) -> None:
        """Update_many returns matched/modified counts."""
        from dagloom.connectors.mongodb import MongoDBConnector

        mock_result = MagicMock()
        mock_result.matched_count = 3
        mock_result.modified_count = 2
        self.mock_collection.update_many = AsyncMock(return_value=mock_result)

        conn = MongoDBConnector(self._config())
        await conn.connect()
        result = await conn.execute(
            "update_many",
            collection="users",
            filter={"active": False},
            update={"$set": {"active": True}},
        )
        assert result == {"matched_count": 3, "modified_count": 2}

    @pytest.mark.asyncio
    async def test_execute_delete_one(self) -> None:
        """Delete_one returns deleted_count."""
        from dagloom.connectors.mongodb import MongoDBConnector

        mock_result = MagicMock()
        mock_result.deleted_count = 1
        self.mock_collection.delete_one = AsyncMock(return_value=mock_result)

        conn = MongoDBConnector(self._config())
        await conn.connect()
        result = await conn.execute("delete_one", collection="users", filter={"_id": 1})
        assert result == {"deleted_count": 1}

    @pytest.mark.asyncio
    async def test_execute_delete_many(self) -> None:
        """Delete_many returns deleted_count."""
        from dagloom.connectors.mongodb import MongoDBConnector

        mock_result = MagicMock()
        mock_result.deleted_count = 5
        self.mock_collection.delete_many = AsyncMock(return_value=mock_result)

        conn = MongoDBConnector(self._config())
        await conn.connect()
        result = await conn.execute("delete_many", collection="users", filter={"active": False})
        assert result == {"deleted_count": 5}

    @pytest.mark.asyncio
    async def test_execute_aggregate(self) -> None:
        """Aggregate returns list of results."""
        from dagloom.connectors.mongodb import MongoDBConnector

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"_id": "A", "count": 10}])
        self.mock_collection.aggregate.return_value = mock_cursor

        conn = MongoDBConnector(self._config())
        await conn.connect()
        pipeline = [{"$group": {"_id": "$category", "count": {"$sum": 1}}}]
        result = await conn.execute("aggregate", collection="users", pipeline=pipeline)
        assert result == [{"_id": "A", "count": 10}]

    @pytest.mark.asyncio
    async def test_execute_count(self) -> None:
        """Count returns document count."""
        from dagloom.connectors.mongodb import MongoDBConnector

        self.mock_collection.count_documents = AsyncMock(return_value=42)

        conn = MongoDBConnector(self._config())
        await conn.connect()
        result = await conn.execute("count", collection="users", filter={"active": True})
        assert result == 42

    @pytest.mark.asyncio
    async def test_execute_unknown_operation(self) -> None:
        """Unknown operation raises ValueError."""
        from dagloom.connectors.mongodb import MongoDBConnector

        conn = MongoDBConnector(self._config())
        await conn.connect()
        with pytest.raises(ValueError, match="Unknown MongoDB operation"):
            await conn.execute("drop_everything", collection="users")

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Async context manager connects and disconnects."""
        from dagloom.connectors.mongodb import MongoDBConnector

        conn = MongoDBConnector(self._config())
        async with conn:
            assert conn.is_connected
        assert not conn.is_connected

    def test_repr(self) -> None:
        """Repr includes class name and connection info."""
        from dagloom.connectors.mongodb import MongoDBConnector

        conn = MongoDBConnector(self._config())
        r = repr(conn)
        assert "MongoDBConnector" in r
        assert "localhost" in r


# ===========================================================================
# RedisConnector Tests
# ===========================================================================


class TestRedisConnector:
    """Tests for dagloom.connectors.redis.RedisConnector."""

    @pytest.fixture(autouse=True)
    def _mock_redis(self) -> Any:  # type: ignore[misc]
        """Inject a fake redis.asyncio module."""
        self.mock_client = AsyncMock()
        self.mock_client.ping = AsyncMock(return_value=True)
        self.mock_client.aclose = AsyncMock()
        self.mock_redis_cls = MagicMock(return_value=self.mock_client)

        redis_asyncio_mod = _make_mock_module("redis.asyncio", {"Redis": self.mock_redis_cls})
        redis_mod = _make_mock_module("redis", {"asyncio": redis_asyncio_mod})

        with patch.dict(
            sys.modules,
            {"redis": redis_mod, "redis.asyncio": redis_asyncio_mod},
        ):
            yield

    def _config(self, **overrides: Any) -> ConnectionConfig:
        return ConnectionConfig(host="localhost", **overrides)

    @pytest.mark.asyncio
    async def test_default_port(self) -> None:
        """Default port is 6379."""
        from dagloom.connectors.redis import RedisConnector

        cfg = self._config()
        conn = RedisConnector(cfg)
        assert conn.config.port == 6379

    @pytest.mark.asyncio
    async def test_connect_disconnect(self) -> None:
        """Connect creates client; disconnect closes it."""
        from dagloom.connectors.redis import RedisConnector

        conn = RedisConnector(self._config())
        await conn.connect()
        assert conn.is_connected
        self.mock_redis_cls.assert_called_once()

        await conn.disconnect()
        assert not conn.is_connected
        self.mock_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_health_check_success(self) -> None:
        """Health check pings the server."""
        from dagloom.connectors.redis import RedisConnector

        conn = RedisConnector(self._config())
        await conn.connect()
        assert await conn.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self) -> None:
        """Health check returns False when not connected."""
        from dagloom.connectors.redis import RedisConnector

        conn = RedisConnector(self._config())
        assert await conn.health_check() is False

    @pytest.mark.asyncio
    async def test_execute_get(self) -> None:
        """GET command returns value."""
        from dagloom.connectors.redis import RedisConnector

        self.mock_client.get = AsyncMock(return_value="myvalue")

        conn = RedisConnector(self._config())
        await conn.connect()
        result = await conn.execute("get", "mykey")
        assert result == "myvalue"
        self.mock_client.get.assert_awaited_once_with("mykey")

    @pytest.mark.asyncio
    async def test_execute_set(self) -> None:
        """SET command stores value."""
        from dagloom.connectors.redis import RedisConnector

        self.mock_client.set = AsyncMock(return_value=True)

        conn = RedisConnector(self._config())
        await conn.connect()
        result = await conn.execute("set", "mykey", "myvalue")
        assert result is True

    @pytest.mark.asyncio
    async def test_execute_delete(self) -> None:
        """DELETE command removes key."""
        from dagloom.connectors.redis import RedisConnector

        self.mock_client.delete = AsyncMock(return_value=1)

        conn = RedisConnector(self._config())
        await conn.connect()
        result = await conn.execute("delete", "mykey")
        assert result == 1

    @pytest.mark.asyncio
    async def test_execute_hget(self) -> None:
        """HGET command returns hash field value."""
        from dagloom.connectors.redis import RedisConnector

        self.mock_client.hget = AsyncMock(return_value="field_value")

        conn = RedisConnector(self._config())
        await conn.connect()
        result = await conn.execute("hget", "myhash", "myfield")
        assert result == "field_value"

    @pytest.mark.asyncio
    async def test_execute_not_connected(self) -> None:
        """Execute raises ConnectionError when not connected."""
        from dagloom.connectors.redis import RedisConnector

        conn = RedisConnector(self._config())
        with pytest.raises(ConnectionError, match="Not connected"):
            await conn.execute("get", "mykey")

    @pytest.mark.asyncio
    async def test_execute_unsupported_command(self) -> None:
        """Unsupported command raises ValueError."""
        from dagloom.connectors.redis import RedisConnector

        conn = RedisConnector(self._config())
        await conn.connect()
        # Remove the method to simulate unsupported command.
        self.mock_client.nonexistent_cmd = None
        delattr(self.mock_client, "nonexistent_cmd")
        with pytest.raises(ValueError, match="Unsupported Redis command"):
            await conn.execute("nonexistent_cmd", "arg")

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Async context manager connects and disconnects."""
        from dagloom.connectors.redis import RedisConnector

        conn = RedisConnector(self._config())
        async with conn:
            assert conn.is_connected
        assert not conn.is_connected

    def test_repr(self) -> None:
        """Repr includes class name and connection info."""
        from dagloom.connectors.redis import RedisConnector

        conn = RedisConnector(self._config())
        r = repr(conn)
        assert "RedisConnector" in r
        assert "localhost" in r

    @pytest.mark.asyncio
    async def test_connect_with_db_index(self) -> None:
        """Database field is used as Redis DB index."""
        from dagloom.connectors.redis import RedisConnector

        cfg = self._config(database="3")
        conn = RedisConnector(cfg)
        await conn.connect()
        # Verify db=3 was passed to the Redis constructor.
        call_kwargs = self.mock_redis_cls.call_args[1]
        assert call_kwargs["db"] == 3


# ===========================================================================
# KafkaConnector Tests
# ===========================================================================


class TestKafkaConnector:
    """Tests for dagloom.connectors.kafka.KafkaConnector."""

    @pytest.fixture(autouse=True)
    def _mock_aiokafka(self) -> Any:  # type: ignore[misc]
        """Inject a fake aiokafka module."""
        self.mock_producer = AsyncMock()
        self.mock_producer.start = AsyncMock()
        self.mock_producer.stop = AsyncMock()
        self.mock_producer.partitions_for = AsyncMock(return_value={0, 1})

        # Mock send_and_wait to return a record-like object.
        self.mock_record = SimpleNamespace(topic="test-topic", partition=0, offset=42)
        self.mock_producer.send_and_wait = AsyncMock(return_value=self.mock_record)

        self.mock_producer_cls = MagicMock(return_value=self.mock_producer)

        self.mock_consumer = AsyncMock()
        self.mock_consumer.start = AsyncMock()
        self.mock_consumer.stop = AsyncMock()
        self.mock_consumer_cls = MagicMock(return_value=self.mock_consumer)

        aiokafka_mod = _make_mock_module(
            "aiokafka",
            {
                "AIOKafkaProducer": self.mock_producer_cls,
                "AIOKafkaConsumer": self.mock_consumer_cls,
            },
        )

        with patch.dict(sys.modules, {"aiokafka": aiokafka_mod}):
            yield

    def _config(self, **overrides: Any) -> ConnectionConfig:
        overrides.setdefault("host", "localhost")
        return ConnectionConfig(**overrides)

    @pytest.mark.asyncio
    async def test_default_port(self) -> None:
        """Default port is 9092."""
        from dagloom.connectors.kafka import KafkaConnector

        cfg = self._config()
        conn = KafkaConnector(cfg)
        assert conn.config.port == 9092

    @pytest.mark.asyncio
    async def test_connect_disconnect(self) -> None:
        """Connect starts producer; disconnect stops it."""
        from dagloom.connectors.kafka import KafkaConnector

        conn = KafkaConnector(self._config())
        await conn.connect()
        assert conn.is_connected
        self.mock_producer.start.assert_awaited_once()

        await conn.disconnect()
        assert not conn.is_connected
        self.mock_producer.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_health_check_success(self) -> None:
        """Health check queries partitions for connectivity."""
        from dagloom.connectors.kafka import KafkaConnector

        conn = KafkaConnector(self._config())
        await conn.connect()
        assert await conn.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self) -> None:
        """Health check returns False when not connected."""
        from dagloom.connectors.kafka import KafkaConnector

        conn = KafkaConnector(self._config())
        assert await conn.health_check() is False

    @pytest.mark.asyncio
    async def test_execute_send(self) -> None:
        """Send operation produces a message."""
        from dagloom.connectors.kafka import KafkaConnector

        conn = KafkaConnector(self._config())
        await conn.connect()
        result = await conn.execute("send", topic="test-topic", value=b"hello")
        assert result == {"topic": "test-topic", "partition": 0, "offset": 42}
        self.mock_producer.send_and_wait.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_send_not_connected(self) -> None:
        """Send raises ConnectionError when not connected."""
        from dagloom.connectors.kafka import KafkaConnector

        conn = KafkaConnector(self._config())
        with pytest.raises(ConnectionError, match="Not connected"):
            await conn.execute("send", topic="test-topic", value=b"hello")

    @pytest.mark.asyncio
    async def test_execute_send_missing_topic(self) -> None:
        """Send raises ValueError when topic is missing."""
        from dagloom.connectors.kafka import KafkaConnector

        conn = KafkaConnector(self._config())
        await conn.connect()
        with pytest.raises(ValueError, match="topic"):
            await conn.execute("send", value=b"hello")

    @pytest.mark.asyncio
    async def test_execute_consume(self) -> None:
        """Consume operation reads messages via temporary consumer."""
        from dagloom.connectors.kafka import KafkaConnector

        # Mock async iteration over consumer.
        mock_msg = SimpleNamespace(
            topic="test-topic",
            partition=0,
            offset=0,
            key=None,
            value=b"hello",
            timestamp=1000,
        )

        # Build a proper async iterator for `async for msg in consumer`.
        class _AsyncIter:
            def __init__(self, items: list[Any]) -> None:
                self._items = iter(items)

            def __aiter__(self) -> _AsyncIter:
                return self

            async def __anext__(self) -> Any:
                try:
                    return next(self._items)
                except StopIteration:
                    raise StopAsyncIteration  # noqa: B904

        aiter = _AsyncIter([mock_msg])
        self.mock_consumer.__aiter__ = MagicMock(return_value=aiter)
        self.mock_consumer.__anext__ = aiter.__anext__

        conn = KafkaConnector(self._config())
        # Note: consume doesn't require a producer connection.
        result = await conn.execute(
            "consume", topic="test-topic", group_id="test-group", max_messages=1
        )
        assert len(result) == 1
        assert result[0]["topic"] == "test-topic"
        assert result[0]["value"] == b"hello"

    @pytest.mark.asyncio
    async def test_execute_consume_missing_topic(self) -> None:
        """Consume raises ValueError when topic is missing."""
        from dagloom.connectors.kafka import KafkaConnector

        conn = KafkaConnector(self._config())
        with pytest.raises(ValueError, match="topic"):
            await conn.execute("consume")

    @pytest.mark.asyncio
    async def test_execute_unknown_operation(self) -> None:
        """Unknown operation raises ValueError."""
        from dagloom.connectors.kafka import KafkaConnector

        conn = KafkaConnector(self._config())
        with pytest.raises(ValueError, match="Unknown Kafka operation"):
            await conn.execute("purge_topic", topic="test")

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Async context manager connects and disconnects."""
        from dagloom.connectors.kafka import KafkaConnector

        conn = KafkaConnector(self._config())
        async with conn:
            assert conn.is_connected
        assert not conn.is_connected

    def test_repr(self) -> None:
        """Repr includes class name and connection info."""
        from dagloom.connectors.kafka import KafkaConnector

        conn = KafkaConnector(self._config())
        r = repr(conn)
        assert "KafkaConnector" in r
        assert "localhost" in r

    @pytest.mark.asyncio
    async def test_bootstrap_servers_with_port_in_host(self) -> None:
        """Host containing ':' is used as-is for bootstrap servers."""
        from dagloom.connectors.kafka import KafkaConnector

        cfg = self._config(host="broker1:9092,broker2:9092")
        conn = KafkaConnector(cfg)
        assert conn._bootstrap_servers() == "broker1:9092,broker2:9092"


# ===========================================================================
# Import Error Tests (no mocked modules)
# ===========================================================================


class TestImportErrors:
    """Test that connectors raise helpful ImportError when deps are missing."""

    @pytest.mark.asyncio
    async def test_mongodb_import_error(self) -> None:
        """MongoDBConnector raises ImportError with install hint."""
        with patch.dict(sys.modules, {"motor": None, "motor.motor_asyncio": None}):
            # Force reimport.
            if "dagloom.connectors.mongodb" in sys.modules:
                del sys.modules["dagloom.connectors.mongodb"]
            from dagloom.connectors.mongodb import MongoDBConnector

            conn = MongoDBConnector(ConnectionConfig(database="test"))
            with pytest.raises(ImportError, match="motor"):
                await conn.connect()

    @pytest.mark.asyncio
    async def test_redis_import_error(self) -> None:
        """RedisConnector raises ImportError with install hint."""
        with patch.dict(sys.modules, {"redis": None, "redis.asyncio": None}):
            if "dagloom.connectors.redis" in sys.modules:
                del sys.modules["dagloom.connectors.redis"]
            from dagloom.connectors.redis import RedisConnector

            conn = RedisConnector(ConnectionConfig())
            with pytest.raises(ImportError, match="redis"):
                await conn.connect()

    @pytest.mark.asyncio
    async def test_kafka_import_error(self) -> None:
        """KafkaConnector raises ImportError with install hint."""
        with patch.dict(sys.modules, {"aiokafka": None}):
            if "dagloom.connectors.kafka" in sys.modules:
                del sys.modules["dagloom.connectors.kafka"]
            from dagloom.connectors.kafka import KafkaConnector

            conn = KafkaConnector(ConnectionConfig())
            with pytest.raises(ImportError, match="aiokafka"):
                await conn.connect()
