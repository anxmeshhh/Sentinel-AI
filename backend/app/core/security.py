"""Encryption for third-party credentials (GitHub/Jira/Slack tokens) at rest.

Tokens are never stored or logged in plaintext. `token_encryption_key` is a
Fernet key held only in the deployment's secret store / .env, never in git.
"""

from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().token_encryption_key.encode())


def encrypt_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
