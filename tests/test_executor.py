"""Tests for the AsyncExecutor and ProcessExecutor."""

import asyncio

import pytest

from dagloom.core.node import node
from dagloom.scheduler.executor import AsyncExecutor, ExecutionError


class TestAsyncExecutorBasic:
    """Basic async execution tests."""

    @pytest.mark.asyncio
    async def test_simple_chain(self) -> None:
        @node
        def add_one(x: int) -> int:
            return x + 1

        @node
        def double(x: int) -> int:
            return x * 2

        pipeline = add_one >> double
        executor = AsyncExecutor(pipeline)
        result = await executor.execute(x=5)
        assert result == 12  # (5+1)*2

    @pytest.mark.asyncio
    async def test_three_step_chain(self) -> None:
        @node
        def step1(x: int) -> int:
            return x + 1

        @node
        def step2(x: int) -> int:
            return x * 3

        @node
        def step3(x: int) -> str:
            return f"result={x}"

        pipeline = step1 >> step2 >> step3
        executor = AsyncExecutor(pipeline)
        result = await executor.execute(x=2)
        assert result == "result=9"  # (2+1)*3=9

    @pytest.mark.asyncio
    async def test_async_node_function(self) -> None:
        @node
        async def async_add(x: int) -> int:
            await asyncio.sleep(0.01)
            return x + 10

        @node
        def sync_double(x: int) -> int:
            return x * 2

        pipeline = async_add >> sync_double
        executor = AsyncExecutor(pipeline)
        result = await executor.execute(x=5)
        assert result == 30  # (5+10)*2


class TestAsyncExecutorParallel:
    """Test parallel execution of independent nodes."""

    @pytest.mark.asyncio
    async def test_parallel_nodes_execute(self) -> None:
        """Two independent nodes should run concurrently."""
        from dagloom.core.pipeline import Pipeline

        call_order: list[str] = []

        @node
        async def root(x: int) -> int:
            return x

        @node
        async def branch_a(x: int) -> int:
            call_order.append("a_start")
            await asyncio.sleep(0.05)
            call_order.append("a_end")
            return x + 1

        @node
        async def branch_b(x: int) -> int:
            call_order.append("b_start")
            await asyncio.sleep(0.05)
            call_order.append("b_end")
            return x + 2

        pipe = Pipeline()
        pipe.add_node(root)
        pipe.add_node(branch_a)
        pipe.add_node(branch_b)
        pipe.add_edge("root", "branch_a")
        pipe.add_edge("root", "branch_b")
        pipe._tail_nodes = ["branch_a", "branch_b"]

        executor = AsyncExecutor(pipe)
        result = await executor.execute(x=10)

        # Both branches should have started before either finished.
        assert isinstance(result, dict)
        assert result["branch_a"] == 11
        assert result["branch_b"] == 12


class TestAsyncExecutorTimeout:
    """Test per-node timeout."""

    @pytest.mark.asyncio
    async def test_timeout_raises(self) -> None:
        @node(timeout=0.05)
        async def slow_node(x: int) -> int:
            await asyncio.sleep(10)  # Way too long
            return x

        from dagloom.core.pipeline import Pipeline

        pipe = Pipeline()
        pipe.add_node(slow_node)
        pipe._tail_nodes = ["slow_node"]

        executor = AsyncExecutor(pipe)
        with pytest.raises(ExecutionError, match="slow_node"):
            await executor.execute(x=1)


class TestAsyncExecutorRetry:
    """Test retry with exponential backoff."""

    @pytest.mark.asyncio
    async def test_retry_on_failure(self) -> None:
        call_count = 0

        @node(retry=2)
        def flaky(x: int) -> int:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return x * 10

        from dagloom.core.pipeline import Pipeline

        pipe = Pipeline()
        pipe.add_node(flaky)
        pipe._tail_nodes = ["flaky"]

        executor = AsyncExecutor(pipe, retry_base_delay=0.01)
        result = await executor.execute(x=5)
        assert result == 50
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self) -> None:
        @node(retry=1)
        def always_fail(x: int) -> int:
            raise RuntimeError("permanent failure")

        from dagloom.core.pipeline import Pipeline

        pipe = Pipeline()
        pipe.add_node(always_fail)
        pipe._tail_nodes = ["always_fail"]

        executor = AsyncExecutor(pipe, retry_base_delay=0.01)
        with pytest.raises(ExecutionError, match="always_fail"):
            await executor.execute(x=1)


class TestAsyncExecutorErrors:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_node_exception_propagates(self) -> None:
        @node
        def ok(x: int) -> int:
            return x

        @node
        def bad(x: int) -> int:
            raise ValueError("boom")

        pipeline = ok >> bad
        executor = AsyncExecutor(pipeline)
        with pytest.raises(ExecutionError, match="bad"):
            await executor.execute(x=1)
