"""Tests for authentication providers (API Key + Basic Auth).

Covers:
- APIKeyAuth: direct key, from SecretStore, from env var
- BasicAuth: direct credentials, from SecretStore, from env var, password hashing
- NoAuth: null provider
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio

from dagloom.security.auth import APIKeyAuth, BasicAuth, NoAuth
from dagloom.security.encryption import Encryptor
from dagloom.security.secrets import SecretStore
from dagloom.store.db import Database

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:  # type: ignore[misc]
    """Create a temporary database."""
    _db = Database(tmp_path / "test.db")
    await _db.connect()
    yield _db  # type: ignore[misc]
    await _db.close()


@pytest.fixture
def encryptor() -> Encryptor:
    """Create an Encryptor with a fixed test key."""
    key = Encryptor.generate_key()
    return Encryptor(master_key=key)


@pytest_asyncio.fixture
async def store(db: Database, encryptor: Encryptor) -> SecretStore:
    """Create a SecretStore backed by temp DB."""
    return SecretStore(db=db, encryptor=encryptor, dotenv_path=None)


# ---------------------------------------------------------------------------
# APIKeyAuth Tests
# ---------------------------------------------------------------------------


class TestAPIKeyAuth:
    """Tests for API Key authentication."""

    @pytest.mark.asyncio
    async def test_api_key_direct(self) -> None:
        """Direct API key authentication succeeds."""
        auth = APIKeyAuth(api_key="sk-test-12345")
        result = await auth.authenticate("sk-test-12345")
        assert result is not None
        assert result["api_key_valid"] is True
        assert "user_id" in result

    @pytest.mark.asyncio
    async def test_api_key_direct_wrong_token(self) -> None:
        """Wrong token with direct API key fails."""
        auth = APIKeyAuth(api_key="sk-test-12345")
        result = await auth.authenticate("sk-wrong-token")
        assert result is None

    @pytest.mark.asyncio
    async def test_api_key_from_secret_store(self, store: SecretStore) -> None:
        """API key resolved from SecretStore."""
        await store.set("api_key", "sk-from-store")
        auth = APIKeyAuth(secret_store=store, secret_key="api_key")
        result = await auth.authenticate("sk-from-store")
        assert result is not None
        assert result["api_key_valid"] is True

    @pytest.mark.asyncio
    async def test_api_key_from_secret_store_wrong_token(self, store: SecretStore) -> None:
        """Wrong token with SecretStore key fails."""
        await store.set("api_key", "sk-from-store")
        auth = APIKeyAuth(secret_store=store, secret_key="api_key")
        result = await auth.authenticate("sk-wrong-token")
        assert result is None

    @pytest.mark.asyncio
    async def test_api_key_from_env(self) -> None:
        """API key resolved from environment variable."""
        with patch.dict(os.environ, {"DAGLOOM_API_KEY": "sk-from-env"}):
            auth = APIKeyAuth()
            result = await auth.authenticate("sk-from-env")
            assert result is not None
            assert result["api_key_valid"] is True

    @pytest.mark.asyncio
    async def test_api_key_precedence_direct_over_store(self, store: SecretStore) -> None:
        """Direct API key takes precedence over SecretStore."""
        await store.set("api_key", "sk-from-store")
        auth = APIKeyAuth(api_key="sk-direct", secret_store=store, secret_key="api_key")
        result = await auth.authenticate("sk-direct")
        assert result is not None
        # Wrong store key should fail.
        result = await auth.authenticate("sk-from-store")
        assert result is None

    @pytest.mark.asyncio
    async def test_api_key_no_config(self) -> None:
        """Authentication fails when no API key is configured."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("DAGLOOM_API_KEY", None)
            auth = APIKeyAuth()
            result = await auth.authenticate("sk-any-token")
            assert result is None

    @pytest.mark.asyncio
    async def test_api_key_user_id_deterministic(self) -> None:
        """API key produces deterministic user_id hash."""
        auth = APIKeyAuth(api_key="sk-test-12345")
        result1 = await auth.authenticate("sk-test-12345")
        result2 = await auth.authenticate("sk-test-12345")
        assert result1 is not None
        assert result2 is not None
        assert result1["user_id"] == result2["user_id"]


# ---------------------------------------------------------------------------
# BasicAuth Tests
# ---------------------------------------------------------------------------


class TestBasicAuth:
    """Tests for HTTP Basic authentication."""

    def _encode_creds(self, username: str, password: str) -> str:
        """Helper to encode credentials as base64."""
        return base64.b64encode(f"{username}:{password}".encode()).decode()

    @pytest.mark.asyncio
    async def test_basic_auth_direct(self) -> None:
        """Direct credentials authentication succeeds."""
        auth = BasicAuth(username="admin", password="test-only-pwd")
        creds = self._encode_creds("admin", "test-only-pwd")
        result = await auth.authenticate(creds)
        assert result is not None
        assert result["username"] == "admin"
        assert result["user_id"] == "admin"

    @pytest.mark.asyncio
    async def test_basic_auth_direct_wrong_username(self) -> None:
        """Wrong username fails."""
        auth = BasicAuth(username="admin", password="test-only-pwd")
        creds = self._encode_creds("user", "test-only-pwd")
        result = await auth.authenticate(creds)
        assert result is None

    @pytest.mark.asyncio
    async def test_basic_auth_direct_wrong_password(self) -> None:
        """Wrong password fails."""
        auth = BasicAuth(username="admin", password="test-only-pwd")
        creds = self._encode_creds("admin", "wrong")
        result = await auth.authenticate(creds)
        assert result is None

    @pytest.mark.asyncio
    async def test_basic_auth_from_secret_store(self, store: SecretStore) -> None:
        """Credentials resolved from SecretStore."""
        await store.set("auth_username", "user1")
        await store.set("auth_password", "pass1")
        auth = BasicAuth(secret_store=store)
        creds = self._encode_creds("user1", "pass1")
        result = await auth.authenticate(creds)
        assert result is not None
        assert result["username"] == "user1"

    @pytest.mark.asyncio
    async def test_basic_auth_from_env(self) -> None:
        """Credentials resolved from environment variables."""
        with patch.dict(
            os.environ,
            {"DAGLOOM_AUTH_USERNAME": "envuser", "DAGLOOM_AUTH_PASSWORD": "envpass"},
        ):
            auth = BasicAuth()
            creds = self._encode_creds("envuser", "envpass")
            result = await auth.authenticate(creds)
            assert result is not None
            assert result["username"] == "envuser"

    @pytest.mark.asyncio
    async def test_basic_auth_malformed_base64(self) -> None:
        """Malformed base64 fails gracefully."""
        auth = BasicAuth(username="admin", password="test-only-pwd")
        result = await auth.authenticate("not-valid-base64!!!")
        assert result is None

    @pytest.mark.asyncio
    async def test_basic_auth_malformed_creds_no_colon(self) -> None:
        """Credentials without colon fail."""
        auth = BasicAuth(username="admin", password="test-only-pwd")
        creds = base64.b64encode(b"admin-no-colon").decode()
        result = await auth.authenticate(creds)
        assert result is None

    @pytest.mark.asyncio
    async def test_basic_auth_no_config(self) -> None:
        """Authentication fails when no credentials configured."""
        with patch.dict(os.environ, {}, clear=True):
            auth = BasicAuth()
            creds = self._encode_creds("any", "creds")
            result = await auth.authenticate(creds)
            assert result is None

    def test_password_hashing_consistency(self) -> None:
        """Same password+salt produces same hash."""
        auth = BasicAuth(username="test", password="test-only-pwd")
        password = "mysecret"
        hash1 = auth._hash_password(password)
        # Extract salt and re-hash.
        salt_hex = hash1.split(":")[0]
        salt = bytes.fromhex(salt_hex)
        hash2 = auth._hash_password(password, salt)
        assert hash1 == hash2

    def test_password_verification_success(self) -> None:
        """Password verification succeeds for correct password."""
        auth = BasicAuth(username="test", password="test-only-pwd")
        password = "mypassword"
        hashed = auth._hash_password(password)
        assert auth._verify_password(password, hashed) is True

    def test_password_verification_failure(self) -> None:
        """Password verification fails for wrong password."""
        auth = BasicAuth(username="test", password="test-only-pwd")
        password = "correctpassword"
        hashed = auth._hash_password(password)
        assert auth._verify_password("wrongpassword", hashed) is False

    def test_password_verification_malformed_hash(self) -> None:
        """Verification fails for malformed hash."""
        auth = BasicAuth(username="test", password="test-only-pwd")
        assert auth._verify_password("password", "not-a-valid-hash") is False

    @pytest.mark.asyncio
    async def test_basic_auth_hashed_password(self) -> None:
        """Authentication works with hashed passwords."""
        auth = BasicAuth(username="admin", password="test-only-pwd")
        # Pre-hash the password.
        password = "test-hashed-pwd"
        hashed = auth._hash_password(password)
        # Create a new auth with the hashed password.
        auth2 = BasicAuth(username="admin", password=hashed)
        creds = self._encode_creds("admin", password)
        result = await auth2.authenticate(creds)
        assert result is not None

    @pytest.mark.asyncio
    async def test_basic_auth_custom_hash_iterations(self) -> None:
        """Custom PBKDF2 iterations parameter works."""
        auth = BasicAuth(username="admin", password="test-only-pwd", hash_iterations=50000)
        hash1 = auth._hash_password("password")
        # Verify it can be used.
        assert auth._verify_password("password", hash1) is True


# ---------------------------------------------------------------------------
# NoAuth Tests
# ---------------------------------------------------------------------------


class TestNoAuth:
    """Tests for null authentication provider."""

    @pytest.mark.asyncio
    async def test_no_auth_always_succeeds(self) -> None:
        """NoAuth always authenticates successfully."""
        auth = NoAuth()
        result = await auth.authenticate("any-token")
        assert result is not None
        assert result["user_id"] == "anonymous"
        assert result["authenticated"] is False

    @pytest.mark.asyncio
    async def test_no_auth_empty_token(self) -> None:
        """NoAuth succeeds even with empty token."""
        auth = NoAuth()
        result = await auth.authenticate("")
        assert result is not None
        assert result["user_id"] == "anonymous"
