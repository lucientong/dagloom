"""Tests for pipeline version management.

Covers:
- Database: pipeline_versions CRUD (save, get, list, delete)
- API: GET /api/pipelines/{id}/versions, GET /api/versions/{hash},
       GET /api/versions/{hash_a}/diff/{hash_b}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from dagloom.server.api import router as api_router
from dagloom.server.api import set_state
from dagloom.store.db import Database

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:  # type: ignore[misc]
    """Create a temporary database."""
    _db = Database(tmp_path / "test_versions.db")
    await _db.connect()
    yield _db  # type: ignore[misc]
    await _db.close()


@pytest_asyncio.fixture
async def client(db: Database) -> Any:  # type: ignore[misc]
    """Create a test HTTP client."""
    set_state("db", db)
    app = FastAPI()
    app.include_router(api_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ===========================================================================
# Database Pipeline Version Tests
# ===========================================================================


class TestPipelineVersionsDB:
    """Tests for pipeline_versions CRUD in Database."""

    @pytest.mark.asyncio
    async def test_save_and_get_version(self, db: Database) -> None:
        """Save a version and retrieve it by hash."""
        await db.save_pipeline("pipe1", "Test Pipeline")
        await db.save_pipeline_version(
            version_hash="abc123",
            pipeline_id="pipe1",
            code_snapshot="pipeline = a >> b",
            node_names=["a", "b"],
            edges=[("a", "b")],
            description="Initial version",
        )
        ver = await db.get_pipeline_version("abc123")
        assert ver is not None
        assert ver["version_hash"] == "abc123"
        assert ver["pipeline_id"] == "pipe1"
        assert ver["code_snapshot"] == "pipeline = a >> b"
        assert ver["description"] == "Initial version"

    @pytest.mark.asyncio
    async def test_save_version_idempotent(self, db: Database) -> None:
        """Saving same hash twice is idempotent (INSERT OR IGNORE)."""
        await db.save_pipeline("pipe1", "Test")
        await db.save_pipeline_version(
            version_hash="hash1",
            pipeline_id="pipe1",
            code_snapshot="v1",
        )
        await db.save_pipeline_version(
            version_hash="hash1",
            pipeline_id="pipe1",
            code_snapshot="v2-should-be-ignored",
        )
        ver = await db.get_pipeline_version("hash1")
        assert ver is not None
        assert ver["code_snapshot"] == "v1"

    @pytest.mark.asyncio
    async def test_get_version_not_found(self, db: Database) -> None:
        """Getting nonexistent version returns None."""
        ver = await db.get_pipeline_version("nonexistent")
        assert ver is None

    @pytest.mark.asyncio
    async def test_list_pipeline_versions(self, db: Database) -> None:
        """List versions returns newest first."""
        await db.save_pipeline("pipe1", "Test")
        for i in range(3):
            await db.save_pipeline_version(
                version_hash=f"hash{i}",
                pipeline_id="pipe1",
                code_snapshot=f"code_v{i}",
            )
        versions = await db.list_pipeline_versions("pipe1")
        assert len(versions) == 3
        # Newest first.
        assert versions[0]["version_hash"] == "hash2"

    @pytest.mark.asyncio
    async def test_list_versions_limit(self, db: Database) -> None:
        """Limit parameter restricts results."""
        await db.save_pipeline("pipe1", "Test")
        for i in range(5):
            await db.save_pipeline_version(
                version_hash=f"hash{i}",
                pipeline_id="pipe1",
                code_snapshot=f"code_v{i}",
            )
        versions = await db.list_pipeline_versions("pipe1", limit=2)
        assert len(versions) == 2

    @pytest.mark.asyncio
    async def test_list_versions_empty(self, db: Database) -> None:
        """Empty pipeline returns empty list."""
        versions = await db.list_pipeline_versions("nonexistent")
        assert versions == []

    @pytest.mark.asyncio
    async def test_delete_version(self, db: Database) -> None:
        """Delete removes a version."""
        await db.save_pipeline("pipe1", "Test")
        await db.save_pipeline_version(
            version_hash="to_delete",
            pipeline_id="pipe1",
            code_snapshot="old code",
        )
        await db.delete_pipeline_version("to_delete")
        ver = await db.get_pipeline_version("to_delete")
        assert ver is None

    @pytest.mark.asyncio
    async def test_versions_scoped_to_pipeline(self, db: Database) -> None:
        """Versions are scoped to their pipeline."""
        await db.save_pipeline("pipe1", "Pipeline 1")
        await db.save_pipeline("pipe2", "Pipeline 2")
        await db.save_pipeline_version("h1", "pipe1", "code1")
        await db.save_pipeline_version("h2", "pipe2", "code2")

        v1 = await db.list_pipeline_versions("pipe1")
        v2 = await db.list_pipeline_versions("pipe2")
        assert len(v1) == 1
        assert len(v2) == 1
        assert v1[0]["version_hash"] == "h1"
        assert v2[0]["version_hash"] == "h2"


# ===========================================================================
# API Endpoint Tests
# ===========================================================================


class TestVersionAPI:
    """Tests for pipeline version REST API endpoints."""

    @pytest.mark.asyncio
    async def test_list_versions_empty(self, client: Any) -> None:
        """Empty pipeline returns empty versions list."""
        resp = await client.get("/api/pipelines/nonexistent/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["versions"] == []

    @pytest.mark.asyncio
    async def test_list_versions_with_data(self, db: Database, client: Any) -> None:
        """Pipeline with versions returns them."""
        await db.save_pipeline("pipe1", "Test")
        await db.save_pipeline_version("h1", "pipe1", "code_v1", ["a"], [])
        await db.save_pipeline_version("h2", "pipe1", "code_v2", ["a", "b"], [("a", "b")])

        resp = await client.get("/api/pipelines/pipe1/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["versions"]) == 2

    @pytest.mark.asyncio
    async def test_get_version(self, db: Database, client: Any) -> None:
        """Get a specific version by hash."""
        await db.save_pipeline("pipe1", "Test")
        await db.save_pipeline_version("h1", "pipe1", "code_v1")

        resp = await client.get("/api/versions/h1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version_hash"] == "h1"
        assert data["code_snapshot"] == "code_v1"

    @pytest.mark.asyncio
    async def test_get_version_not_found(self, client: Any) -> None:
        """Nonexistent version returns 404."""
        resp = await client.get("/api/versions/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_diff_versions(self, db: Database, client: Any) -> None:
        """Diff two versions shows added/removed nodes and code diff."""
        await db.save_pipeline("pipe1", "Test")
        await db.save_pipeline_version(
            "h1",
            "pipe1",
            "pipeline = a >> b\n",
            ["a", "b"],
            [("a", "b")],
        )
        await db.save_pipeline_version(
            "h2",
            "pipe1",
            "pipeline = a >> b >> c\n",
            ["a", "b", "c"],
            [("a", "b"), ("b", "c")],
        )

        resp = await client.get("/api/versions/h1/diff/h2")
        assert resp.status_code == 200
        data = resp.json()

        assert data["hash_a"] == "h1"
        assert data["hash_b"] == "h2"
        assert "c" in data["nodes"]["added"]
        assert data["nodes"]["removed"] == []
        assert "a" in data["nodes"]["unchanged"]
        assert "b" in data["nodes"]["unchanged"]
        assert len(data["edges"]["added"]) == 1
        assert data["code_diff"] != ""

    @pytest.mark.asyncio
    async def test_diff_versions_not_found_a(self, db: Database, client: Any) -> None:
        """Diff with missing version A returns 404."""
        await db.save_pipeline("pipe1", "Test")
        await db.save_pipeline_version("h2", "pipe1", "code")

        resp = await client.get("/api/versions/missing/diff/h2")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_diff_versions_not_found_b(self, db: Database, client: Any) -> None:
        """Diff with missing version B returns 404."""
        await db.save_pipeline("pipe1", "Test")
        await db.save_pipeline_version("h1", "pipe1", "code")

        resp = await client.get("/api/versions/h1/diff/missing")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_diff_identical_versions(self, db: Database, client: Any) -> None:
        """Diff identical versions returns empty diff."""
        await db.save_pipeline("pipe1", "Test")
        await db.save_pipeline_version("h1", "pipe1", "same code\n", ["a"], [("a", "b")])
        await db.save_pipeline_version("h2", "pipe1", "same code\n", ["a"], [("a", "b")])

        resp = await client.get("/api/versions/h1/diff/h2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"]["added"] == []
        assert data["nodes"]["removed"] == []
        assert data["edges"]["added"] == []
        assert data["edges"]["removed"] == []
        assert data["code_diff"] == ""

    @pytest.mark.asyncio
    async def test_list_versions_with_limit(self, db: Database, client: Any) -> None:
        """Limit query param works."""
        await db.save_pipeline("pipe1", "Test")
        for i in range(5):
            await db.save_pipeline_version(f"h{i}", "pipe1", f"v{i}")

        resp = await client.get("/api/pipelines/pipe1/versions?limit=2")
        assert resp.status_code == 200
        assert len(resp.json()["versions"]) == 2
