"""Tests for the CacheManager."""

import pytest

from dagloom.scheduler.cache import CacheManager, compute_input_hash
from dagloom.store.db import Database


@pytest.fixture
async def db(tmp_path):
    """Provide a fresh database for each test."""
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def cache(db, tmp_path):
    """Provide a CacheManager with a temp cache directory."""
    cache_dir = tmp_path / "cache"
    return CacheManager(db, cache_dir=cache_dir)


class TestComputeInputHash:
    """Test input hash computation."""

    def test_same_input_same_hash(self) -> None:
        h1 = compute_input_hash(1, 2, key="value")
        h2 = compute_input_hash(1, 2, key="value")
        assert h1 == h2

    def test_different_input_different_hash(self) -> None:
        h1 = compute_input_hash(1, 2)
        h2 = compute_input_hash(3, 4)
        assert h1 != h2

    def test_hash_is_hex_string(self) -> None:
        h = compute_input_hash("hello")
        assert len(h) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in h)

    def test_kwargs_order_independent(self) -> None:
        h1 = compute_input_hash(a=1, b=2)
        h2 = compute_input_hash(b=2, a=1)
        assert h1 == h2


class TestCacheManager:
    """Test cache put/get/invalidate."""

    @pytest.mark.asyncio
    async def test_miss_returns_none(self, cache) -> None:
        result = await cache.get("node_a", "nonexistent_hash")
        assert result is None

    @pytest.mark.asyncio
    async def test_put_and_get_pickle(self, cache) -> None:
        await cache.put("node_a", "hash123", {"data": [1, 2, 3]})
        result = await cache.get("node_a", "hash123")
        assert result == {"data": [1, 2, 3]}

    @pytest.mark.asyncio
    async def test_put_and_get_json(self, cache) -> None:
        await cache.put("node_b", "hash456", {"key": "value"}, fmt="json")
        result = await cache.get("node_b", "hash456")
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_invalidate(self, cache) -> None:
        await cache.put("node_c", "hash789", 42)
        await cache.invalidate("node_c", "hash789")
        result = await cache.get("node_c", "hash789")
        assert result is None

    @pytest.mark.asyncio
    async def test_overwrite_existing(self, cache) -> None:
        await cache.put("node_d", "hash000", "old_value")
        await cache.put("node_d", "hash000", "new_value")
        result = await cache.get("node_d", "hash000")
        assert result == "new_value"

    @pytest.mark.asyncio
    async def test_missing_file_cleans_metadata(self, cache, tmp_path) -> None:
        """If the cached file is deleted externally, metadata is cleaned."""
        path = await cache.put("node_e", "hashXYZ", "data")
        # Simulate external deletion.
        from pathlib import Path

        Path(path).unlink()
        result = await cache.get("node_e", "hashXYZ")
        assert result is None
