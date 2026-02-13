"""
Backend utilities module
"""

from .session_helper import SessionHelper
from .progress_helper import calculate_progress
from .error_handler import (
    handle_api_error,
    log_and_raise,
    api_error_handler,
    validate_required,
    validate_session_exists,
    safe_execute,
    build_error_response,
    build_success_response,
)

__all__ = [
    "SessionHelper",
    "calculate_progress",
    "handle_api_error",
    "log_and_raise",
    "api_error_handler",
    "validate_required",
    "validate_session_exists",
    "safe_execute",
    "build_error_response",
    "build_success_response",
]
