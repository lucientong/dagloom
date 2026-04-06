"""Tests for the ExecutionContext."""

from dagloom.core.context import ExecutionContext, NodeExecutionInfo, NodeStatus


class TestNodeExecutionInfo:
    """Test node execution metadata tracking."""

    def test_initial_state(self) -> None:
        info = NodeExecutionInfo(node_name="test")
        assert info.status == NodeStatus.PENDING
        assert info.started_at is None
        assert info.finished_at is None
        assert info.duration is None

    def test_mark_running(self) -> None:
        info = NodeExecutionInfo(node_name="test")
        info.mark_running()
        assert info.status == NodeStatus.RUNNING
        assert info.started_at is not None

    def test_mark_success(self) -> None:
        info = NodeExecutionInfo(node_name="test")
        info.mark_running()
        info.mark_success()
        assert info.status == NodeStatus.SUCCESS
        assert info.finished_at is not None
        assert info.duration is not None
        assert info.duration >= 0

    def test_mark_failed(self) -> None:
        info = NodeExecutionInfo(node_name="test")
        info.mark_running()
        info.mark_failed("something broke")
        assert info.status == NodeStatus.FAILED
        assert info.error == "something broke"
        assert info.duration is not None

    def test_mark_skipped(self) -> None:
        info = NodeExecutionInfo(node_name="test")
        info.mark_skipped()
        assert info.status == NodeStatus.SKIPPED


class TestExecutionContext:
    """Test pipeline execution context."""

    def test_unique_execution_id(self) -> None:
        ctx1 = ExecutionContext()
        ctx2 = ExecutionContext()
        assert ctx1.execution_id != ctx2.execution_id

    def test_set_and_get_output(self) -> None:
        ctx = ExecutionContext()
        ctx.set_output("node_a", 42)
        assert ctx.get_output("node_a") == 42

    def test_get_missing_output_raises(self) -> None:
        ctx = ExecutionContext()
        import pytest

        with pytest.raises(KeyError, match="node_x"):
            ctx.get_output("node_x")

    def test_has_output(self) -> None:
        ctx = ExecutionContext()
        assert not ctx.has_output("node_a")
        ctx.set_output("node_a", "value")
        assert ctx.has_output("node_a")

    def test_get_node_info_creates_on_first_access(self) -> None:
        ctx = ExecutionContext()
        info = ctx.get_node_info("node_a")
        assert isinstance(info, NodeExecutionInfo)
        assert info.node_name == "node_a"
        assert info.status == NodeStatus.PENDING

        # Second access returns the same object.
        info2 = ctx.get_node_info("node_a")
        assert info is info2

    def test_is_complete(self) -> None:
        ctx = ExecutionContext()
        ctx.get_node_info("a").mark_running()
        ctx.get_node_info("a").mark_success()
        ctx.get_node_info("b").mark_skipped()
        assert ctx.is_complete

    def test_is_not_complete_with_running(self) -> None:
        ctx = ExecutionContext()
        ctx.get_node_info("a").mark_running()
        ctx.get_node_info("a").mark_success()
        ctx.get_node_info("b").mark_running()
        assert not ctx.is_complete

    def test_is_success(self) -> None:
        ctx = ExecutionContext()
        ctx.get_node_info("a").mark_running()
        ctx.get_node_info("a").mark_success()
        ctx.get_node_info("b").mark_skipped()
        assert ctx.is_success

    def test_is_not_success_with_failure(self) -> None:
        ctx = ExecutionContext()
        ctx.get_node_info("a").mark_running()
        ctx.get_node_info("a").mark_success()
        ctx.get_node_info("b").mark_running()
        ctx.get_node_info("b").mark_failed("error")
        assert not ctx.is_success

    def test_failed_nodes(self) -> None:
        ctx = ExecutionContext()
        ctx.get_node_info("a").mark_running()
        ctx.get_node_info("a").mark_success()
        ctx.get_node_info("b").mark_running()
        ctx.get_node_info("b").mark_failed("error")
        assert ctx.failed_nodes == ["b"]

    def test_summary(self) -> None:
        ctx = ExecutionContext(pipeline_name="test_pipe")
        ctx.get_node_info("a").mark_running()
        ctx.get_node_info("a").mark_success()

        summary = ctx.summary()
        assert summary["pipeline_name"] == "test_pipe"
        assert summary["is_complete"] is True
        assert summary["is_success"] is True
        assert "a" in summary["nodes"]
        assert summary["nodes"]["a"]["status"] == "success"

    def test_metadata(self) -> None:
        ctx = ExecutionContext()
        ctx.metadata["key"] = "value"
        assert ctx.metadata["key"] == "value"
