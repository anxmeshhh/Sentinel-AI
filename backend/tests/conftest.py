"""Test env vars must be set before any `app.*` module is imported, since
Settings() validates required fields (token_encryption_key, groq_api_key,
session_secret_key) at import time via get_settings()'s lru_cache.
"""

import os
import secrets
import sqlite3

from cryptography.fernet import Fernet
from sqlalchemy import event
from sqlalchemy.engine import Engine

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")
os.environ.setdefault("SESSION_SECRET_KEY", secrets.token_urlsafe(48))
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("LOG_JSON", "false")


@event.listens_for(Engine, "connect")
def _enforce_sqlite_foreign_keys(dbapi_connection, _connection_record):
    """Make SQLite behave like production MySQL about foreign keys.

    SQLite silently ignores FK constraints unless this pragma is set, so a
    delete that leaves orphaned children - or deletes a parent before its
    children - passes here and fails in production. That happened for real:
    `delete_channel` had a passing cascade test while raising an
    IntegrityError on MySQL whenever the channel had a connection assigned.

    Enabling it globally means the test suite can actually catch that class
    of bug instead of granting false confidence.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
