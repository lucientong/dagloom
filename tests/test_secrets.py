"""Tests for credential security management (P1-5).

Covers:
- Encryptor: encrypt/decrypt, key generation, master key from env, ephemeral key
- DecryptionError: wrong key, corrupted data
- SecretStore: layered resolution (env → .env → DB), set/get/delete/list/exists
- Database: secrets table CRUD (save, get, list, delete)
- REST API: GET/POST/DELETE /api/secrets
- CLI: dagloom secret set/get/list/delete
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from click.testing import CliRunner

from dagloom.cli.main import cli
from dagloom.security.encryption import DecryptionError, Encryptor
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
async def store(db: Database, encryptor: Encryptor, tmp_path: Path) -> SecretStore:
    """Create a SecretStore backed by temp DB and encryptor."""
    return SecretStore(db=db, encryptor=encryptor, dotenv_path=None)


# ---------------------------------------------------------------------------
# Encryptor
# ---------------------------------------------------------------------------


class TestEncryptor:
    """Tests for Fernet encryption wrapper."""

    def test_encrypt_decrypt_roundtrip(self, encryptor: Encryptor) -> None:
        """Encrypt then decrypt returns original plaintext."""
        plaintext = "super-secret-api-key-12345"
        encrypted = encryptor.encrypt(plaintext)
        assert encrypted != plaintext
        decrypted = encryptor.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_produces_different_tokens(self, encryptor: Encryptor) -> None:
        """Same plaintext encrypted twice produces different tokens (Fernet uses timestamp)."""
        t1 = encryptor.encrypt("same")
        t2 = encryptor.encrypt("same")
        assert t1 != t2  # Fernet includes timestamp nonce.

    def test_decrypt_wrong_key_raises(self) -> None:
        """Decrypting with a different key raises DecryptionError."""
        enc1 = Encryptor(master_key=Encryptor.generate_key())
        enc2 = Encryptor(master_key=Encryptor.generate_key())

        encrypted = enc1.encrypt("hello")
        with pytest.raises(DecryptionError, match="Failed to decrypt"):
            enc2.decrypt(encrypted)

    def test_decrypt_corrupted_data_raises(self, encryptor: Encryptor) -> None:
        """Corrupted token raises DecryptionError."""
        with pytest.raises(DecryptionError, match="Failed to decrypt"):
            encryptor.decrypt("not-a-valid-fernet-token")

    def test_generate_key(self) -> None:
        """generate_key returns a valid Fernet key string."""
        key = Encryptor.generate_key()
        assert isinstance(key, str)
        assert len(key) == 44  # Base64-encoded 32 bytes.
        # Should be usable to create a new Encryptor.
        enc = Encryptor(master_key=key)
        assert enc.decrypt(enc.encrypt("test")) == "test"

    def test_key_property(self, encryptor: Encryptor) -> None:
        """key property returns the master key as string."""
        key = encryptor.key
        assert isinstance(key, str)
        # Can create a new encryptor with the same key.
        enc2 = Encryptor(master_key=key)
        encrypted = encryptor.encrypt("shared")
        assert enc2.decrypt(encrypted) == "shared"

    def test_master_key_from_env(self) -> None:
        """Encryptor reads DAGLOOM_MASTER_KEY from environment."""
        key = Encryptor.generate_key()
        with patch.dict(os.environ, {"DAGLOOM_MASTER_KEY": key}):
            enc = Encryptor()
            assert enc.key == key

    def test_ephemeral_key_warning(self) -> None:
        """Without env var or explicit key, a warning is logged."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove the env var if it exists.
            os.environ.pop("DAGLOOM_MASTER_KEY", None)
            enc = Encryptor()
            # Should still work — just with an ephemeral key.
            assert enc.decrypt(enc.encrypt("test")) == "test"

    def test_encrypt_empty_string(self, encryptor: Encryptor) -> None:
        """Empty string can be encrypted and decrypted."""
        assert encryptor.decrypt(encryptor.encrypt("")) == ""

    def test_key_file_creates_and_persists(self, tmp_path: Path) -> None:
        """key_file creates a new key file when it doesn't exist."""
        key_path = tmp_path / "master.key"
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("DAGLOOM_MASTER_KEY", None)
            enc = Encryptor(key_file=key_path)
            assert key_path.exists()
            # File should contain the key.
            assert key_path.read_text().strip() == enc.key

    def test_key_file_reuses_existing(self, tmp_path: Path) -> None:
        """key_file reuses an existing key file across invocations."""
        key_path = tmp_path / "master.key"
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("DAGLOOM_MASTER_KEY", None)
            enc1 = Encryptor(key_file=key_path)
            encrypted = enc1.encrypt("my-secret")

            enc2 = Encryptor(key_file=key_path)
            assert enc2.key == enc1.key
            assert enc2.decrypt(encrypted) == "my-secret"

    def test_key_file_permissions(self, tmp_path: Path) -> None:
        """key_file is created with 0o600 permissions."""
        key_path = tmp_path / "master.key"
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("DAGLOOM_MASTER_KEY", None)
            Encryptor(key_file=key_path)
            mode = key_path.stat().st_mode & 0o777
            assert mode == 0o600

    def test_key_file_creates_parent_dirs(self, tmp_path: Path) -> None:
        """key_file creates parent directories if needed."""
        key_path = tmp_path / "subdir" / "deep" / "master.key"
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("DAGLOOM_MASTER_KEY", None)
            enc = Encryptor(key_file=key_path)
            assert key_path.exists()
            assert enc.decrypt(enc.encrypt("test")) == "test"

    def test_env_var_takes_precedence_over_key_file(self, tmp_path: Path) -> None:
        """DAGLOOM_MASTER_KEY env var takes precedence over key_file."""
        key_path = tmp_path / "master.key"
        env_key = Encryptor.generate_key()
        with patch.dict(os.environ, {"DAGLOOM_MASTER_KEY": env_key}):
            enc = Encryptor(key_file=key_path)
            assert enc.key == env_key
            # key_file should NOT have been created.
            assert not key_path.exists()

    def test_encrypt_unicode(self, encryptor: Encryptor) -> None:
        """Unicode strings are handled correctly."""
        value = "密码🔑Пароль"
        assert encryptor.decrypt(encryptor.encrypt(value)) == value


# ---------------------------------------------------------------------------
# Database Secrets CRUD
# ---------------------------------------------------------------------------


class TestDatabaseSecretsCRUD:
    """Tests for the secrets table in Database."""

    @pytest.mark.asyncio
    async def test_save_and_get_secret(self, db: Database) -> None:
        """Save then retrieve a secret."""
        await db.save_secret("API_KEY", "encrypted_value_here")
        row = await db.get_secret("API_KEY")
        assert row is not None
        assert row["key"] == "API_KEY"
        assert row["encrypted_value"] == "encrypted_value_here"
        assert "created_at" in row
        assert "updated_at" in row

    @pytest.mark.asyncio
    async def test_save_secret_upsert(self, db: Database) -> None:
        """Saving with same key updates the value."""
        await db.save_secret("DB_PASS", "old_value")
        await db.save_secret("DB_PASS", "new_value")
        row = await db.get_secret("DB_PASS")
        assert row is not None
        assert row["encrypted_value"] == "new_value"

    @pytest.mark.asyncio
    async def test_get_nonexistent_secret(self, db: Database) -> None:
        """Getting a non-existent key returns None."""
        assert await db.get_secret("NONEXISTENT") is None

    @pytest.mark.asyncio
    async def test_list_secrets(self, db: Database) -> None:
        """List returns all keys sorted alphabetically."""
        await db.save_secret("B_KEY", "val_b")
        await db.save_secret("A_KEY", "val_a")
        await db.save_secret("C_KEY", "val_c")

        rows = await db.list_secrets()
        assert len(rows) == 3
        keys = [r["key"] for r in rows]
        assert keys == ["A_KEY", "B_KEY", "C_KEY"]
        # Values should NOT be in the list output.
        assert "encrypted_value" not in rows[0]

    @pytest.mark.asyncio
    async def test_delete_secret(self, db: Database) -> None:
        """Delete removes a secret."""
        await db.save_secret("TEMP", "val")
        await db.delete_secret("TEMP")
        assert await db.get_secret("TEMP") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_secret(self, db: Database) -> None:
        """Deleting a non-existent key does not raise."""
        await db.delete_secret("NOTHING")  # Should not raise.


# ---------------------------------------------------------------------------
# SecretStore layered resolution
# ---------------------------------------------------------------------------


class TestSecretStore:
    """Tests for SecretStore with layered resolution."""

    @pytest.mark.asyncio
    async def test_set_and_get_from_db(self, store: SecretStore) -> None:
        """Set stores encrypted; get decrypts from DB."""
        await store.set("MY_SECRET", "hunter2")
        value = await store.get("MY_SECRET")
        assert value == "hunter2"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, store: SecretStore) -> None:
        """Getting a non-existent key returns None."""
        assert await store.get("NOPE") is None

    @pytest.mark.asyncio
    async def test_env_var_takes_precedence(self, store: SecretStore) -> None:
        """Environment variable overrides DB value."""
        await store.set("MY_KEY", "db_value")
        with patch.dict(os.environ, {"DAGLOOM_SECRET_MY_KEY": "env_value"}):
            result = await store.get("MY_KEY")
            assert result == "env_value"

    @pytest.mark.asyncio
    async def test_dotenv_takes_precedence_over_db(
        self, db: Database, encryptor: Encryptor, tmp_path: Path
    ) -> None:
        """ ".env file value overrides DB value."""
        dotenv_file = tmp_path / ".env"
        dotenv_file.write_text("DAGLOOM_SECRET_API_TOKEN=dotenv_value\n")

        local_store = SecretStore(db=db, encryptor=encryptor, dotenv_path=dotenv_file)
        await local_store.set("API_TOKEN", "db_value")

        result = await local_store.get("API_TOKEN")
        assert result == "dotenv_value"

    @pytest.mark.asyncio
    async def test_env_takes_precedence_over_dotenv(
        self, db: Database, encryptor: Encryptor, tmp_path: Path
    ) -> None:
        """Environment variable overrides both .env and DB."""
        dotenv_file = tmp_path / ".env"
        dotenv_file.write_text("DAGLOOM_SECRET_KEY=dotenv_val\n")

        local_store = SecretStore(db=db, encryptor=encryptor, dotenv_path=dotenv_file)
        await local_store.set("KEY", "db_val")

        with patch.dict(os.environ, {"DAGLOOM_SECRET_KEY": "env_val"}):
            result = await local_store.get("KEY")
            assert result == "env_val"

    @pytest.mark.asyncio
    async def test_delete_secret(self, store: SecretStore) -> None:
        """Delete removes from DB and returns True."""
        await store.set("TEMP", "val")
        assert await store.delete("TEMP") is True
        assert await store.get("TEMP") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, store: SecretStore) -> None:
        """Deleting non-existent key returns False."""
        assert await store.delete("NOTHING") is False

    @pytest.mark.asyncio
    async def test_list_keys(self, store: SecretStore) -> None:
        """list_keys returns DB keys only."""
        await store.set("A", "1")
        await store.set("B", "2")
        keys = await store.list_keys()
        assert set(keys) == {"A", "B"}

    @pytest.mark.asyncio
    async def test_exists_true(self, store: SecretStore) -> None:
        """exists returns True for stored secret."""
        await store.set("EXISTS", "yes")
        assert await store.exists("EXISTS") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, store: SecretStore) -> None:
        """exists returns False for missing secret."""
        assert await store.exists("MISSING") is False

    @pytest.mark.asyncio
    async def test_exists_via_env(self, store: SecretStore) -> None:
        """exists returns True when secret is in env."""
        with patch.dict(os.environ, {"DAGLOOM_SECRET_ENV_ONLY": "val"}):
            assert await store.exists("ENV_ONLY") is True

    @pytest.mark.asyncio
    async def test_reload_dotenv(self, db: Database, encryptor: Encryptor, tmp_path: Path) -> None:
        """reload_dotenv picks up new values."""
        dotenv_file = tmp_path / ".env"
        dotenv_file.write_text("DAGLOOM_SECRET_X=old\n")

        local_store = SecretStore(db=db, encryptor=encryptor, dotenv_path=dotenv_file)
        assert await local_store.get("X") == "old"

        dotenv_file.write_text("DAGLOOM_SECRET_X=new\n")
        local_store.reload_dotenv()
        assert await local_store.get("X") == "new"

    def test_no_dotenv_file(self, db: Database, encryptor: Encryptor) -> None:
        """SecretStore works when .env file doesn't exist."""
        store = SecretStore(db=db, encryptor=encryptor, dotenv_path="/nonexistent/.env")
        assert store._dotenv_values == {}

    def test_dotenv_disabled(self, db: Database, encryptor: Encryptor) -> None:
        """SecretStore works with dotenv_path=None."""
        store = SecretStore(db=db, encryptor=encryptor, dotenv_path=None)
        assert store._dotenv_values == {}


# ---------------------------------------------------------------------------
# REST API endpoints
# ---------------------------------------------------------------------------


class TestSecretsAPI:
    """Tests for /api/secrets endpoints."""

    @pytest_asyncio.fixture
    async def client(self, tmp_path: Path) -> Any:  # type: ignore[misc]
        """Create an async HTTP test client."""
        from httpx import ASGITransport, AsyncClient

        from dagloom.server.api import router, set_state
        from dagloom.store.db import Database

        db = Database(tmp_path / "api_test.db")
        await db.connect()
        set_state("db", db)

        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

        await db.close()

    @pytest.mark.asyncio
    async def test_list_secrets_empty(self, client: Any) -> None:
        """GET /api/secrets returns empty list initially."""
        resp = await client.get("/api/secrets")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_create_secret(self, client: Any) -> None:
        """POST /api/secrets creates an encrypted secret."""
        resp = await client.post("/api/secrets", json={"key": "API_KEY", "value": "sk-123"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["key"] == "API_KEY"
        assert data["status"] == "created"

    @pytest.mark.asyncio
    async def test_create_then_list(self, client: Any) -> None:
        """Created secrets appear in list (values not exposed)."""
        await client.post("/api/secrets", json={"key": "K1", "value": "v1"})
        await client.post("/api/secrets", json={"key": "K2", "value": "v2"})

        resp = await client.get("/api/secrets")
        assert resp.status_code == 200
        keys = [s["key"] for s in resp.json()]
        assert "K1" in keys
        assert "K2" in keys
        # Values should NOT be in response.
        for s in resp.json():
            assert "value" not in s
            assert "encrypted_value" not in s

    @pytest.mark.asyncio
    async def test_delete_secret(self, client: Any) -> None:
        """DELETE /api/secrets/{key} removes a secret."""
        await client.post("/api/secrets", json={"key": "DEL_ME", "value": "tmp"})
        resp = await client.delete("/api/secrets/DEL_ME")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # Should be gone now.
        list_resp = await client.get("/api/secrets")
        keys = [s["key"] for s in list_resp.json()]
        assert "DEL_ME" not in keys

    @pytest.mark.asyncio
    async def test_delete_nonexistent_secret(self, client: Any) -> None:
        """DELETE non-existent returns 404."""
        resp = await client.delete("/api/secrets/NOPE")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


class TestSecretsCLI:
    """Tests for dagloom secret CLI commands."""

    def test_secret_list_empty(self) -> None:
        """'dagloom secret list' shows no secrets when empty."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["secret", "list"])
            assert result.exit_code == 0
            assert "No secrets stored" in result.output

    def test_secret_set_and_list(self) -> None:
        """'dagloom secret set' then 'dagloom secret list' shows the key."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            # Need consistent master key for set/get.
            key = Encryptor.generate_key()
            with patch.dict(os.environ, {"DAGLOOM_MASTER_KEY": key}):
                result = runner.invoke(cli, ["secret", "set", "MY_KEY", "my_value"])
                assert result.exit_code == 0
                assert "saved" in result.output

                result = runner.invoke(cli, ["secret", "list"])
                assert result.exit_code == 0
                assert "MY_KEY" in result.output

    def test_secret_get(self) -> None:
        """'dagloom secret get' retrieves the plaintext value."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            key = Encryptor.generate_key()
            with patch.dict(os.environ, {"DAGLOOM_MASTER_KEY": key}):
                runner.invoke(cli, ["secret", "set", "TOKEN", "abc123"])
                result = runner.invoke(cli, ["secret", "get", "TOKEN"])
                assert result.exit_code == 0
                assert "abc123" in result.output

    def test_secret_get_nonexistent(self) -> None:
        """'dagloom secret get' for missing key exits with error."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            key = Encryptor.generate_key()
            with patch.dict(os.environ, {"DAGLOOM_MASTER_KEY": key}):
                result = runner.invoke(cli, ["secret", "get", "MISSING"])
                assert result.exit_code == 1
                assert "not found" in result.output

    def test_secret_delete(self) -> None:
        """'dagloom secret delete' removes a secret."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            key = Encryptor.generate_key()
            with patch.dict(os.environ, {"DAGLOOM_MASTER_KEY": key}):
                runner.invoke(cli, ["secret", "set", "DEL", "val"])
                result = runner.invoke(cli, ["secret", "delete", "DEL"])
                assert result.exit_code == 0
                assert "deleted" in result.output

    def test_secret_delete_nonexistent(self) -> None:
        """'dagloom secret delete' for missing key exits with error."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            key = Encryptor.generate_key()
            with patch.dict(os.environ, {"DAGLOOM_MASTER_KEY": key}):
                result = runner.invoke(cli, ["secret", "delete", "NOPE"])
                assert result.exit_code == 1
                assert "not found" in result.output
