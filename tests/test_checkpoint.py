"""Tests for the CheckpointManager."""

import pytest

from dagloom.scheduler.checkpoint import CheckpointManager
from dagloom.store.db import Database


@pytest.fixture
async def db(tmp_path):
    """Provide a fresh database for each test."""
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    await database.connect()
    # Create a test pipeline to satisfy foreign key constraints.
    await database.save_pipeline("pipe-1", "test-pipeline")
    yield database
    await database.close()


@pytest.fixture
async def ckpt(db):
    """Provide a CheckpointManager."""
    return CheckpointManager(db)


class TestCheckpointManager:
    """Test checkpoint state persistence and resume logic."""

    @pytest.mark.asyncio
    async def test_init_execution(self, ckpt, db) -> None:
        await ckpt.init_execution("exec-1", "pipe-1")
        record = await db.get_execution("exec-1")
        assert record is not None
        assert record["status"] == "running"

    @pytest.mark.asyncio
    async def test_save_and_query_state(self, ckpt) -> None:
        await ckpt.init_execution("exec-2", "pipe-1")
        await ckpt.save_state("exec-2", "pipe-1", "node_a", "success")
        await ckpt.save_state("exec-2", "pipe-1", "node_b", "failed", error_message="boom")

        states = await ckpt.get_node_states("exec-2")
        assert states["node_a"] == "success"
        assert states["node_b"] == "failed"

    @pytest.mark.asyncio
    async def test_get_completed_nodes(self, ckpt) -> None:
        await ckpt.init_execution("exec-3", "pipe-1")
        await ckpt.save_state("exec-3", "pipe-1", "node_a", "success")
        await ckpt.save_state("exec-3", "pipe-1", "node_b", "success")
        await ckpt.save_state("exec-3", "pipe-1", "node_c", "failed")

        completed = await ckpt.get_completed_nodes("exec-3")
        assert completed == {"node_a", "node_b"}

    @pytest.mark.asyncio
    async def test_should_skip(self, ckpt) -> None:
        await ckpt.init_execution("exec-4", "pipe-1")
        await ckpt.save_state("exec-4", "pipe-1", "node_a", "success")

        assert await ckpt.should_skip("exec-4", "node_a") is True
        assert await ckpt.should_skip("exec-4", "node_b") is False

    @pytest.mark.asyncio
    async def test_finish_execution_success(self, ckpt, db) -> None:
        await ckpt.init_execution("exec-5", "pipe-1")
        await ckpt.finish_execution("exec-5", "pipe-1", success=True)

        record = await db.get_execution("exec-5")
        assert record["status"] == "success"
        assert record["finished_at"] is not None

    @pytest.mark.asyncio
    async def test_finish_execution_failure(self, ckpt, db) -> None:
        await ckpt.init_execution("exec-6", "pipe-1")
        await ckpt.finish_execution("exec-6", "pipe-1", success=False, error_message="error")

        record = await db.get_execution("exec-6")
        assert record["status"] == "failed"
        assert record["error_message"] == "error"

    @pytest.mark.asyncio
    async def test_resume_workflow(self, ckpt) -> None:
        """Simulate a resume: nodes a,b succeeded, c failed."""
        exec_id = "exec-resume"
        await ckpt.init_execution(exec_id, "pipe-1")
        await ckpt.save_state(exec_id, "pipe-1", "a", "success")
        await ckpt.save_state(exec_id, "pipe-1", "b", "success")
        await ckpt.save_state(exec_id, "pipe-1", "c", "failed", error_message="oops")

        # On resume, a and b should be skipped, c should run.
        assert await ckpt.should_skip(exec_id, "a") is True
        assert await ckpt.should_skip(exec_id, "b") is True
        assert await ckpt.should_skip(exec_id, "c") is False
