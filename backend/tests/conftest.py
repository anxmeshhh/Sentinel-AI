"""Test env vars must be set before any `app.*` module is imported, since
Settings() validates required fields (token_encryption_key, groq_api_key) at
import time via get_settings()'s lru_cache.
"""

import os

from cryptography.fernet import Fernet

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("LOG_JSON", "false")
