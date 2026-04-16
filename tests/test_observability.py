"""Tests for observability features (node metrics, execution history).

Covers:
- Database: node_metrics CRUD, get_node_stats, get_execution_history
- AsyncExecutor: metrics_db instrumentation (success + failure recording)
- API: GET /api/metrics/{pipeline_id}, GET /api/history/{pipeline_id}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from dagloom.core.node import node
from dagloom.core.pipeline import Pipeline
from dagloom.scheduler.executor import AsyncExecutor
from dagloom.server.api import router as api_router
from dagloom.server.api import set_state
from dagloom.store.db import Database

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:  # type: ignore[misc]
    """Create a temporary database."""
    _db = Database(tmp_path / "test_metrics.db")
    await _db.connect()
    yield _db  # type: ignore[misc]
    await _db.close()


@pytest_asyncio.fixture
async def client(db: Database) -> Any:  # type: ignore[misc]
    """Create a test HTTP client with metrics endpoints."""
    set_state("db", db)
    app = FastAPI()
    app.include_router(api_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ===========================================================================
# Database Node Metrics Tests
# ===========================================================================


class TestNodeMetricsDB:
    """Tests for node_metrics CRUD in Database."""

    @pytest.mark.asyncio
    async def test_save_and_get_node_metric(self, db: Database) -> None:
        """Save a metric and retrieve it."""
        await db.save_node_metric(
            pipeline_id="pipe1",
            execution_id="exec1",
            node_id="fetch",
            wall_time_ms=123.45,
            outcome="success",
            retry_count=0,
        )
        metrics = await db.get_node_metrics("fetch")
        assert len(metrics) == 1
        assert metrics[0]["node_id"] == "fetch"
        assert metrics[0]["wall_time_ms"] == 123.45
        assert metrics[0]["outcome"] == "success"

    @pytest.mark.asyncio
    async def test_get_node_metrics_ordering(self, db: Database) -> None:
        """Metrics are returned most-recent-first."""
        for i in range(3):
            await db.save_node_metric(
                pipeline_id="pipe1",
                execution_id=f"exec{i}",
                node_id="transform",
                wall_time_ms=float(i * 100),
                outcome="success",
            )
        metrics = await db.get_node_metrics("transform")
        assert len(metrics) == 3
        # Most recent first (last inserted has the latest recorded_at).
        assert metrics[0]["wall_time_ms"] == 200.0

    @pytest.mark.asyncio
    async def test_get_node_metrics_limit(self, db: Database) -> None:
        """Limit parameter restricts results."""
        for i in range(5):
            await db.save_node_metric(
                pipeline_id="pipe1",
                execution_id=f"exec{i}",
                node_id="save",
                wall_time_ms=float(i),
                outcome="success",
            )
        metrics = await db.get_node_metrics("save", limit=2)
        assert len(metrics) == 2

    @pytest.mark.asyncio
    async def test_get_pipeline_metrics(self, db: Database) -> None:
        """Pipeline metrics returns all nodes for the pipeline."""
        await db.save_node_metric("pipe1", "exec1", "fetch", 100.0, "success")
        await db.save_node_metric("pipe1", "exec1", "transform", 200.0, "success")
        await db.save_node_metric("pipe2", "exec2", "other", 300.0, "success")

        metrics = await db.get_pipeline_metrics("pipe1")
        assert len(metrics) == 2
        node_ids = {m["node_id"] for m in metrics}
        assert node_ids == {"fetch", "transform"}

    @pytest.mark.asyncio
    async def test_get_node_stats(self, db: Database) -> None:
        """Aggregate stats computed correctly."""
        for ms in [100.0, 200.0, 300.0, 400.0, 500.0]:
            await db.save_node_metric("pipe1", f"e{int(ms)}", "fetch", ms, "success")
        await db.save_node_metric("pipe1", "e_fail", "fetch", 50.0, "failed")

        stats = await db.get_node_stats("pipe1")
        assert len(stats) == 1
        s = stats[0]
        assert s["node_id"] == "fetch"
        assert s["total_runs"] == 6
        assert s["success_count"] == 5
        assert s["failure_count"] == 1
        assert s["min_ms"] == 50.0
        assert s["max_ms"] == 500.0
        assert s["p50_ms"] > 0
        assert s["p95_ms"] > 0

    @pytest.mark.asyncio
    async def test_get_node_stats_empty(self, db: Database) -> None:
        """Empty pipeline returns empty stats."""
        stats = await db.get_node_stats("nonexistent")
        assert stats == []

    @pytest.mark.asyncio
    async def test_save_metric_with_error(self, db: Database) -> None:
        """Metric with error message is saved correctly."""
        await db.save_node_metric(
            pipeline_id="pipe1",
            execution_id="exec_err",
            node_id="failing_node",
            wall_time_ms=50.0,
            outcome="failed",
            retry_count=3,
            error_message="Connection refused",
        )
        metrics = await db.get_node_metrics("failing_node")
        assert len(metrics) == 1
        assert metrics[0]["error_message"] == "Connection refused"
        assert metrics[0]["retry_count"] == 3

    @pytest.mark.asyncio
    async def test_get_execution_history(self, db: Database) -> None:
        """Execution history includes per-node metrics."""
        await db.save_pipeline("pipe1", "Test Pipeline")
        await db.save_execution(
            "exec1", "pipe1", status="success", started_at="2026-01-01T00:00:00"
        )
        await db.save_node_metric("pipe1", "exec1", "fetch", 100.0, "success")
        await db.save_node_metric("pipe1", "exec1", "transform", 200.0, "success")

        history = await db.get_execution_history("pipe1")
        assert len(history) == 1
        assert history[0]["id"] == "exec1"
        assert len(history[0]["node_metrics"]) == 2

    @pytest.mark.asyncio
    async def test_get_execution_history_empty(self, db: Database) -> None:
        """Empty pipeline returns empty history."""
        history = await db.get_execution_history("nonexistent")
        assert history == []

    @pytest.mark.asyncio
    async def test_get_execution_history_limit(self, db: Database) -> None:
        """Limit parameter restricts history results."""
        await db.save_pipeline("pipe1", "Test")
        for i in range(5):
            await db.save_execution(
                f"exec{i}", "pipe1", status="success", started_at=f"2026-01-0{i + 1}T00:00:00"
            )
        history = await db.get_execution_history("pipe1", limit=2)
        assert len(history) == 2


# ===========================================================================
# AsyncExecutor Metrics Integration Tests
# ===========================================================================


@node
def _metrics_add(x: int) -> int:
    """Simple node for metrics testing."""
    return x + 1


@node
def _metrics_fail(x: int) -> int:
    """Node that always fails."""
    raise ValueError("test failure")


class TestExecutorMetrics:
    """Tests for AsyncExecutor metrics_db instrumentation."""

    def _make_pipeline(self, *nodes: Any, name: str = "test_pipe") -> Pipeline:
        """Build a pipeline from one or more nodes."""
        if len(nodes) == 1:
            p = Pipeline(name=name)
            p.add_node(nodes[0])
            return p
        pipeline = nodes[0]
        for n in nodes[1:]:
            pipeline = pipeline >> n
        pipeline.name = name
        return pipeline

    @pytest.mark.asyncio
    async def test_metrics_recorded_on_success(self, db: Database) -> None:
        """Successful execution records metrics to DB."""
        pipeline = self._make_pipeline(_metrics_add, name="test_pipe")

        executor = AsyncExecutor(pipeline, metrics_db=db)
        result = await executor.execute(x=1)
        assert result == 2

        metrics = await db.get_node_metrics("_metrics_add")
        assert len(metrics) == 1
        assert metrics[0]["outcome"] == "success"
        assert metrics[0]["wall_time_ms"] > 0
        assert metrics[0]["pipeline_id"] == "test_pipe"

    @pytest.mark.asyncio
    async def test_metrics_recorded_on_failure(self, db: Database) -> None:
        """Failed execution records metrics to DB."""
        pipeline = self._make_pipeline(_metrics_fail, name="test_pipe_fail")

        executor = AsyncExecutor(pipeline, metrics_db=db)
        with pytest.raises(Exception, match="test failure"):
            await executor.execute(x=1)

        metrics = await db.get_node_metrics("_metrics_fail")
        assert len(metrics) == 1
        assert metrics[0]["outcome"] == "failed"
        assert metrics[0]["error_message"] is not None

    @pytest.mark.asyncio
    async def test_metrics_not_recorded_without_db(self, db: Database) -> None:
        """No metrics recorded when metrics_db is None."""
        pipeline = self._make_pipeline(_metrics_add, name="test_no_db")

        executor = AsyncExecutor(pipeline, metrics_db=None)
        result = await executor.execute(x=1)
        assert result == 2

        # No metrics should exist.
        metrics = await db.get_node_metrics("_metrics_add")
        assert len(metrics) == 0

    @pytest.mark.asyncio
    async def test_metrics_multi_node_pipeline(self, db: Database) -> None:
        """Multi-node pipeline records metrics for each node."""

        @node
        def step_a(x: int) -> int:
            return x + 1

        @node
        def step_b(x: int) -> int:
            return x * 2

        pipeline = step_a >> step_b
        pipeline.name = "multi_pipe"

        executor = AsyncExecutor(pipeline, metrics_db=db)
        result = await executor.execute(x=5)
        assert result == 12

        metrics_a = await db.get_node_metrics("step_a")
        metrics_b = await db.get_node_metrics("step_b")
        assert len(metrics_a) == 1
        assert len(metrics_b) == 1
        assert metrics_a[0]["outcome"] == "success"
        assert metrics_b[0]["outcome"] == "success"


# ===========================================================================
# API Endpoint Tests
# ===========================================================================


class TestMetricsAPI:
    """Tests for metrics and history REST API endpoints."""

    @pytest.mark.asyncio
    async def test_get_metrics_empty(self, client: Any) -> None:
        """Empty pipeline returns empty nodes list."""
        resp = await client.get("/api/metrics/nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pipeline_id"] == "nonexistent"
        assert data["nodes"] == []

    @pytest.mark.asyncio
    async def test_get_metrics_with_data(self, db: Database, client: Any) -> None:
        """Pipeline with metrics returns node stats."""
        for i in range(3):
            await db.save_node_metric("pipe1", f"e{i}", "fetch", float(i * 100 + 50), "success")
        await db.save_node_metric("pipe1", "e_fail", "fetch", 10.0, "failed")

        resp = await client.get("/api/metrics/pipe1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 1
        s = data["nodes"][0]
        assert s["node_id"] == "fetch"
        assert s["total_runs"] == 4
        assert s["success_count"] == 3
        assert s["failure_count"] == 1

    @pytest.mark.asyncio
    async def test_get_history_empty(self, client: Any) -> None:
        """Empty pipeline returns empty executions."""
        resp = await client.get("/api/history/nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["executions"] == []

    @pytest.mark.asyncio
    async def test_get_history_with_data(self, db: Database, client: Any) -> None:
        """Execution history returns node metrics."""
        await db.save_pipeline("pipe1", "Test Pipeline")
        await db.save_execution(
            "exec1", "pipe1", status="success", started_at="2026-01-01T00:00:00"
        )
        await db.save_node_metric("pipe1", "exec1", "fetch", 100.0, "success")

        resp = await client.get("/api/history/pipe1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["executions"]) == 1
        assert data["executions"][0]["id"] == "exec1"
        assert len(data["executions"][0]["node_metrics"]) == 1

    @pytest.mark.asyncio
    async def test_get_history_with_limit(self, db: Database, client: Any) -> None:
        """Limit parameter works in history endpoint."""
        await db.save_pipeline("pipe1", "Test")
        for i in range(5):
            await db.save_execution(
                f"exec{i}", "pipe1", status="success", started_at=f"2026-01-0{i + 1}T00:00:00"
            )

        resp = await client.get("/api/history/pipe1?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["executions"]) == 2
