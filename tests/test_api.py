"""Tests for the REST API endpoints."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from dagloom.server.app import create_app
from dagloom.store.db import Database


@pytest.fixture
async def app(tmp_path):
    """Create a test app with a temporary database."""
    from dagloom.server.api import set_state

    db = Database(tmp_path / "test.db")
    await db.connect()
    set_state("db", db)

    application = create_app()
    yield application

    await db.close()


@pytest.fixture
async def client(app):
    """Create an async HTTP test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealthCheck:
    """Test health endpoint."""

    @pytest.mark.asyncio
    async def test_health(self, client) -> None:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestPipelineEndpoints:
    """Test pipeline CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_list_empty(self, client) -> None:
        resp = await client.get("/api/pipelines")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_run_missing_pipeline(self, client) -> None:
        resp = await client.post(
            "/api/pipelines/nonexistent/run",
            json={"inputs": {}},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_status_no_execution(self, client) -> None:
        resp = await client.get("/api/pipelines/nonexistent/status")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_resume_no_failed(self, client) -> None:
        resp = await client.post("/api/pipelines/nonexistent/resume")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_dag_missing(self, client) -> None:
        resp = await client.get("/api/pipelines/nonexistent/dag")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_dag_missing(self, client) -> None:
        resp = await client.put(
            "/api/pipelines/nonexistent/dag",
            json={"nodes": [], "edges": []},
        )
        assert resp.status_code == 404


class TestPipelineWorkflow:
    """Test a complete pipeline workflow."""

    @pytest.mark.asyncio
    async def test_full_workflow(self, client, app, tmp_path) -> None:
        from dagloom.server.api import get_state

        db = get_state("db")

        # Create a test pipeline directly in the DB.
        await db.save_pipeline(
            pipeline_id="test-pipe",
            name="Test Pipeline",
            description="A test pipeline",
            node_names=["fetch", "clean", "save"],
            edges=[("fetch", "clean"), ("clean", "save")],
        )

        # List pipelines.
        resp = await client.get("/api/pipelines")
        assert resp.status_code == 200
        pipelines = resp.json()
        assert len(pipelines) == 1
        assert pipelines[0]["name"] == "Test Pipeline"

        # Run the pipeline.
        resp = await client.post(
            "/api/pipelines/test-pipe/run",
            json={"inputs": {"url": "https://example.com"}},
        )
        assert resp.status_code == 200
        run_data = resp.json()
        assert run_data["status"] == "running"
        execution_id = run_data["execution_id"]

        # Get status.
        resp = await client.get("/api/pipelines/test-pipe/status")
        assert resp.status_code == 200
        assert resp.json()["execution_id"] == execution_id

        # Get DAG.
        resp = await client.get("/api/pipelines/test-pipe/dag")
        assert resp.status_code == 200
        dag = resp.json()
        assert len(dag["nodes"]) == 3

        # Update DAG.
        resp = await client.put(
            "/api/pipelines/test-pipe/dag",
            json={
                "nodes": [{"name": "a"}, {"name": "b"}],
                "edges": [["a", "b"]],
            },
        )
        assert resp.status_code == 200
