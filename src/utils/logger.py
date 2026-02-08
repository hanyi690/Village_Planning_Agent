"""Logging configuration for the Village Planning Agent."""

from __future__ import annotations

import logging
from typing import Final


# Module-level constants
LOG_FORMAT: Final[str] = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DEFAULT_LOG_LEVEL: Final[int] = logging.INFO


def get_logger(name: str = __name__) -> logging.Logger:
    """
    Get or create a logger with consistent configuration.

    Args:
        name: Logger name (defaults to module name)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(DEFAULT_LOG_LEVEL)

    return logger
