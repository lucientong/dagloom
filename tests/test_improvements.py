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
from typing import Any

import pytest

from dagloom.core.node import node
from dagloom.core.pipeline import Pipeline
from dagloom.scheduler.cache import CacheManager
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

        source = """
from dagloom import node

@node
def outer(x):
    def inner_helper(y):
        return y + 1
    return inner_helper(x)
"""
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
            "Branch",
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


# -- Test: Conditional branching (| operator) --------------------------------


class TestConditionalBranching:
    """Test the | operator and branch selection logic."""

    def test_branch_creation_via_or(self) -> None:
        """node_a | node_b should create a Branch with two nodes."""
        from dagloom.core.node import Branch

        @node
        def branch_a(x: int) -> int:
            return x + 1

        @node
        def branch_b(x: int) -> int:
            return x + 2

        branch = branch_a | branch_b
        assert isinstance(branch, Branch)
        assert len(branch.nodes) == 2
        assert branch.nodes[0].name == "branch_a"
        assert branch.nodes[1].name == "branch_b"

    def test_branch_triple_or(self) -> None:
        """node_a | node_b | node_c should create a Branch with three nodes."""
        from dagloom.core.node import Branch

        @node
        def opt_1(x: int) -> int:
            return 1

        @node
        def opt_2(x: int) -> int:
            return 2

        @node
        def opt_3(x: int) -> int:
            return 3

        branch = opt_1 | opt_2 | opt_3
        assert isinstance(branch, Branch)
        assert len(branch.nodes) == 3

    def test_branch_repr(self) -> None:
        @node
        def x_node(x: int) -> int:
            return x

        @node
        def y_node(x: int) -> int:
            return x

        branch = x_node | y_node
        assert "x_node" in repr(branch)
        assert "y_node" in repr(branch)

    def test_pipeline_with_branch_dict_selector(self) -> None:
        """Branch selection via dict with 'branch' key."""

        @node
        def router(x: int) -> dict:
            if x > 0:
                return {"branch": "positive", "value": x}
            return {"branch": "negative", "value": x}

        @node
        def positive(data: dict) -> str:
            return f"positive:{data['value']}"

        @node
        def negative(data: dict) -> str:
            return f"negative:{data['value']}"

        pipe = router >> (positive | negative)
        result = pipe.run(x=5)
        assert result == "positive:5"

    def test_pipeline_with_branch_boolean_selector(self) -> None:
        """Branch selection via truthy/falsy output for two-branch group."""

        @node
        def checker(x: int) -> bool:
            return x > 0

        @node
        def yes_path(flag: bool) -> str:
            return "yes"

        @node
        def no_path(flag: bool) -> str:
            return "no"

        pipe_true = checker >> (yes_path | no_path)
        assert pipe_true.run(x=10) == "yes"

        pipe_false = checker >> (yes_path | no_path)
        assert pipe_false.run(x=-5) == "no"

    def test_select_branch_fallback(self) -> None:
        """Fallback: select first branch when no special output."""
        from dagloom.core.node import Branch
        from dagloom.core.pipeline import _select_branch

        @node
        def first(x: int) -> int:
            return x

        @node
        def second(x: int) -> int:
            return x

        @node
        def third(x: int) -> int:
            return x

        branch = Branch([first, second, third])
        # Non-dict, non-boolean with 3 branches: should select first.
        assert _select_branch("hello", branch) == "first"

    @pytest.mark.asyncio
    async def test_async_executor_with_branch(self) -> None:
        """AsyncExecutor should handle branch selection."""

        @node
        def decider(x: int) -> dict:
            return {"branch": "path_b", "data": x}

        @node
        def path_a(data: dict) -> str:
            return "a"

        @node
        def path_b(data: dict) -> str:
            return "b"

        pipe = decider >> (path_a | path_b)
        executor = AsyncExecutor(pipe)
        result = await executor.execute(x=1)
        assert result == "b"


# -- Test: Node streaming (generator/async generator) ------------------------


class TestNodeStreaming:
    """Test generator and async generator node functions."""

    def test_sync_generator_node(self) -> None:
        """Generator node should be collected into a list."""

        @node
        def gen_items(n: int) -> list:
            for i in range(n):
                yield i * 10

        pipe = Pipeline()
        pipe.add_node(gen_items)
        pipe._tail_nodes = ["gen_items"]

        result = pipe.run(n=4)
        assert result == [0, 10, 20, 30]

    def test_sync_generator_in_chain(self) -> None:
        """Generator node in a pipeline chain."""

        @node
        def source(n: int) -> int:
            return n

        @node
        def expand(x: int) -> list:
            yield from range(x)

        @node
        def count(items: list) -> int:
            return len(items)

        pipe = source >> expand >> count
        result = pipe.run(n=5)
        assert result == 5

    def test_async_generator_node(self) -> None:
        """Async generator node should be collected into a list."""

        @node
        async def async_gen(n: int) -> list:
            for i in range(n):
                yield i * 2

        pipe = Pipeline()
        pipe.add_node(async_gen)
        pipe._tail_nodes = ["async_gen"]

        result = pipe.run(n=3)
        assert result == [0, 2, 4]

    @pytest.mark.asyncio
    async def test_async_executor_generator(self) -> None:
        """AsyncExecutor should handle generator nodes."""

        @node
        def gen_squares(n: int) -> list:
            for i in range(n):
                yield i**2

        pipe = Pipeline()
        pipe.add_node(gen_squares)
        pipe._tail_nodes = ["gen_squares"]

        executor = AsyncExecutor(pipe)
        result = await executor.execute(n=4)
        assert result == [0, 1, 4, 9]

    @pytest.mark.asyncio
    async def test_async_executor_async_generator(self) -> None:
        """AsyncExecutor should handle async generator nodes."""

        @node
        async def async_gen_cubes(n: int) -> list:
            for i in range(n):
                yield i**3

        pipe = Pipeline()
        pipe.add_node(async_gen_cubes)
        pipe._tail_nodes = ["async_gen_cubes"]

        executor = AsyncExecutor(pipe)
        result = await executor.execute(n=3)
        assert result == [0, 1, 8]


# -- Test: Node execution hooks (on_node_start / on_node_end) ----------------


class TestNodeExecutionHooks:
    """Test on_node_start and on_node_end hooks in AsyncExecutor."""

    @pytest.mark.asyncio
    async def test_hooks_called_on_success(self) -> None:
        """Hooks should be called for each node in execution order."""
        events: list[str] = []

        def on_start(name: str, ctx: Any) -> None:
            events.append(f"start:{name}")

        def on_end(name: str, ctx: Any) -> None:
            events.append(f"end:{name}")

        @node
        def step1(x: int) -> int:
            return x + 1

        @node
        def step2(x: int) -> int:
            return x * 2

        pipe = step1 >> step2
        executor = AsyncExecutor(pipe, on_node_start=on_start, on_node_end=on_end)
        result = await executor.execute(x=3)

        assert result == 8  # (3+1)*2
        assert "start:step1" in events
        assert "end:step1" in events
        assert "start:step2" in events
        assert "end:step2" in events

    @pytest.mark.asyncio
    async def test_hooks_called_on_failure(self) -> None:
        """Hooks should be called even when a node fails."""
        events: list[str] = []

        def on_start(name: str, ctx: Any) -> None:
            events.append(f"start:{name}")

        def on_end(name: str, ctx: Any) -> None:
            events.append(f"end:{name}")

        @node
        def fail_step(x: int) -> int:
            raise ValueError("boom")

        pipe = Pipeline()
        pipe.add_node(fail_step)
        pipe._tail_nodes = ["fail_step"]

        executor = AsyncExecutor(pipe, on_node_start=on_start, on_node_end=on_end)
        with pytest.raises(ExecutionError):
            await executor.execute(x=1)

        assert "start:fail_step" in events
        assert "end:fail_step" in events

    @pytest.mark.asyncio
    async def test_async_hooks(self) -> None:
        """Async hook functions should be awaited."""
        events: list[str] = []

        async def on_start(name: str, ctx: Any) -> None:
            events.append(f"async_start:{name}")

        async def on_end(name: str, ctx: Any) -> None:
            events.append(f"async_end:{name}")

        @node
        def compute(x: int) -> int:
            return x * 10

        pipe = Pipeline()
        pipe.add_node(compute)
        pipe._tail_nodes = ["compute"]

        executor = AsyncExecutor(pipe, on_node_start=on_start, on_node_end=on_end)
        result = await executor.execute(x=7)
        assert result == 70
        assert "async_start:compute" in events
        assert "async_end:compute" in events

    @pytest.mark.asyncio
    async def test_hook_errors_do_not_break_execution(self) -> None:
        """Hook errors should be swallowed, not break the pipeline."""

        def bad_hook(name: str, ctx: Any) -> None:
            raise RuntimeError("hook error")

        @node
        def ok_node(x: int) -> int:
            return x + 1

        pipe = Pipeline()
        pipe.add_node(ok_node)
        pipe._tail_nodes = ["ok_node"]

        executor = AsyncExecutor(pipe, on_node_start=bad_hook, on_node_end=bad_hook)
        # Should not raise despite bad hooks.
        result = await executor.execute(x=5)
        assert result == 6

    @pytest.mark.asyncio
    async def test_no_hooks_is_fine(self) -> None:
        """Execution without hooks should work as before."""

        @node
        def identity(x: int) -> int:
            return x

        pipe = Pipeline()
        pipe.add_node(identity)
        pipe._tail_nodes = ["identity"]

        executor = AsyncExecutor(pipe)
        result = await executor.execute(x=42)
        assert result == 42


# -- Test: Updated public API (Branch export) --------------------------------


class TestPublicApiBranch:
    """Ensure Branch is now importable from top-level."""

    def test_branch_import(self) -> None:
        from dagloom import Branch  # noqa: F401

        assert Branch is not None

    def test_all_contains_branch(self) -> None:
        import dagloom

        assert "Branch" in dagloom.__all__

    def test_version_is_030(self) -> None:
        import dagloom

        assert dagloom.__version__ == "0.3.0"
