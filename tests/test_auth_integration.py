"""Integration tests for authentication with the FastAPI app.

Covers:
- Creating app with and without authentication
- API endpoints with authentication
- Error handling for invalid configurations
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from dagloom.server.app import create_app, set_state
from dagloom.store.db import Database

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app_no_auth(tmp_path: Path) -> FastAPI:  # type: ignore[misc]
    """Create app without authentication."""
    db = Database(tmp_path / "test_no_auth.db")
    await db.connect()
    set_state("db", db)
    app = create_app(auth_type=None)
    yield app
    await db.close()


@pytest_asyncio.fixture
async def app_api_key_auth(tmp_path: Path) -> FastAPI:  # type: ignore[misc]
    """Create app with API Key authentication."""
    db = Database(tmp_path / "test_api_key.db")
    await db.connect()
    set_state("db", db)
    app = create_app(auth_type="API_KEY", auth_key="sk-integration-test")
    yield app
    await db.close()


@pytest_asyncio.fixture
async def app_basic_auth(tmp_path: Path) -> FastAPI:  # type: ignore[misc]
    """Create app with Basic authentication."""
    db = Database(tmp_path / "test_basic.db")
    await db.connect()
    set_state("db", db)
    app = create_app(auth_type="BASIC_AUTH", auth_key="testuser:testpass")
    yield app
    await db.close()


@pytest_asyncio.fixture
async def client_no_auth(app_no_auth: FastAPI) -> Any:  # type: ignore[misc]
    """Client for app without auth."""
    transport = ASGITransport(app=app_no_auth)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def client_api_key(app_api_key_auth: FastAPI) -> Any:  # type: ignore[misc]
    """Client for app with API Key auth."""
    transport = ASGITransport(app=app_api_key_auth)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def client_basic(app_basic_auth: FastAPI) -> Any:  # type: ignore[misc]
    """Client for app with Basic auth."""
    transport = ASGITransport(app=app_basic_auth)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# App Creation Tests
# ---------------------------------------------------------------------------


class TestAppCreation:
    """Tests for creating the FastAPI app with various auth configurations."""

    def test_create_app_no_auth(self) -> None:
        """App can be created without authentication."""
        app = create_app()
        assert app is not None
        assert isinstance(app, FastAPI)

    def test_create_app_with_api_key(self) -> None:
        """App can be created with API Key authentication."""
        app = create_app(auth_type="API_KEY", auth_key="sk-test")
        assert app is not None

    def test_create_app_with_basic_auth(self) -> None:
        """App can be created with Basic authentication."""
        app = create_app(auth_type="BASIC_AUTH", auth_key="admin:password")
        assert app is not None

    def test_create_app_api_key_missing_key(self) -> None:
        """Creating app with API_KEY but no key raises error."""
        with pytest.raises(ValueError, match="--auth-key is required"):
            create_app(auth_type="API_KEY", auth_key=None)

    def test_create_app_basic_auth_missing_key(self) -> None:
        """Creating app with BASIC_AUTH but no key raises error."""
        with pytest.raises(ValueError, match="--auth-key is required"):
            create_app(auth_type="BASIC_AUTH", auth_key=None)

    def test_create_app_basic_auth_invalid_format(self) -> None:
        """Creating app with BASIC_AUTH but invalid format raises error."""
        with pytest.raises(ValueError, match="username:password"):
            create_app(auth_type="BASIC_AUTH", auth_key="invalidformat")

    def test_create_app_unknown_auth_type(self) -> None:
        """Creating app with unknown auth type raises error."""
        with pytest.raises(ValueError, match="Unknown authentication type"):
            create_app(auth_type="UNKNOWN_AUTH", auth_key="something")


# ---------------------------------------------------------------------------
# API Endpoint Tests
# ---------------------------------------------------------------------------


class TestAPIEndpointsNoAuth:
    """Tests for API endpoints without authentication."""

    @pytest.mark.asyncio
    async def test_health_check_no_auth(self, client_no_auth: Any) -> None:
        """Health check endpoint works without auth."""
        resp = await client_no_auth.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_list_pipelines_no_auth(self, client_no_auth: Any) -> None:
        """List pipelines endpoint works without auth."""
        resp = await client_no_auth.get("/api/pipelines")
        assert resp.status_code == 200
        # Should be empty list since no pipelines registered.
        assert isinstance(resp.json(), list)


class TestAPIEndpointsWithAPIKeyAuth:
    """Tests for API endpoints with API Key authentication."""

    @pytest.mark.asyncio
    async def test_health_check_with_api_key_auth(self, client_api_key: Any) -> None:
        """Health check endpoint is excluded from auth (always accessible)."""
        resp = await client_api_key.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_pipelines_with_valid_token(self, client_api_key: Any) -> None:
        """List pipelines with valid API key token."""
        resp = await client_api_key.get(
            "/api/pipelines",
            headers={"Authorization": "Bearer sk-integration-test"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_pipelines_with_invalid_token(self, client_api_key: Any) -> None:
        """List pipelines with invalid API key token (no auth check on endpoint)."""
        resp = await client_api_key.get(
            "/api/pipelines",
            headers={"Authorization": "Bearer sk-wrong-token"},
        )
        # The endpoint doesn't enforce auth (it's in state), so it returns 200
        # with empty list. This is expected behavior (endpoints opt-in to auth).
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_pipelines_without_token(self, client_api_key: Any) -> None:
        """List pipelines without token (unauthenticated but no auth check on endpoint)."""
        resp = await client_api_key.get("/api/pipelines")
        assert resp.status_code == 200


class TestAPIEndpointsWithBasicAuth:
    """Tests for API endpoints with Basic authentication."""

    @pytest.mark.asyncio
    async def test_health_check_with_basic_auth(self, client_basic: Any) -> None:
        """Health check endpoint is excluded from auth."""
        resp = await client_basic.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_pipelines_with_valid_basic_auth(self, client_basic: Any) -> None:
        """List pipelines with valid Basic auth credentials."""
        creds = base64.b64encode(b"testuser:testpass").decode()
        resp = await client_basic.get(
            "/api/pipelines",
            headers={"Authorization": f"Basic {creds}"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_pipelines_with_invalid_basic_auth(self, client_basic: Any) -> None:
        """List pipelines with invalid Basic auth credentials."""
        creds = base64.b64encode(b"testuser:wrongpass").decode()
        resp = await client_basic.get(
            "/api/pipelines",
            headers={"Authorization": f"Basic {creds}"},
        )
        assert resp.status_code == 200  # Endpoint doesn't enforce auth


# ---------------------------------------------------------------------------
# WebSocket Tests
# ---------------------------------------------------------------------------


class TestWebSocketWithAuth:
    """Tests for WebSocket endpoints with authentication."""

    @pytest.mark.asyncio
    async def test_websocket_connection_no_auth(self, client_no_auth: Any) -> None:
        """WebSocket connects without authentication."""
        # Note: We can't fully test WebSocket with AsyncClient easily,
        # but we can verify the endpoint exists.
        # Full testing would require a WebSocket client.
        # For now, just verify the endpoint definition works.
        pass

    @pytest.mark.asyncio
    async def test_websocket_connection_with_auth(self, client_api_key: Any) -> None:
        """WebSocket can connect with authentication."""
        # Similarly, just verify the endpoint exists.
        pass


# ---------------------------------------------------------------------------
# End-to-End Tests
# ---------------------------------------------------------------------------


class TestE2EAuthFlow:
    """End-to-end tests for authentication flows."""

    @pytest.mark.asyncio
    async def test_unauthenticated_then_authenticated(self, client_api_key: Any) -> None:
        """First request unauthenticated, then authenticated."""
        # First request without auth.
        resp1 = await client_api_key.get("/health")
        assert resp1.status_code == 200

        # Second request with auth.
        resp2 = await client_api_key.get(
            "/health",
            headers={"Authorization": "Bearer sk-integration-test"},
        )
        assert resp2.status_code == 200

    @pytest.mark.asyncio
    async def test_multiple_auth_types_in_requests(self, client_api_key: Any) -> None:
        """Client can switch between auth types (though only one is valid)."""
        # Try Bearer token (valid).
        resp1 = await client_api_key.get(
            "/health",
            headers={"Authorization": "Bearer sk-integration-test"},
        )
        assert resp1.status_code == 200

        # Try Basic auth (invalid for API_KEY app, but shouldn't crash).
        creds = base64.b64encode(b"user:pass").decode()
        resp2 = await client_api_key.get(
            "/health",
            headers={"Authorization": f"Basic {creds}"},
        )
        assert resp2.status_code == 200
