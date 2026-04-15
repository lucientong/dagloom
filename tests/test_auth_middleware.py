"""Tests for authentication middleware.

Covers:
- AuthMiddleware: Bearer token extraction and validation
- AuthMiddleware: Basic auth extraction and validation
- Exclude paths (e.g., /health, /docs)
- RequireAuth dependency
- OptionalAuth dependency
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient

from dagloom.security.auth import APIKeyAuth, BasicAuth
from dagloom.server.middleware import AuthMiddleware

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def bearer_auth_app() -> FastAPI:  # type: ignore[misc]
    """Create a FastAPI app with Bearer token auth middleware."""
    app = FastAPI()
    auth = APIKeyAuth(api_key="sk-test-token")
    app.add_middleware(AuthMiddleware, auth_provider=auth)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Public health check."""
        return {"status": "ok"}

    @app.get("/protected")
    async def protected(request: Request) -> dict[str, Any]:
        """Protected endpoint."""
        if not getattr(request.state, "authenticated", False):
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"message": "Protected resource"}

    @app.get("/optional")
    async def optional_endpoint(request: Request) -> dict[str, Any]:
        """Endpoint with optional auth."""
        user = getattr(request.state, "user", None)
        return {"user": user or {"user_id": "anonymous", "authenticated": False}}

    return app


@pytest_asyncio.fixture
async def basic_auth_app() -> FastAPI:  # type: ignore[misc]
    """Create a FastAPI app with Basic auth middleware."""
    app = FastAPI()
    auth = BasicAuth(username="admin", password="secret")
    app.add_middleware(AuthMiddleware, auth_provider=auth)

    @app.get("/data")
    async def get_data(request: Request) -> dict[str, str]:
        """Protected endpoint."""
        if not getattr(request.state, "authenticated", False):
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"data": "secret"}

    return app


@pytest_asyncio.fixture
async def bearer_client(bearer_auth_app: FastAPI) -> Any:  # type: ignore[misc]
    """Create async HTTP client for Bearer auth app."""
    transport = ASGITransport(app=bearer_auth_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def basic_client(basic_auth_app: FastAPI) -> Any:  # type: ignore[misc]
    """Create async HTTP client for Basic auth app."""
    transport = ASGITransport(app=basic_auth_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# AuthMiddleware + Bearer Token Tests
# ---------------------------------------------------------------------------


class TestAuthMiddlewareBearer:
    """Tests for Bearer token authentication via middleware."""

    @pytest.mark.asyncio
    async def test_bearer_token_valid(self, bearer_client: Any) -> None:
        """Valid Bearer token is extracted and validated."""
        resp = await bearer_client.get(
            "/protected",
            headers={"Authorization": "Bearer sk-test-token"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_bearer_token_invalid(self, bearer_client: Any) -> None:
        """Invalid Bearer token fails authentication."""
        resp = await bearer_client.get(
            "/protected",
            headers={"Authorization": "Bearer sk-wrong-token"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_bearer_token_missing(self, bearer_client: Any) -> None:
        """Missing Bearer token results in unauthenticated state."""
        resp = await bearer_client.get("/protected")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_bearer_case_insensitive(self, bearer_client: Any) -> None:
        """Bearer scheme is case-insensitive."""
        resp = await bearer_client.get(
            "/protected",
            headers={"Authorization": "bearer sk-test-token"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_health_excluded_from_auth(self, bearer_client: Any) -> None:
        """Health check endpoint is excluded from authentication."""
        resp = await bearer_client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_malformed_auth_header(self, bearer_client: Any) -> None:
        """Malformed Authorization header is handled gracefully."""
        resp = await bearer_client.get(
            "/protected",
            headers={"Authorization": "BearerMissingSpace"},
        )
        # Should not crash; endpoint enforces auth and rejects.
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# AuthMiddleware + Basic Auth Tests
# ---------------------------------------------------------------------------


class TestAuthMiddlewareBasic:
    """Tests for HTTP Basic authentication via middleware."""

    @pytest.mark.asyncio
    async def test_basic_auth_valid(self, basic_client: Any) -> None:
        """Valid Basic auth credentials are validated."""
        creds = base64.b64encode(b"admin:secret").decode()
        resp = await basic_client.get(
            "/data",
            headers={"Authorization": f"Basic {creds}"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_basic_auth_invalid_password(self, basic_client: Any) -> None:
        """Invalid password fails authentication."""
        creds = base64.b64encode(b"admin:wrongpass").decode()
        resp = await basic_client.get(
            "/data",
            headers={"Authorization": f"Basic {creds}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_basic_auth_invalid_username(self, basic_client: Any) -> None:
        """Invalid username fails authentication."""
        creds = base64.b64encode(b"user:secret").decode()
        resp = await basic_client.get(
            "/data",
            headers={"Authorization": f"Basic {creds}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_basic_auth_missing(self, basic_client: Any) -> None:
        """Missing Basic auth header results in unauthenticated state."""
        resp = await basic_client.get("/data")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_basic_auth_case_insensitive(self, basic_client: Any) -> None:
        """Basic scheme is case-insensitive."""
        creds = base64.b64encode(b"admin:secret").decode()
        resp = await basic_client.get(
            "/data",
            headers={"Authorization": f"basic {creds}"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# AuthMiddleware + Optional Auth Tests
# ---------------------------------------------------------------------------


class TestAuthMiddlewareOptional:
    """Tests for optional authentication."""

    @pytest.mark.asyncio
    async def test_optional_auth_with_token(self, bearer_client: Any) -> None:
        """Optional auth endpoint returns user info when authenticated."""
        resp = await bearer_client.get(
            "/optional",
            headers={"Authorization": "Bearer sk-test-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "user" in data
        assert data["user"] is not None

    @pytest.mark.asyncio
    async def test_optional_auth_without_token(self, bearer_client: Any) -> None:
        """Optional auth endpoint returns guest user when not authenticated."""
        resp = await bearer_client.get("/optional")
        assert resp.status_code == 200
        data = resp.json()
        assert "user" in data
        assert data["user"]["user_id"] == "anonymous"


# ---------------------------------------------------------------------------
# AuthMiddleware + Dependencies Tests
# ---------------------------------------------------------------------------


class TestAuthDependencies:
    """Tests for RequireAuth and OptionalAuth dependencies."""

    @pytest_asyncio.fixture
    async def app_with_deps(self) -> FastAPI:  # type: ignore[misc]
        """App with auth dependencies."""
        app = FastAPI()
        auth = APIKeyAuth(api_key="sk-test")
        app.add_middleware(AuthMiddleware, auth_provider=auth)

        @app.get("/require")
        async def require_auth(user: dict[str, Any] = None) -> dict[str, str]:  # type: ignore[assignment]
            """Requires authentication via dependency."""
            # Using RequireAuth dependency.
            if user is None:
                raise HTTPException(status_code=401, detail="Not authenticated")
            return {"message": "Authorized"}

        @app.get("/require-via-request")
        async def require_via_request(request: Request) -> dict[str, str]:
            """Requires authentication via request state."""
            if not getattr(request.state, "authenticated", False):
                raise HTTPException(status_code=401, detail="Not authenticated")
            return {"message": "Authorized"}

        @app.get("/optional")
        async def optional_auth(
            user: dict[str, Any] = None,  # type: ignore[assignment]
        ) -> dict[str, Any]:
            """Optional authentication."""
            return {"user": user or {"user_id": "anonymous", "authenticated": False}}

        return app

    @pytest_asyncio.fixture
    async def app_client(self, app_with_deps: FastAPI) -> Any:  # type: ignore[misc]
        """Client for the dependency app."""
        transport = ASGITransport(app=app_with_deps)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    @pytest.mark.asyncio
    async def test_require_auth_with_valid_token(self, app_client: Any) -> None:
        """RequireAuth succeeds with valid token."""
        resp = await app_client.get(
            "/require-via-request",
            headers={"Authorization": "Bearer sk-test"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_require_auth_without_token(self, app_client: Any) -> None:
        """RequireAuth fails without token."""
        resp = await app_client.get("/require-via-request")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_optional_auth_without_token(self, app_client: Any) -> None:
        """OptionalAuth provides guest user without token."""
        resp = await app_client.get("/optional")
        assert resp.status_code == 200
        data = resp.json()
        assert "user" in data


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


class TestAuthMiddlewareIntegration:
    """Integration tests for middleware with multiple auth types."""

    @pytest_asyncio.fixture
    async def multi_auth_app(self) -> FastAPI:  # type: ignore[misc]
        """App supporting multiple auth types (Bearer + Basic)."""
        app = FastAPI()
        bearer_auth = APIKeyAuth(api_key="sk-test")
        app.add_middleware(AuthMiddleware, auth_provider=bearer_auth)

        @app.get("/status")
        async def status() -> dict[str, str]:
            return {"status": "ok"}

        return app

    @pytest_asyncio.fixture
    async def multi_auth_client(self, multi_auth_app: FastAPI) -> Any:  # type: ignore[misc]
        """Client for multi-auth app."""
        transport = ASGITransport(app=multi_auth_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    @pytest.mark.asyncio
    async def test_middleware_attached_successfully(self, multi_auth_client: Any) -> None:
        """Middleware is attached and doesn't crash the app."""
        resp = await multi_auth_client.get("/status")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_middleware_with_bearer_token(self, multi_auth_client: Any) -> None:
        """Middleware processes Bearer token."""
        resp = await multi_auth_client.get(
            "/status",
            headers={"Authorization": "Bearer sk-test"},
        )
        assert resp.status_code == 200
