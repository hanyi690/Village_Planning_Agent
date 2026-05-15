import logging
from app.core.settings import LOG_LEVEL


def get_logger(name=__name__):
    """Get a logger instance. Handlers are configured centrally in main.py."""
    return logging.getLogger(name)