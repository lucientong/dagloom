"""Fernet-based encryption for secret values.

Uses a master key derived from the ``DAGLOOM_MASTER_KEY`` environment
variable.  If the variable is not set, a random key is generated and
logged as a warning (suitable for development only).

Example::

    encryptor = Encryptor()                     # from env var
    encryptor = Encryptor(master_key="base64…")  # explicit key

    encrypted = encryptor.encrypt("my-secret")
    decrypted = encryptor.decrypt(encrypted)
    assert decrypted == "my-secret"
"""

from __future__ import annotations

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_ENV_MASTER_KEY = "DAGLOOM_MASTER_KEY"


class DecryptionError(Exception):
    """Raised when decryption fails (wrong key, corrupted data)."""


class Encryptor:
    """Fernet symmetric encryption wrapper.

    Args:
        master_key: A URL-safe base64-encoded 32-byte key.  If ``None``,
            the key is read from the ``DAGLOOM_MASTER_KEY`` environment
            variable.  If neither is available, a random key is generated
            (development mode — a warning is logged).
    """

    def __init__(self, master_key: str | None = None) -> None:
        if master_key is not None:
            self._key = master_key.encode() if isinstance(master_key, str) else master_key
        else:
            env_key = os.environ.get(_ENV_MASTER_KEY)
            if env_key:
                self._key = env_key.encode()
            else:
                self._key = Fernet.generate_key()
                logger.warning(
                    "DAGLOOM_MASTER_KEY not set — generated ephemeral key. "
                    "Secrets will NOT be recoverable after restart. "
                    "Set DAGLOOM_MASTER_KEY for production use."
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
    def generate_key() -> str:
        """Generate a new random Fernet key.

        Returns:
            A URL-safe base64-encoded 32-byte key string.
        """
        return Fernet.generate_key().decode()
