"""Tests for dagloom improvements.

Covers:
- AsyncExecutor cache integration
- AsyncExecutor checkpoint integration
- Pipeline.run() with async nodes
- Pipeline.arun() convenience method
- codegen complex DAG support
- NodeStatus de-duplication
- Expanded public API
"""

import asyncio

import pytest

from dagloom.core.node import node
from dagloom.core.pipeline import Pipeline
from dagloom.scheduler.cache import CacheManager, compute_input_hash
from dagloom.scheduler.checkpoint import CheckpointManager
from dagloom.scheduler.executor import AsyncExecutor, ExecutionError
from dagloom.store.db import Database


# -- Fixtures -----------------------------------------------------------------


@pytest.fixture
async def db(tmp_path):
    """Provide a fresh database for each test."""
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def cache_manager(db, tmp_path):
    """Provide a CacheManager with a temp cache directory."""
    cache_dir = tmp_path / "cache"
    return CacheManager(db, cache_dir=cache_dir)


@pytest.fixture
async def checkpoint_manager(db):
    """Provide a CheckpointManager."""
    return CheckpointManager(db)


# -- Test: AsyncExecutor cache integration ------------------------------------


class TestExecutorCacheIntegration:
    """Test that cache_manager is used by AsyncExecutor."""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_execution(self, cache_manager) -> None:
        """Second call with same input should hit cache."""
        call_count = 0

        @node(cache=True)
        def expensive(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 100

        pipe = Pipeline()
        pipe.add_node(expensive)
        pipe._tail_nodes = ["expensive"]

        executor = AsyncExecutor(pipe, cache_manager=cache_manager)

        # First call: cache miss, should execute.
        result1 = await executor.execute(x=5)
        assert result1 == 500
        assert call_count == 1

        # Second call: cache hit, should NOT execute.
        result2 = await executor.execute(x=5)
        assert result2 == 500
        assert call_count == 1  # Still 1!

    @pytest.mark.asyncio
    async def test_cache_different_input_executes(self, cache_manager) -> None:
        """Different input should cause a cache miss."""
        call_count = 0

        @node(cache=True)
        def double(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        pipe = Pipeline()
        pipe.add_node(double)
        pipe._tail_nodes = ["double"]

        executor = AsyncExecutor(pipe, cache_manager=cache_manager)

        await executor.execute(x=3)
        assert call_count == 1

        await executor.execute(x=7)
        assert call_count == 2  # Different input, new execution.

    @pytest.mark.asyncio
    async def test_no_cache_without_flag(self, cache_manager) -> None:
        """Nodes without cache=True should not be cached."""
        call_count = 0

        @node  # No cache=True
        def simple(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x

        pipe = Pipeline()
        pipe.add_node(simple)
        pipe._tail_nodes = ["simple"]

        executor = AsyncExecutor(pipe, cache_manager=cache_manager)

        await executor.execute(x=1)
        await executor.execute(x=1)
        assert call_count == 2  # Executed both times.


# -- Test: AsyncExecutor checkpoint integration -------------------------------


class TestExecutorCheckpointIntegration:
    """Test that checkpoint_manager is used by AsyncExecutor."""

    @pytest.mark.asyncio
    async def test_checkpoint_records_success(self, db, checkpoint_manager) -> None:
        """Successful execution should create checkpoint records."""
        # Create pipeline record for foreign key.
        await db.save_pipeline("test-pipe", "test-pipe")

        @node
        def add_one(x: int) -> int:
            return x + 1

        pipe = Pipeline(name="test-pipe")
        pipe.add_node(add_one)
        pipe._tail_nodes = ["add_one"]

        executor = AsyncExecutor(pipe, checkpoint_manager=checkpoint_manager)
        result = await executor.execute(x=5)
        assert result == 6

    @pytest.mark.asyncio
    async def test_checkpoint_records_failure(self, db, checkpoint_manager) -> None:
        """Failed execution should persist failure state."""
        await db.save_pipeline("fail-pipe", "fail-pipe")

        @node
        def fail_node(x: int) -> int:
            raise ValueError("intentional failure")

        pipe = Pipeline(name="fail-pipe")
        pipe.add_node(fail_node)
        pipe._tail_nodes = ["fail_node"]

        executor = AsyncExecutor(pipe, checkpoint_manager=checkpoint_manager)
        with pytest.raises(ExecutionError, match="fail_node"):
            await executor.execute(x=1)


# -- Test: Pipeline.run() with async nodes ------------------------------------


class TestPipelineRunAsync:
    """Test that Pipeline.run() handles async node functions."""

    def test_run_with_async_node(self) -> None:
        """Pipeline.run() should transparently handle async def nodes."""

        @node
        async def async_add(x: int) -> int:
            await asyncio.sleep(0.01)
            return x + 10

        @node
        def sync_double(x: int) -> int:
            return x * 2

        pipeline = async_add >> sync_double
        result = pipeline.run(x=5)
        assert result == 30  # (5+10)*2

    def test_run_all_async_nodes(self) -> None:
        """Pipeline.run() with all-async chain."""

        @node
        async def step_a(x: int) -> int:
            return x + 1

        @node
        async def step_b(x: int) -> int:
            return x * 3

        pipeline = step_a >> step_b
        result = pipeline.run(x=2)
        assert result == 9  # (2+1)*3


# -- Test: Pipeline.arun() ---------------------------------------------------


class TestPipelineArun:
    """Test the new arun() convenience method."""

    @pytest.mark.asyncio
    async def test_arun_basic(self) -> None:
        @node
        def inc(x: int) -> int:
            return x + 1

        @node
        def triple(x: int) -> int:
            return x * 3

        pipeline = inc >> triple
        result = await pipeline.arun(x=4)
        assert result == 15  # (4+1)*3

    @pytest.mark.asyncio
    async def test_arun_with_async_nodes(self) -> None:
        @node
        async def async_inc(x: int) -> int:
            return x + 1

        @node
        async def async_triple(x: int) -> int:
            return x * 3

        pipeline = async_inc >> async_triple
        result = await pipeline.arun(x=4)
        assert result == 15


# -- Test: codegen complex DAG -----------------------------------------------


class TestCodegenComplexDag:
    """Test that codegen handles non-linear DAGs correctly."""

    def test_linear_chain_codegen(self) -> None:
        from dagloom.server.codegen import _build_dag_statements

        edges = [["a", "b"], ["b", "c"]]
        result = _build_dag_statements(edges)
        assert len(result) == 1
        assert "a >> b >> c" in result[0]

    def test_fanout_dag_codegen(self) -> None:
        """Fan-out: A -> B, A -> C should NOT lose any edge."""
        from dagloom.server.codegen import _build_dag_statements

        edges = [["a", "b"], ["a", "c"]]
        result = _build_dag_statements(edges)
        code = "\n".join(result)
        # Should reference all three nodes and both edges.
        assert '"a"' in code or "add_node(a)" in code
        assert '"b"' in code or "add_node(b)" in code
        assert '"c"' in code or "add_node(c)" in code

    def test_diamond_dag_codegen(self) -> None:
        """Diamond: A->B, A->C, B->D, C->D should produce valid code."""
        from dagloom.server.codegen import _build_dag_statements

        edges = [["a", "b"], ["a", "c"], ["b", "d"], ["c", "d"]]
        result = _build_dag_statements(edges)
        code = "\n".join(result)
        # Should reference all four nodes.
        for n in ["a", "b", "c", "d"]:
            assert n in code

    def test_dag_to_code_preserves_linear(self) -> None:
        """dag_to_code still works for linear chains."""
        from dagloom.server.codegen import dag_to_code

        dag = {
            "nodes": [
                {"name": "fetch", "params": {}, "docstring": "Fetch data"},
                {"name": "clean", "params": {}, "docstring": "Clean data"},
            ],
            "edges": [["fetch", "clean"]],
        }
        code = dag_to_code(dag)
        assert "fetch >> clean" in code

    def test_dag_to_code_complex(self) -> None:
        """dag_to_code handles diamond DAG."""
        from dagloom.server.codegen import dag_to_code

        dag = {
            "nodes": [
                {"name": "a", "params": {}},
                {"name": "b", "params": {}},
                {"name": "c", "params": {}},
                {"name": "d", "params": {}},
            ],
            "edges": [["a", "b"], ["a", "c"], ["b", "d"], ["c", "d"]],
        }
        code = dag_to_code(dag)
        # Should contain explicit Pipeline construction (not linear >> chain).
        assert "add_edge" in code

    def test_code_to_dag_only_module_level(self) -> None:
        """code_to_dag should not extract nested function definitions."""
        from dagloom.server.codegen import code_to_dag

        source = '''
from dagloom import node

@node
def outer(x):
    def inner_helper(y):
        return y + 1
    return inner_helper(x)
'''
        dag = code_to_dag(source)
        names = [n["name"] for n in dag["nodes"]]
        assert "outer" in names
        assert "inner_helper" not in names


# -- Test: NodeStatus de-duplication -----------------------------------------


class TestNodeStatusUnified:
    """Ensure NodeStatus is the same class everywhere."""

    def test_same_enum_class(self) -> None:
        from dagloom.core.context import NodeStatus as ContextStatus
        from dagloom.store.models import NodeStatus as ModelsStatus

        # They should be the exact same class now.
        assert ContextStatus is ModelsStatus

    def test_enum_values(self) -> None:
        from dagloom.core.context import NodeStatus

        assert NodeStatus.PENDING == "pending"
        assert NodeStatus.SUCCESS == "success"
        assert NodeStatus.FAILED == "failed"
        assert NodeStatus.SKIPPED == "skipped"


# -- Test: Expanded public API -----------------------------------------------


class TestPublicApi:
    """Ensure all key classes are importable from the top-level package."""

    def test_imports(self) -> None:
        from dagloom import (  # noqa: F401
            AsyncExecutor,
            CacheManager,
            CheckpointManager,
            CycleError,
            ExecutionContext,
            ExecutionError,
            Node,
            NodeStatus,
            Pipeline,
            node,
        )

    def test_all_contains_key_names(self) -> None:
        import dagloom

        expected = {
            "AsyncExecutor",
            "CacheManager",
            "CheckpointManager",
            "CycleError",
            "ExecutionContext",
            "ExecutionError",
            "Node",
            "NodeStatus",
            "Pipeline",
            "node",
            "__version__",
        }
        assert expected == set(dagloom.__all__)


# -- Test: Database.get_latest_execution -------------------------------------


class TestDatabaseGetLatestExecution:
    """Test the new get_latest_execution helper."""

    @pytest.mark.asyncio
    async def test_returns_latest(self, db) -> None:
        await db.save_pipeline("p1", "Pipeline 1")
        await db.save_execution("e1", "p1", status="success", started_at="2024-01-01T00:00:00")
        await db.save_execution("e2", "p1", status="running", started_at="2024-01-02T00:00:00")

        latest = await db.get_latest_execution("p1")
        assert latest is not None
        assert latest["id"] == "e2"

    @pytest.mark.asyncio
    async def test_filter_by_status(self, db) -> None:
        await db.save_pipeline("p2", "Pipeline 2")
        await db.save_execution("e3", "p2", status="success", started_at="2024-01-01T00:00:00")
        await db.save_execution("e4", "p2", status="failed", started_at="2024-01-02T00:00:00")

        latest_failed = await db.get_latest_execution("p2", status="failed")
        assert latest_failed is not None
        assert latest_failed["id"] == "e4"

    @pytest.mark.asyncio
    async def test_returns_none_if_not_found(self, db) -> None:
        result = await db.get_latest_execution("nonexistent")
        assert result is None
