"""Structured logging.

Every log line carries whatever correlation ids are bound to the current
context (run_id, workspace_id, connection_id, agent) so a single finding
that looks wrong can be traced back through logs -> the exact agent run ->
the exact signals it read, without grepping timestamps.

Logs go to two places with identical structure: stdout (for `docker compose
logs`) and a rotating JSONL file (LOG_FILE_PATH) that the admin panel's log
viewer reads (`GET /admin/logs`). This must be configured identically in the
API process, the Celery worker, and Celery beat - `core/celery_app.py` calls
`configure_logging()` at import time so worker/beat get the same structured
output instead of falling back to Celery's own plain-text logging.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import structlog

from app.core.config import get_settings

_SENSITIVE_KEYS = {"token", "access_token", "encrypted_token", "authorization", "api_key", "groq_api_key"}

LOG_DIR = os.environ.get("SENTINEL_LOG_DIR", "logs")
LOG_FILE_PATH = os.path.join(LOG_DIR, "sentinel.jsonl")

_configured = False


def _redact_sensitive(_logger: object, _method_name: str, event_dict: dict) -> dict:
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***redacted***"
    return event_dict


def configure_logging() -> None:
    global _configured
    if _configured:
        return  # avoid double-adding handlers if called more than once in a process
    _configured = True

    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        _redact_sensitive,
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Both handlers render through the SAME structlog pipeline (ProcessorFormatter),
    # so stdout and the persisted file are always in sync, in JSON, regardless of
    # which process emitted the line.
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    os.makedirs(LOG_DIR, exist_ok=True)
    file_handler = RotatingFileHandler(LOG_FILE_PATH, maxBytes=5_000_000, backupCount=3)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


def get_logger(name: str = "sentinel") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def bind_run_context(*, run_id: str, workspace_id: str, agent: str | None = None, connection_id: str | None = None) -> None:
    """Bind correlation ids to every subsequent log line on this thread/task until cleared."""
    structlog.contextvars.bind_contextvars(
        run_id=run_id,
        workspace_id=workspace_id,
        **({"agent": agent} if agent else {}),
        **({"connection_id": connection_id} if connection_id else {}),
    )


def clear_run_context() -> None:
    structlog.contextvars.clear_contextvars()
