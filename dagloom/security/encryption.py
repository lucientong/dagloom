"""Fernet-based encryption for secret values.

Uses a master key resolved in priority order:

1. Explicit ``master_key`` argument.
2. ``DAGLOOM_MASTER_KEY`` environment variable.
3. ``key_file`` path — reads the key from disk, or auto-generates one
   and persists it with ``0o600`` permissions (CLI-friendly).
4. Ephemeral random key (development only — warning logged).

Example::

    encryptor = Encryptor()                     # from env var
    encryptor = Encryptor(master_key="base64…")  # explicit key
    encryptor = Encryptor(key_file="~/.myapp/master.key")  # file-backed

    encrypted = encryptor.encrypt("my-secret")
    decrypted = encryptor.decrypt(encrypted)
    assert decrypted == "my-secret"
"""

from __future__ import annotations

import contextlib
import logging
import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_ENV_MASTER_KEY = "DAGLOOM_MASTER_KEY"


class DecryptionError(Exception):
    """Raised when decryption fails (wrong key, corrupted data)."""


class Encryptor:
    """Fernet symmetric encryption wrapper.

    Args:
        master_key: A URL-safe base64-encoded 32-byte key.  If ``None``,
            the key is resolved from the environment or ``key_file``.
        key_file: Path to a file storing the master key.  When the env var
            is unset and ``master_key`` is ``None``, the key is read from
            this file.  If the file does not exist, a new key is generated
            and written with owner-only permissions (``0o600``).
    """

    def __init__(
        self,
        master_key: str | None = None,
        key_file: str | Path | None = None,
    ) -> None:
        if master_key is not None:
            self._key = master_key.encode() if isinstance(master_key, str) else master_key
        else:
            env_key = os.environ.get(_ENV_MASTER_KEY)
            if env_key:
                self._key = env_key.encode()
            elif key_file is not None:
                self._key = self._load_or_create_key(Path(key_file).expanduser())
            else:
                self._key = Fernet.generate_key()
                logger.warning(
                    "DAGLOOM_MASTER_KEY not set — generated ephemeral key. "
                    "Secrets will NOT be recoverable after restart. "
                    "Set DAGLOOM_MASTER_KEY or pass key_file for production use."
                )
        self._fernet = Fernet(self._key)

    @property
    def key(self) -> str:
        """Return the master key as a string (for persistence)."""
        return self._key.decode()

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string.

        Args:
            plaintext: The secret value to encrypt.

        Returns:
            A URL-safe base64-encoded encrypted token (string).
        """
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        """Decrypt an encrypted token back to plaintext.

        Args:
            token: The encrypted token produced by :meth:`encrypt`.

        Returns:
            The original plaintext string.

        Raises:
            DecryptionError: If the token is invalid or the key is wrong.
        """
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except (InvalidToken, Exception) as exc:
            raise DecryptionError(f"Failed to decrypt secret: {exc}") from exc

    @staticmethod
    def _load_or_create_key(key_path: Path) -> bytes:
        """Load a master key from *key_path*, or generate and persist one.

        The file is created with owner-only permissions (``0o600``) on
        Unix-like systems.

        Args:
            key_path: Path to the key file.

        Returns:
            The key as bytes.
        """
        if key_path.exists():
            key = key_path.read_text().strip().encode()
            logger.debug("Master key loaded from %s", key_path)
            return key

        # Generate, persist, and restrict permissions.
        key_path.parent.mkdir(parents=True, exist_ok=True)
        new_key = Fernet.generate_key()
        key_path.write_text(new_key.decode())
        with contextlib.suppress(OSError):
            key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        logger.info("Generated and saved master key to %s", key_path)
        return new_key

    @staticmethod
    def generate_key() -> str:
        """Generate a new random Fernet key.

        Returns:
            A URL-safe base64-encoded 32-byte key string.
        """
        return Fernet.generate_key().decode()
