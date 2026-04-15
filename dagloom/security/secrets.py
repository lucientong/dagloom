"""Layered secret store with encrypted database backend.

Resolution order:
1. Environment variables (``DAGLOOM_SECRET_<KEY>``)
2. ``.env`` file (via ``python-dotenv``)
3. Encrypted SQLite database (via ``Encryptor`` + ``Database``)

Example::

    store = SecretStore(db=db, encryptor=encryptor)
    await store.set("API_KEY", "sk-abc123")
    value = await store.get("API_KEY")
    keys  = await store.list_keys()
    await store.delete("API_KEY")
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dagloom.security.encryption import Encryptor
from dagloom.store.db import Database

logger = logging.getLogger(__name__)

_ENV_PREFIX = "DAGLOOM_SECRET_"


class SecretStore:
    """Layered secret store with encrypted persistence.

    Resolves secrets by checking, in order:

    1. **Environment variables** — ``DAGLOOM_SECRET_<KEY>``
    2. **.env file** — loaded via ``python-dotenv`` (same prefix)
    3. **Encrypted database** — Fernet-encrypted values in the
       ``secrets`` table

    When setting/deleting secrets, only the database layer is modified.
    Environment variables and ``.env`` entries take precedence on read.

    Args:
        db: Database instance for encrypted storage.
        encryptor: Encryptor instance for Fernet encryption.
        dotenv_path: Path to the ``.env`` file. Defaults to ``.env``
            in the current directory. Set to ``None`` to disable.
    """

    def __init__(
        self,
        db: Database,
        encryptor: Encryptor,
        dotenv_path: str | Path | None = ".env",
    ) -> None:
        self.db = db
        self.encryptor = encryptor
        self.dotenv_path = Path(dotenv_path) if dotenv_path else None
        self._dotenv_values: dict[str, str | None] = {}
        self._load_dotenv()

    def _load_dotenv(self) -> None:
        """Load values from .env file if it exists."""
        if self.dotenv_path and self.dotenv_path.exists():
            try:
                from dotenv import dotenv_values

                self._dotenv_values = dotenv_values(self.dotenv_path)
                logger.debug("Loaded .env from %s", self.dotenv_path)
            except ImportError:
                logger.debug("python-dotenv not installed, skipping .env file.")

    async def get(self, key: str) -> str | None:
        """Retrieve a secret by key.

        Resolution order: env var → .env → encrypted DB.

        Args:
            key: The secret key name.

        Returns:
            The plaintext secret value, or ``None`` if not found.
        """
        # Layer 1: Environment variable.
        env_key = f"{_ENV_PREFIX}{key}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            logger.debug("Secret %r resolved from environment variable.", key)
            return env_val

        # Layer 2: .env file.
        dotenv_val = self._dotenv_values.get(env_key)
        if dotenv_val is not None:
            logger.debug("Secret %r resolved from .env file.", key)
            return dotenv_val

        # Layer 3: Encrypted database.
        row = await self.db.get_secret(key)
        if row is not None:
            plaintext = self.encryptor.decrypt(row["encrypted_value"])
            logger.debug("Secret %r resolved from encrypted database.", key)
            return plaintext

        return None

    async def set(self, key: str, value: str) -> None:
        """Store a secret (encrypted) in the database.

        Args:
            key: The secret key name.
            value: The plaintext secret value to encrypt and store.
        """
        encrypted = self.encryptor.encrypt(value)
        await self.db.save_secret(key, encrypted)
        logger.info("Secret %r saved to encrypted database.", key)

    async def delete(self, key: str) -> bool:
        """Delete a secret from the database.

        Args:
            key: The secret key name.

        Returns:
            ``True`` if the secret existed and was deleted.
        """
        existing = await self.db.get_secret(key)
        if existing is None:
            return False
        await self.db.delete_secret(key)
        logger.info("Secret %r deleted from database.", key)
        return True

    async def list_keys(self) -> list[str]:
        """List all secret key names from the database.

        .. note::

            This only returns keys stored in the database, not those
            from environment variables or ``.env`` files.

        Returns:
            A list of secret key names (values are never exposed).
        """
        rows = await self.db.list_secrets()
        return [row["key"] for row in rows]

    async def exists(self, key: str) -> bool:
        """Check if a secret exists (in any layer).

        Args:
            key: The secret key name.

        Returns:
            ``True`` if the secret is resolvable.
        """
        return await self.get(key) is not None

    def reload_dotenv(self) -> None:
        """Reload the ``.env`` file (e.g. after external edits)."""
        self._dotenv_values = {}
        self._load_dotenv()
