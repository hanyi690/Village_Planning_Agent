"""
Structured logging with session_id correlation and file persistence.

- SessionFilter: injects session_id into log records
- get_logger(): returns logger with session-aware formatting
- File handlers configured centrally in main.py LOGGING_CONFIG
"""

import logging
import contextvars
from pathlib import Path
from app.core.settings import LOG_DIR

# Context-var for session_id correlation across async calls
_session_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("session_id", default="")


def set_session_id(sid: str):
    """Set session_id for current async context (call once per request)."""
    return _session_id_var.set(sid)


def reset_session_id(token) -> None:
    _session_id_var.reset(token)


def get_session_id() -> str:
    return _session_id_var.get()


class SessionFilter(logging.Filter):
    """Inject session_id into log records from context var."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.session_id = _session_id_var.get("")  # type: ignore[attr-defined]
        return True


def ensure_log_dir() -> Path:
    """Create logs/ directory if it doesn't exist."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR


def get_logger(name: str = __name__) -> logging.Logger:
    """Get a logger instance. Handlers are configured centrally in main.py."""
    return logging.getLogger(name)
