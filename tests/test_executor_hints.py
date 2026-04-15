"""Tests for per-node executor hints (P1-4).

Covers:
- Node and @node decorator: ``executor`` parameter validation
- AsyncExecutor: per-node dispatch to thread vs process pool
- ProcessExecutor: backward-compatible all-process execution
- Mixed pipelines: some nodes in process, some in thread
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import pytest_asyncio

from dagloom import AsyncExecutor, Pipeline, node
from dagloom.core.node import EXECUTOR_HINTS, Node
from dagloom.scheduler.process_executor import ProcessExecutor
from dagloom.store.db import Database

# ---------------------------------------------------------------------------
# Module-level node functions (picklable for process pool)
# ---------------------------------------------------------------------------


def _add_one(x: int) -> int:
    return x + 1


def _square(x: int) -> int:
    return x * x


def _get_pid(x: int) -> int:
    return os.getpid()


def _double(x: int) -> int:
    return x * 2


def _mul_two(x: int) -> int:
    return x * 2


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


# ---------------------------------------------------------------------------
# Node executor hint
# ---------------------------------------------------------------------------


class TestNodeExecutorHint:
    """Tests for the executor parameter on Node and @node."""

    def test_default_executor_is_auto(self) -> None:
        """Node without explicit executor defaults to 'auto'."""

        @node
        def step(x: int) -> int:
            return x + 1

        assert step.executor == "auto"

    def test_executor_process(self) -> None:
        """@node(executor='process') sets the hint."""

        @node(executor="process")
        def heavy(x: int) -> int:
            return x * x

        assert heavy.executor == "process"

    def test_executor_async(self) -> None:
        """@node(executor='async') sets the hint."""

        @node(executor="async")
        def light(x: int) -> int:
            return x

        assert light.executor == "async"

    def test_invalid_executor_raises(self) -> None:
        """Invalid executor hint raises ValueError."""
        with pytest.raises(ValueError, match="Invalid executor hint"):
            Node(name="bad", fn=lambda x: x, executor="gpu")

    def test_executor_hints_constant(self) -> None:
        """EXECUTOR_HINTS contains all valid values."""
        assert {"auto", "async", "process"} == EXECUTOR_HINTS

    def test_repr_includes_executor(self) -> None:
        """Non-default executor appears in repr."""

        @node(executor="process")
        def proc(x: int) -> int:
            return x

        assert "executor='process'" in repr(proc)

    def test_repr_omits_auto_executor(self) -> None:
        """Default 'auto' executor is omitted from repr."""

        @node
        def step(x: int) -> int:
            return x

        assert "executor" not in repr(step)

    def test_executor_combined_with_other_params(self) -> None:
        """executor works alongside retry, cache, timeout."""

        @node(retry=2, cache=True, timeout=10.0, executor="process")
        def full(x: int) -> int:
            return x

        assert full.executor == "process"
        assert full.retry == 2
        assert full.cache is True
        assert full.timeout == 10.0


# ---------------------------------------------------------------------------
# AsyncExecutor per-node dispatch
# ---------------------------------------------------------------------------


class TestAsyncExecutorDispatch:
    """Tests for per-node executor dispatch in AsyncExecutor."""

    @pytest.mark.asyncio
    async def test_auto_sync_runs_in_thread(self) -> None:
        """executor='auto' with sync function uses asyncio.to_thread."""

        @node
        def step(x: int) -> int:
            return x + 1

        pipeline = Pipeline()
        pipeline.add_node(step)
        pipeline._tail_nodes = ["step"]

        executor = AsyncExecutor(pipeline)
        result = await executor.execute(x=5)
        assert result == 6

    @pytest.mark.asyncio
    async def test_auto_async_runs_directly(self) -> None:
        """executor='auto' with async function awaits directly."""

        @node
        async def step(x: int) -> int:
            return x + 1

        pipeline = Pipeline()
        pipeline.add_node(step)
        pipeline._tail_nodes = ["step"]

        executor = AsyncExecutor(pipeline)
        result = await executor.execute(x=5)
        assert result == 6

    @pytest.mark.asyncio
    async def test_process_runs_in_separate_process(self) -> None:
        """executor='process' runs sync function in a process pool."""
        pid_node = Node(name="get_pid", fn=_get_pid, executor="process")

        pipeline = Pipeline()
        pipeline.add_node(pid_node)
        pipeline._tail_nodes = ["get_pid"]

        executor = AsyncExecutor(pipeline)
        result = await executor.execute(x=0)
        assert isinstance(result, int)
        assert result != os.getpid()

    @pytest.mark.asyncio
    async def test_mixed_pipeline(self) -> None:
        """Pipeline with both 'auto' and 'process' nodes."""
        add_node = Node(name="add_one", fn=_add_one)
        sq_node = Node(name="square", fn=_square, executor="process")

        pipeline = Pipeline()
        pipeline.add_node(add_node)
        pipeline.add_node(sq_node)
        pipeline.add_edge("add_one", "square")
        pipeline._tail_nodes = ["square"]

        executor = AsyncExecutor(pipeline)
        result = await executor.execute(x=3)
        assert result == 16  # (3+1)^2

    @pytest.mark.asyncio
    async def test_process_pool_shutdown_after_execute(self) -> None:
        """Process pool is cleaned up after execute completes."""
        step_node = Node(name="step", fn=_double, executor="process")

        pipeline = Pipeline()
        pipeline.add_node(step_node)
        pipeline._tail_nodes = ["step"]

        executor = AsyncExecutor(pipeline)
        await executor.execute(x=1)
        assert executor._process_pool is None

    @pytest.mark.asyncio
    async def test_no_pool_when_no_process_nodes(self) -> None:
        """No process pool is created if no nodes use executor='process'."""

        @node
        def step(x: int) -> int:
            return x + 1

        pipeline = Pipeline()
        pipeline.add_node(step)
        pipeline._tail_nodes = ["step"]

        executor = AsyncExecutor(pipeline)
        await executor.execute(x=1)
        assert executor._process_pool is None

    @pytest.mark.asyncio
    async def test_async_executor_hint_with_async_fn(self) -> None:
        """executor='async' with async function works normally."""

        @node(executor="async")
        async def step(x: int) -> int:
            return x + 10

        pipeline = Pipeline()
        pipeline.add_node(step)
        pipeline._tail_nodes = ["step"]

        executor = AsyncExecutor(pipeline)
        result = await executor.execute(x=5)
        assert result == 15

    @pytest.mark.asyncio
    async def test_process_node_with_cache(self) -> None:
        """executor='process' works alongside cache=True."""
        compute_node = Node(name="compute", fn=_double, executor="process", cache=True)

        pipeline = Pipeline()
        pipeline.add_node(compute_node)
        pipeline._tail_nodes = ["compute"]

        executor = AsyncExecutor(pipeline)
        result = await executor.execute(x=5)
        assert result == 10


# ---------------------------------------------------------------------------
# ProcessExecutor backward compatibility
# ---------------------------------------------------------------------------


class TestProcessExecutor:
    """Tests for ProcessExecutor backward compatibility."""

    @pytest.mark.asyncio
    async def test_process_executor_runs(self) -> None:
        """ProcessExecutor runs all sync nodes in process pool."""
        add_node = Node(name="add", fn=_add_one)
        mul_node = Node(name="mul", fn=_mul_two)

        pipeline = Pipeline()
        pipeline.add_node(add_node)
        pipeline.add_node(mul_node)
        pipeline.add_edge("add", "mul")
        pipeline._tail_nodes = ["mul"]

        executor = ProcessExecutor(pipeline, max_workers=2)
        result = await executor.execute(x=3)
        assert result == 8  # (3+1)*2

    @pytest.mark.asyncio
    async def test_process_executor_sets_hints(self) -> None:
        """ProcessExecutor sets all 'auto' nodes to 'process'."""
        step_a = Node(name="step_a", fn=_add_one)

        @node(executor="async")
        async def step_b(x: int) -> int:
            return x + 1

        pipeline = Pipeline()
        pipeline.add_node(step_a)
        pipeline.add_node(step_b)
        pipeline.add_edge("step_a", "step_b")
        pipeline._tail_nodes = ["step_b"]

        ProcessExecutor(pipeline, max_workers=1)
        assert pipeline.nodes["step_a"].executor == "process"
        assert pipeline.nodes["step_b"].executor == "async"

    @pytest.mark.asyncio
    async def test_process_executor_pid(self) -> None:
        """ProcessExecutor dispatches to a different process."""
        pid_node = Node(name="get_pid", fn=_get_pid)

        pipeline = Pipeline()
        pipeline.add_node(pid_node)
        pipeline._tail_nodes = ["get_pid"]

        executor = ProcessExecutor(pipeline, max_workers=1)
        result = await executor.execute(x=0)
        assert isinstance(result, int)
        assert result != os.getpid()
