"""Authentication middleware for Dagloom API.

Provides HTTP middleware for extracting and validating authentication credentials.
Supports:
- Bearer token (API Key) authentication
- HTTP Basic authentication

Example::

    from fastapi import FastAPI
    from dagloom.server.middleware import AuthMiddleware
    from dagloom.security.auth import APIKeyAuth

    app = FastAPI()
    auth = APIKeyAuth(api_key="sk-abc123")
    app.add_middleware(AuthMiddleware, auth_provider=auth)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from dagloom.security.auth import AuthProvider

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """HTTP middleware for authentication.

    Extracts authentication credentials from the request (Bearer token or
    Basic auth header) and validates them using the provided AuthProvider.

    The authenticated user info is attached to the request state for use
    in route handlers via ``request.state.user``.

    Public endpoints (those without authorization requirement) bypass this
    middleware — this is typically handled by route-level decorators or
    endpoint logic.

    Args:
        app: The ASGI application.
        auth_provider: An AuthProvider instance for validating credentials.
        exclude_paths: List of path prefixes to exclude from authentication
            (e.g., ``["/health", "/docs"]``).
    """

    def __init__(
        self,
        app: Any,
        auth_provider: AuthProvider,
        exclude_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.auth_provider = auth_provider
        self.exclude_paths = exclude_paths or [
            "/health",
            "/docs",
            "/openapi.json",
            "/redoc",
        ]

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Process the request and authenticate if needed.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware/endpoint handler.

        Returns:
            The response (with user info attached if authenticated).
        """
        # Check if this path should be excluded from authentication.
        for exclude_path in self.exclude_paths:
            if request.url.path.startswith(exclude_path):
                return await call_next(request)

        # Extract credentials from the request.
        credentials = self._extract_credentials(request)
        if credentials is None:
            logger.warning("No authentication credentials found in request: %s", request.url.path)
            # Allow the request to continue; specific endpoints can enforce auth.
            request.state.user = None
            request.state.authenticated = False
            return await call_next(request)

        # Validate credentials with the auth provider.
        auth_type, credential_value = credentials
        user = await self._authenticate(auth_type, credential_value)

        if user is None:
            logger.warning("Authentication failed for %s: %s", auth_type, request.url.path)
            request.state.user = None
            request.state.authenticated = False
        else:
            logger.debug("User authenticated: %s", user.get("user_id"))
            request.state.user = user
            request.state.authenticated = True

        response = await call_next(request)
        return response

    def _extract_credentials(self, request: Request) -> tuple[str, str] | None:
        """Extract authentication credentials from the request.

        Supports:
        - Bearer token in ``Authorization: Bearer <token>`` header
        - Basic auth in ``Authorization: Basic <base64>`` header

        Args:
            request: The incoming request.

        Returns:
            A tuple of ``(auth_type, credential_value)``, or ``None``.
        """
        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            return None

        parts = auth_header.split(" ", 1)
        if len(parts) != 2:
            logger.warning("Malformed Authorization header")
            return None

        auth_type, credentials = parts
        auth_type_lower = auth_type.lower()

        if auth_type_lower == "bearer":
            # API Key: Bearer token.
            return ("bearer", credentials)

        if auth_type_lower == "basic":
            # Basic auth: base64-encoded credentials.
            return ("basic", credentials)

        logger.warning("Unsupported Authorization scheme: %s", auth_type)
        return None

    async def _authenticate(self, auth_type: str, credentials: str) -> dict[str, Any] | None:
        """Authenticate credentials using the auth provider.

        Args:
            auth_type: Type of authentication ("bearer" or "basic").
            credentials: The credential value (token or base64).

        Returns:
            User info dict on success, or ``None`` if authentication fails.
        """
        try:
            # Delegate to the configured auth provider.
            user = await self.auth_provider.authenticate(credentials)
            return user
        except Exception as exc:
            logger.error("Authentication error: %s", exc)
            return None


class RequireAuth:
    """Dependency for FastAPI endpoints requiring authentication.

    Ensures that the request is authenticated; raises HTTP 401 if not.

    Example::

        from fastapi import Depends

        @app.get("/protected")
        async def protected(user = Depends(RequireAuth())):
            return {"user_id": user["user_id"]}
    """

    async def __call__(self, request: Request) -> dict[str, Any]:
        """Validate authentication state.

        Args:
            request: The incoming request (with request.state.authenticated set by middleware).

        Returns:
            The user info dict if authenticated.

        Raises:
            HTTPException: If not authenticated (status 401).
        """
        if not getattr(request.state, "authenticated", False):
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Not authenticated")

        user = getattr(request.state, "user", None)
        if user is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Not authenticated")

        return user


class OptionalAuth:
    """Dependency for FastAPI endpoints with optional authentication.

    Returns the user info if authenticated, or a guest user dict if not.

    Example::

        from fastapi import Depends

        @app.get("/public")
        async def public(user = Depends(OptionalAuth())):
            return {"user": user.get("user_id", "anonymous")}
    """

    async def __call__(self, request: Request) -> dict[str, Any]:
        """Get user info, or return guest user.

        Args:
            request: The incoming request.

        Returns:
            The user info dict if authenticated, or a guest dict if not.
        """
        user = getattr(request.state, "user", None)
        if user is not None:
            return user

        return {
            "user_id": "anonymous",
            "authenticated": False,
        }
