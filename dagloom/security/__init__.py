"""Credential security management.

Provides encrypted secret storage with layered resolution:
environment variables → .env file → encrypted SQLite database.

Also provides authentication providers for API Key and Basic Auth.
"""

from dagloom.security.auth import APIKeyAuth, AuthProvider, BasicAuth, NoAuth
from dagloom.security.encryption import DecryptionError, Encryptor
from dagloom.security.secrets import SecretStore

__all__ = [
    "DecryptionError",
    "Encryptor",
    "SecretStore",
    "AuthProvider",
    "APIKeyAuth",
    "BasicAuth",
    "NoAuth",
]
