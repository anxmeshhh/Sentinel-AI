"""Structured logging.

Every log line carries whatever correlation ids are bound to the current
context (run_id, workspace_id, connection_id, agent) so a single finding
that looks wrong can be traced back through logs -> the exact agent run ->
the exact signals it read, without grepping timestamps.
"""

import logging
import sys

import structlog

from app.core.config import get_settings

_SENSITIVE_KEYS = {"token", "access_token", "encrypted_token", "authorization", "api_key", "groq_api_key"}


def _redact_sensitive(_logger: object, _method_name: str, event_dict: dict) -> dict:
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***redacted***"
    return event_dict


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        _redact_sensitive,
        structlog.processors.StackInfoRenderer(),
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


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
