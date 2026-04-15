"""Tests for cache dependency invalidation (P1-7).

Covers:
- CacheManager.invalidate_node() — bulk invalidation of a single node
- CacheManager.invalidate_downstream() — cascade invalidation using DAG structure
- CacheManager.compute_output_hash() — deterministic output hashing
- Database.delete_cache_entries_for_node() — bulk DB delete
- Database.get_cache_entries_for_node() — fetch all entries for a node
- AsyncExecutor integration — output change triggers downstream invalidation
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from dagloom import AsyncExecutor, CacheManager, Pipeline, node
from dagloom.store.db import Database

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:  # type: ignore[misc]
    """Create a temporary database."""
    _db = Database(tmp_path / "test.db")
    await _db.connect()
    yield _db  # type: ignore[misc]
    await _db.close()


@pytest_asyncio.fixture
async def cache(db: Database, tmp_path: Path) -> CacheManager:  # type: ignore[misc]
    """Create a CacheManager backed by the temporary database."""
    return CacheManager(db, cache_dir=tmp_path / "cache")


# ---------------------------------------------------------------------------
# Database: delete_cache_entries_for_node / get_cache_entries_for_node
# ---------------------------------------------------------------------------


class TestDatabaseCacheOps:
    """Tests for bulk cache operations on the Database layer."""

    @pytest.mark.asyncio
    async def test_delete_cache_entries_for_node_empty(self, db: Database) -> None:
        """Deleting entries for a non-existent node returns 0."""
        count = await db.delete_cache_entries_for_node("nonexistent")
        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_cache_entries_for_node(self, db: Database, tmp_path: Path) -> None:
        """Bulk-delete all cache entries for a node."""
        for i in range(2):
            p = tmp_path / f"a_{i}.pkl"
            p.write_bytes(b"data")
            await db.save_cache_entry("node_a", f"hash_{i}", str(p))
        p_b = tmp_path / "b_0.pkl"
        p_b.write_bytes(b"data")
        await db.save_cache_entry("node_b", "hash_0", str(p_b))

        count = await db.delete_cache_entries_for_node("node_a")
        assert count == 2

        # node_b still has its entry.
        entry = await db.get_cache_entry("node_b", "hash_0")
        assert entry is not None

    @pytest.mark.asyncio
    async def test_get_cache_entries_for_node(self, db: Database, tmp_path: Path) -> None:
        """Fetch all cache entries for a specific node."""
        for i in range(3):
            p = tmp_path / f"n_{i}.pkl"
            p.write_bytes(b"data")
            await db.save_cache_entry("node_x", f"hash_{i}", str(p))

        entries = await db.get_cache_entries_for_node("node_x")
        assert len(entries) == 3

        entries_empty = await db.get_cache_entries_for_node("node_y")
        assert len(entries_empty) == 0


# ---------------------------------------------------------------------------
# CacheManager.invalidate_node
# ---------------------------------------------------------------------------


class TestInvalidateNode:
    """Tests for CacheManager.invalidate_node()."""

    @pytest.mark.asyncio
    async def test_invalidate_node(self, cache: CacheManager) -> None:
        """invalidate_node() removes all entries and files for a node."""
        path_a = await cache.put("clean", "hash_1", {"a": 1})
        path_b = await cache.put("clean", "hash_2", {"b": 2})

        assert Path(path_a).exists()
        assert Path(path_b).exists()

        count = await cache.invalidate_node("clean")
        assert count == 2

        assert not Path(path_a).exists()
        assert not Path(path_b).exists()

        assert await cache.db.get_cache_entry("clean", "hash_1") is None
        assert await cache.db.get_cache_entry("clean", "hash_2") is None

    @pytest.mark.asyncio
    async def test_invalidate_node_no_entries(self, cache: CacheManager) -> None:
        """invalidate_node() returns 0 when no entries exist."""
        count = await cache.invalidate_node("nonexistent")
        assert count == 0


# ---------------------------------------------------------------------------
# CacheManager.invalidate_downstream
# ---------------------------------------------------------------------------


class TestInvalidateDownstream:
    """Tests for CacheManager.invalidate_downstream()."""

    @pytest.mark.asyncio
    async def test_linear_chain(self, cache: CacheManager) -> None:
        """A >> B >> C: invalidating downstream of A removes B and C caches."""

        @node(cache=True)
        def a(x: int) -> int:
            return x + 1

        @node(cache=True)
        def b(x: int) -> int:
            return x * 2

        @node(cache=True)
        def c(x: int) -> int:
            return x - 1

        pipeline = a >> b >> c

        await cache.put("b", "hash_b", 10)
        await cache.put("c", "hash_c", 19)

        invalidated = await cache.invalidate_downstream("a", pipeline.nodes, pipeline.edges)
        assert invalidated == {"b", "c"}

        assert await cache.db.get_cache_entry("b", "hash_b") is None
        assert await cache.db.get_cache_entry("c", "hash_c") is None

    @pytest.mark.asyncio
    async def test_fanout(self, cache: CacheManager) -> None:
        """A >> [B, C] >> D: invalidating downstream of A removes B, C, D."""

        @node(cache=True)
        def a(x: int) -> int:
            return x

        @node(cache=True)
        def b(x: int) -> int:
            return x + 1

        @node(cache=True)
        def c(x: int) -> int:
            return x + 2

        @node(cache=True)
        def d(x: dict) -> int:  # type: ignore[type-arg]
            return sum(x.values())

        pipeline = Pipeline()
        pipeline.add_node(a)
        pipeline.add_node(b)
        pipeline.add_node(c)
        pipeline.add_node(d)
        pipeline.add_edge("a", "b")
        pipeline.add_edge("a", "c")
        pipeline.add_edge("b", "d")
        pipeline.add_edge("c", "d")

        await cache.put("b", "hb", 1)
        await cache.put("c", "hc", 2)
        await cache.put("d", "hd", 3)

        invalidated = await cache.invalidate_downstream("a", pipeline.nodes, pipeline.edges)
        assert invalidated == {"b", "c", "d"}

    @pytest.mark.asyncio
    async def test_independent_branch(self, cache: CacheManager) -> None:
        """A >> B and C >> D: invalidating downstream of A only affects B."""

        @node(cache=True)
        def a(x: int) -> int:
            return x

        @node(cache=True)
        def b(x: int) -> int:
            return x + 1

        @node(cache=True)
        def c(x: int) -> int:
            return x + 2

        @node(cache=True)
        def d(x: int) -> int:
            return x + 3

        pipeline = Pipeline()
        pipeline.add_node(a)
        pipeline.add_node(b)
        pipeline.add_node(c)
        pipeline.add_node(d)
        pipeline.add_edge("a", "b")
        pipeline.add_edge("c", "d")

        await cache.put("b", "hb", 10)
        await cache.put("d", "hd", 20)

        invalidated = await cache.invalidate_downstream("a", pipeline.nodes, pipeline.edges)
        assert invalidated == {"b"}
        assert await cache.db.get_cache_entry("d", "hd") is not None

    @pytest.mark.asyncio
    async def test_no_downstream(self, cache: CacheManager) -> None:
        """Leaf node has no downstream — returns empty set."""

        @node(cache=True)
        def a(x: int) -> int:
            return x

        @node(cache=True)
        def b(x: int) -> int:
            return x + 1

        pipeline = a >> b

        await cache.put("a", "ha", 1)

        invalidated = await cache.invalidate_downstream("b", pipeline.nodes, pipeline.edges)
        assert invalidated == set()
        assert await cache.db.get_cache_entry("a", "ha") is not None

    @pytest.mark.asyncio
    async def test_mid_chain(self, cache: CacheManager) -> None:
        """A >> B >> C >> D: invalidating downstream of B removes C and D only."""

        @node(cache=True)
        def a(x: int) -> int:
            return x

        @node(cache=True)
        def b(x: int) -> int:
            return x + 1

        @node(cache=True)
        def c(x: int) -> int:
            return x + 2

        @node(cache=True)
        def d(x: int) -> int:
            return x + 3

        pipeline = a >> b >> c >> d

        await cache.put("a", "ha", 1)
        await cache.put("b", "hb", 2)
        await cache.put("c", "hc", 3)
        await cache.put("d", "hd", 4)

        invalidated = await cache.invalidate_downstream("b", pipeline.nodes, pipeline.edges)
        assert invalidated == {"c", "d"}
        assert await cache.db.get_cache_entry("a", "ha") is not None
        assert await cache.db.get_cache_entry("b", "hb") is not None

    @pytest.mark.asyncio
    async def test_diamond(self, cache: CacheManager) -> None:
        """Diamond DAG: A >> [B, C] >> D. Invalidating A removes B, C, D."""

        @node(cache=True)
        def a(x: int) -> int:
            return x

        @node(cache=True)
        def b(x: int) -> int:
            return x

        @node(cache=True)
        def c(x: int) -> int:
            return x

        @node(cache=True)
        def d(x: dict) -> int:  # type: ignore[type-arg]
            return 0

        pipeline = Pipeline()
        pipeline.add_node(a)
        pipeline.add_node(b)
        pipeline.add_node(c)
        pipeline.add_node(d)
        pipeline.add_edge("a", "b")
        pipeline.add_edge("a", "c")
        pipeline.add_edge("b", "d")
        pipeline.add_edge("c", "d")

        await cache.put("a", "ha", 1)
        await cache.put("b", "hb", 2)
        await cache.put("c", "hc", 3)
        await cache.put("d", "hd", 4)

        invalidated = await cache.invalidate_downstream("a", pipeline.nodes, pipeline.edges)
        assert invalidated == {"b", "c", "d"}
        assert await cache.db.get_cache_entry("a", "ha") is not None

    @pytest.mark.asyncio
    async def test_no_cache_entries(self, cache: CacheManager) -> None:
        """Downstream nodes with no cache entries — no error, returns empty."""

        @node
        def a(x: int) -> int:
            return x

        @node
        def b(x: int) -> int:
            return x

        pipeline = a >> b

        invalidated = await cache.invalidate_downstream("a", pipeline.nodes, pipeline.edges)
        assert invalidated == set()


# ---------------------------------------------------------------------------
# CacheManager.compute_output_hash
# ---------------------------------------------------------------------------


class TestComputeOutputHash:
    """Tests for CacheManager.compute_output_hash()."""

    def _make_cm(self) -> CacheManager:
        """Create a minimal CacheManager instance (no DB needed)."""
        return CacheManager.__new__(CacheManager)

    def test_deterministic(self) -> None:
        """Same value produces the same hash."""
        cm = self._make_cm()
        h1 = cm.compute_output_hash({"key": "value", "num": 42})
        h2 = cm.compute_output_hash({"key": "value", "num": 42})
        assert h1 == h2

    def test_different_values(self) -> None:
        """Different values produce different hashes."""
        cm = self._make_cm()
        h1 = cm.compute_output_hash({"key": "value"})
        h2 = cm.compute_output_hash({"key": "other"})
        assert h1 != h2

    def test_unpicklable(self) -> None:
        """Falls back to repr() for unpicklable objects."""
        cm = self._make_cm()
        h = cm.compute_output_hash(lambda: None)
        assert isinstance(h, str) and len(h) == 64


# ---------------------------------------------------------------------------
# AsyncExecutor integration: output change triggers downstream invalidation
# ---------------------------------------------------------------------------


class TestExecutorCacheInvalidation:
    """Tests for automatic downstream invalidation in AsyncExecutor."""

    @pytest.mark.asyncio
    async def test_output_change_triggers_invalidation(self, db: Database, tmp_path: Path) -> None:
        """When a cached node produces a different output, downstream caches
        are invalidated so they re-execute on the next run."""
        cache_mgr = CacheManager(db, cache_dir=tmp_path / "cache")

        counter = {"a": 0, "b": 0}

        @node(cache=True)
        def step_a(x: int) -> int:
            counter["a"] += 1
            return x + counter["a"]  # Output changes each run.

        @node(cache=True)
        def step_b(x: int) -> int:
            counter["b"] += 1
            return x * 10

        pipeline = step_a >> step_b

        executor = AsyncExecutor(pipeline, cache_manager=cache_mgr)

        # First run: both execute.
        result1 = await executor.execute(x=1)
        assert counter["a"] == 1
        assert counter["b"] == 1
        assert result1 == 20  # (1+1) * 10

        # Invalidate step_a so it re-runs; output changes → step_b invalidated.
        await cache_mgr.invalidate_node("step_a")

        result2 = await executor.execute(x=1)
        assert counter["a"] == 2
        assert counter["b"] == 2  # Re-executed.
        assert result2 == 30  # (1+2) * 10

    @pytest.mark.asyncio
    async def test_same_output_no_invalidation(self, db: Database, tmp_path: Path) -> None:
        """When a node produces the same output, downstream caches are kept."""
        cache_mgr = CacheManager(db, cache_dir=tmp_path / "cache")

        counter = {"a": 0, "b": 0}

        @node(cache=True)
        def const_a(x: int) -> int:
            counter["a"] += 1
            return 42  # Always same output.

        @node(cache=True)
        def double_b(x: int) -> int:
            counter["b"] += 1
            return x * 2

        pipeline = const_a >> double_b

        executor = AsyncExecutor(pipeline, cache_manager=cache_mgr)

        result1 = await executor.execute(x=1)
        assert counter == {"a": 1, "b": 1}
        assert result1 == 84

        # Invalidate A so it re-executes, but output is same.
        await cache_mgr.invalidate_node("const_a")

        result2 = await executor.execute(x=1)
        assert counter["a"] == 2  # Re-executed.
        assert counter["b"] == 1  # Cache HIT — output didn't change.
        assert result2 == 84

    @pytest.mark.asyncio
    async def test_fanout_invalidation(self, db: Database, tmp_path: Path) -> None:
        """Fan-out: A >> [B, C]. When A's output changes, both B and C re-execute."""
        cache_mgr = CacheManager(db, cache_dir=tmp_path / "cache")

        counter = {"a": 0, "b": 0, "c": 0}

        @node(cache=True)
        def root_a(x: int) -> int:
            counter["a"] += 1
            return x + counter["a"]

        @node(cache=True)
        def left_b(x: int) -> int:
            counter["b"] += 1
            return x + 100

        @node(cache=True)
        def right_c(x: int) -> int:
            counter["c"] += 1
            return x + 200

        pipeline = Pipeline()
        pipeline.add_node(root_a)
        pipeline.add_node(left_b)
        pipeline.add_node(right_c)
        pipeline.add_edge("root_a", "left_b")
        pipeline.add_edge("root_a", "right_c")
        pipeline._tail_nodes = ["left_b", "right_c"]

        executor = AsyncExecutor(pipeline, cache_manager=cache_mgr)

        # First run.
        await executor.execute(x=1)
        assert counter == {"a": 1, "b": 1, "c": 1}

        # Invalidate root_a so it re-executes with different output.
        await cache_mgr.invalidate_node("root_a")

        await executor.execute(x=1)
        assert counter == {"a": 2, "b": 2, "c": 2}
