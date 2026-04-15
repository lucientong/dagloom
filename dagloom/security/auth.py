"""Authentication providers for Dagloom API.

Supports multiple authentication strategies:
- **API Key**: Bearer token authentication (stored in SecretStore)
- **Basic Auth**: HTTP Basic authentication (username:password)

Example::

    # API Key auth
    api_key_auth = APIKeyAuth(secret_store=store, api_key="sk-abc123")
    user = await api_key_auth.authenticate(request)

    # Basic auth
    basic_auth = BasicAuth(secret_store=store, username="admin", password="pass")
    user = await basic_auth.authenticate(request)
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

from dagloom.security.secrets import SecretStore

logger = logging.getLogger(__name__)


class AuthProvider(ABC):
    """Abstract base class for authentication providers."""

    @abstractmethod
    async def authenticate(self, token_or_creds: str) -> dict[str, Any] | None:
        """Authenticate a request using the provided credentials.

        Args:
            token_or_creds: Authentication token or credentials (format depends on provider).

        Returns:
            A dict with user info (e.g., ``{"user_id": "...", "username": "..."}``),
            or ``None`` if authentication fails.
        """


class APIKeyAuth(AuthProvider):
    """API Key authentication using Bearer tokens.

    API keys can be:
    - Provided directly during initialization
    - Stored in the SecretStore under a named key
    - Read from environment variables (``DAGLOOM_API_KEY``)

    Example::

        # Option 1: Direct key
        auth = APIKeyAuth(api_key="sk-abc123")
        user = await auth.authenticate("sk-abc123")

        # Option 2: From SecretStore
        auth = APIKeyAuth(secret_store=store, secret_key="api_key")
        user = await auth.authenticate("sk-abc123")

        # Option 3: From environment (DAGLOOM_API_KEY)
        auth = APIKeyAuth()
        user = await auth.authenticate("sk-abc123")
    """

    def __init__(
        self,
        api_key: str | None = None,
        secret_store: SecretStore | None = None,
        secret_key: str = "api_key",
    ) -> None:
        """Initialize API Key authenticator.

        Args:
            api_key: Direct API key value (takes precedence).
            secret_store: SecretStore instance for resolving secrets.
            secret_key: Key name in SecretStore (e.g., "api_key").
                Only used if ``secret_store`` is provided and ``api_key`` is None.
        """
        self._api_key = api_key
        self._secret_store = secret_store
        self._secret_key = secret_key

    async def _get_api_key(self) -> str | None:
        """Resolve the configured API key from multiple sources."""
        # 1. Direct key (highest priority).
        if self._api_key is not None:
            return self._api_key

        # 2. From SecretStore.
        if self._secret_store is not None:
            key = await self._secret_store.get(self._secret_key)
            if key is not None:
                return key

        # 3. From environment variable.
        env_key = os.environ.get("DAGLOOM_API_KEY")
        if env_key is not None:
            return env_key

        return None

    async def authenticate(self, token: str) -> dict[str, Any] | None:
        """Authenticate a Bearer token.

        Args:
            token: The Bearer token to verify.

        Returns:
            A dict with ``{"user_id": "<hash>\", "api_key_valid": true}`` on success,
            or ``None`` if the token is invalid.
        """
        configured_key = await self._get_api_key()
        if configured_key is None:
            logger.warning("APIKeyAuth: no API key configured")
            return None

        if token == configured_key:
            logger.debug("APIKeyAuth: token verified successfully")
            return {
                "user_id": hashlib.sha256(token.encode()).hexdigest()[:12],
                "api_key_valid": True,
            }

        logger.warning("APIKeyAuth: invalid token provided")
        return None


class BasicAuth(AuthProvider):
    """HTTP Basic authentication (username:password).

    Credentials can be:
    - Provided directly during initialization
    - Stored in the SecretStore
    - Read from environment variables (``DAGLOOM_AUTH_USERNAME``, ``DAGLOOM_AUTH_PASSWORD``)

    Passwords are hashed using PBKDF2 (configurable iterations).

    Example::

        # Option 1: Direct credentials
        auth = BasicAuth(username="admin", password="secret")
        user = await auth.authenticate(base64.b64encode(b"admin:secret"))

        # Option 2: From SecretStore
        auth = BasicAuth(secret_store=store)
        user = await auth.authenticate(encoded_creds)
    """

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        secret_store: SecretStore | None = None,
        username_key: str = "auth_username",
        password_key: str = "auth_password",
        hash_iterations: int = 100000,
    ) -> None:
        """Initialize Basic Auth provider.

        Args:
            username: Direct username (takes precedence).
            password: Direct password (takes precedence).
            secret_store: SecretStore instance for resolving credentials.
            username_key: Key in SecretStore for username.
            password_key: Key in SecretStore for password.
            hash_iterations: PBKDF2 iterations for password hashing.
        """
        self._username = username
        self._password = password
        self._secret_store = secret_store
        self._username_key = username_key
        self._password_key = password_key
        self._hash_iterations = hash_iterations

    async def _get_credentials(self) -> tuple[str | None, str | None]:
        """Resolve configured credentials from multiple sources."""
        username = self._username
        password = self._password

        # 1. Direct credentials (highest priority).
        if username is not None and password is not None:
            return username, password

        # 2. From SecretStore.
        if self._secret_store is not None:
            if username is None:
                username = await self._secret_store.get(self._username_key)
            if password is None:
                password = await self._secret_store.get(self._password_key)
            if username is not None and password is not None:
                return username, password

        # 3. From environment variables.
        env_user = os.environ.get("DAGLOOM_AUTH_USERNAME")
        env_pass = os.environ.get("DAGLOOM_AUTH_PASSWORD")
        if env_user is not None and env_pass is not None:
            return env_user, env_pass

        return None, None

    def _hash_password(self, password: str, salt: bytes | None = None) -> str:
        """Hash a password using PBKDF2.

        Args:
            password: The plaintext password.
            salt: Optional salt. If None, a random salt is used.

        Returns:
            A hex string of format: ``<salt>:<hash>``.
        """
        salt = os.urandom(16) if salt is None else salt

        key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt,
            self._hash_iterations,
        )
        return f"{salt.hex()}:{key.hex()}"

    def _verify_password(self, provided: str, stored_hash: str) -> bool:
        """Verify a plaintext password against a stored hash.

        Args:
            provided: The plaintext password to verify.
            stored_hash: The stored hash (format: ``<salt>:<hash>``).

        Returns:
            ``True`` if the password matches.
        """
        try:
            salt_hex, _ = stored_hash.split(":", 1)
            salt = bytes.fromhex(salt_hex)
            rehashed = self._hash_password(provided, salt)
            return rehashed == stored_hash
        except (ValueError, AttributeError):
            return False

    async def authenticate(self, credentials: str) -> dict[str, Any] | None:
        """Authenticate HTTP Basic credentials.

        Args:
            credentials: Base64-encoded ``username:password`` string.

        Returns:
            A dict with ``{"user_id": "<username>", "username": "<username>"}`` on success,
            or ``None`` if authentication fails.
        """
        configured_user, configured_pass = await self._get_credentials()
        if configured_user is None or configured_pass is None:
            logger.warning("BasicAuth: no credentials configured")
            return None

        # Decode base64 credentials.
        try:
            decoded = base64.b64decode(credentials).decode("utf-8")
            provided_user, provided_pass = decoded.split(":", 1)
        except Exception as exc:
            logger.warning("BasicAuth: failed to decode credentials: %s", exc)
            return None

        # Verify username and password.
        if provided_user != configured_user:
            logger.warning("BasicAuth: username mismatch")
            return None

        # Check if the password is a hash or plaintext.
        # If it contains ":", assume it's a stored hash; otherwise, do direct comparison.
        if ":" in configured_pass:
            # Stored as hash.
            if not self._verify_password(provided_pass, configured_pass):
                logger.warning("BasicAuth: password verification failed")
                return None
        else:
            # Plaintext comparison (for direct credentials).
            if provided_pass != configured_pass:
                logger.warning("BasicAuth: password mismatch")
                return None

        logger.debug("BasicAuth: authentication successful for user %r", provided_user)
        return {
            "user_id": provided_user,
            "username": provided_user,
        }


class NoAuth(AuthProvider):
    """Null authentication provider (always succeeds).

    Useful for development or when authentication is disabled.
    """

    async def authenticate(self, token_or_creds: str) -> dict[str, Any] | None:
        """Always authenticate successfully (no-op).

        Returns:
            A dict with ``{"user_id": "anonymous", "authenticated": false}``.
        """
        return {
            "user_id": "anonymous",
            "authenticated": False,
        }
