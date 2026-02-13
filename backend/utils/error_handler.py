# -*- coding: utf-8 -*-
"""
Centralized Error Handling for Backend APIs

Provides standardized error handling utilities to reduce code duplication
across API endpoints.
"""

import functools
import logging
import traceback
from typing import Any, Callable, TypeVar

from fastapi import HTTPException


T = TypeVar("T")
logger = logging.getLogger(__name__)


def handle_api_error(
    error: Exception,
    context: str,
    status_code: int = 500,
    reraise: bool = False
) -> HTTPException:
    """
    Standardized API error handler

    Args:
        error: The exception that occurred
        context: Description of where the error happened
        status_code: HTTP status code to return
        reraise: If True, re-raises the exception instead of returning HTTPException

    Returns:
        HTTPException with formatted error message
    """
    error_msg = str(error)
    logger.error(f"[ERROR] {context}: {error_msg}", exc_info=True)

    if reraise:
        raise

    return HTTPException(
        status_code=status_code,
        detail=f"{context} failed: {error_msg}"
    )


def log_and_raise(
    error: Exception,
    context: str,
    status_code: int = 500
) -> None:
    """
    Log error and raise HTTPException

    Use this when you want to always raise an exception.

    Args:
        error: The exception that occurred
        context: Description of where the error happened
        status_code: HTTP status code

    Raises:
        HTTPException
    """
    error_msg = str(error)
    logger.error(f"[ERROR] {context}: {error_msg}", exc_info=True)
    raise HTTPException(
        status_code=status_code,
        detail=f"{context} failed: {error_msg}"
    )


def api_error_handler(
    context: str,
    status_code: int = 500,
    reraise: bool = False
):
    """
    Decorator to automatically handle exceptions in API endpoints

    Args:
        context: Description of what the endpoint does
        status_code: HTTP status code for errors
        reraise: If True, re-raises instead of catching
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as e:
                raise handle_api_error(e, context, status_code, reraise)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as e:
                raise handle_api_error(e, context, status_code, reraise)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator


def validate_required(value: Any, field_name: str, min_length: int = 0) -> None:
    """
    Validate required field

    Args:
        value: Value to validate
        field_name: Name of the field (for error message)
        min_length: Minimum length for string values

    Raises:
        HTTPException: If validation fails
    """
    if not value or (isinstance(value, str) and len(value.strip()) < min_length):
        suffix = f" or too short (min {min_length} chars)" if min_length > 0 else ""
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} cannot be empty{suffix}"
        )


def validate_session_exists(session_id: str, sessions_dict: dict) -> None:
    """
    Validate that a session exists

    Args:
        session_id: Session ID to validate
        sessions_dict: Dictionary containing sessions

    Raises:
        HTTPException: If session not found
    """
    if session_id not in sessions_dict:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}"
        )


def safe_execute(
    func: Callable[..., T],
    *args: Any,
    default: T = None,
    log_error: bool = True,
    **kwargs: Any
) -> T:
    """
    Safely execute a function, returning default on error

    Args:
        func: Function to execute
        *args: Positional arguments for function
        default: Value to return on error
        log_error: Whether to log errors
        **kwargs: Keyword arguments for function

    Returns:
        Function result or default value
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if log_error:
            logger.error(f"Safe execution failed: {e}")
        return default


def build_error_response(
    error: str,
    context: str | None = None
) -> dict:
    """
    Build standardized error response

    Args:
        error: Error message
        context: Optional context about where the error occurred

    Returns:
        Error response dict
    """
    if context:
        logger.error(f"[ERROR] {context}: {error}")

    return {
        "success": False,
        "error": error,
        "message": f"{context}: {error}" if context else error
    }


def build_success_response(
    message: str,
    **data: Any
) -> dict:
    """
    Build standardized success response

    Args:
        message: Success message
        **data: Additional data to include

    Returns:
        Success response dict
    """
    return {
        "success": True,
        "message": message,
        **data
    }


__all__ = [
    "handle_api_error",
    "log_and_raise",
    "api_error_handler",
    "validate_required",
    "validate_session_exists",
    "safe_execute",
    "build_error_response",
    "build_success_response",
]
