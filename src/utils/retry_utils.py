"""
Retry utilities for handling transient failures.

Provides configurable retry mechanisms with exponential backoff for operations
that may fail temporarily (e.g., API calls, file I/O, database operations).

Features:
- RetryConfig class for configuration
- retry_on_exception decorator for exception-based retry
- retry_with_timeout decorator for timeout-aware retry
- Exponential backoff with optional jitter
"""

import time
import random
import functools
import inspect
from typing import Callable, Type, Tuple, Optional, Any, List, Dict
from dataclasses import dataclass, field

from .logger import get_logger

logger = get_logger(__name__)


@dataclass
class RetryConfig:
    """
    Retry configuration.

    Attributes:
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Base delay between retries in seconds (default: 1.0)
        max_delay: Maximum delay between retries in seconds (default: 10.0)
        exponential: Whether to use exponential backoff (default: True)
        jitter: Whether to add random jitter to delays (default: True)
        timeout: Timeout for each attempt in seconds (default: None, no timeout)
        retry_on_exceptions: Tuple of exception types to retry on (default: Exception)
        retry_on_timeout: Whether to retry on timeout errors (default: True)
    """
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 10.0
    exponential: bool = True
    jitter: bool = True
    timeout: Optional[float] = None
    retry_on_exceptions: Tuple[Type[Exception], ...] = (Exception,)
    retry_on_timeout: bool = True

    def get_delay(self, attempt: int) -> float:
        """
        Calculate delay for a given retry attempt.

        Args:
            attempt: Attempt number (0-indexed)

        Returns:
            Delay in seconds
        """
        if self.exponential:
            delay = self.base_delay * (2 ** attempt)
        else:
            delay = self.base_delay

        # Cap at max_delay
        delay = min(delay, self.max_delay)

        # Add jitter if enabled
        if self.jitter:
            delay = delay * (0.5 + random.random() * 0.5)

        return delay


def _should_retry(
    exception: Exception,
    config: RetryConfig,
    attempt: int
) -> bool:
    """
    Determine if an exception should trigger a retry.

    Args:
        exception: The exception that was raised
        config: Retry configuration
        attempt: Current attempt number (0-indexed)

    Returns:
        True if should retry, False otherwise
    """
    # Check if we've exceeded max retries
    if attempt >= config.max_retries:
        return False

    # Check if exception type is in retry list
    for exc_type in config.retry_on_exceptions:
        if isinstance(exception, exc_type):
            return True

    # Check for timeout errors
    if config.retry_on_timeout:
        # Check for common timeout error patterns
        error_msg = str(exception).lower()
        timeout_keywords = ['timeout', 'timed out', 'time out', 'deadline']
        if any(keyword in error_msg for keyword in timeout_keywords):
            return True

    # Check for rate limit errors (429)
    error_msg = str(exception).lower()
    rate_limit_keywords = ['429', 'too many requests', 'rate limit', 'rate_limit', 'ratelimit']
    if any(keyword in error_msg for keyword in rate_limit_keywords):
        return True

    return False


def retry_on_exception(
    config: Optional[RetryConfig] = None,
    **kwargs
) -> Callable:
    """
    Decorator to retry function on specific exceptions.

    Args:
        config: RetryConfig instance. If None, uses default config.
        **kwargs: Alternative way to pass config parameters (e.g., max_retries=3)

    Returns:
        Decorated function with retry logic

    Examples:
        >>> @retry_on_exception(max_retries=3, base_delay=1.0)
        >>> def risky_operation():
        ...     return api_call()

        >>> # Using custom config
        >>> config = RetryConfig(max_retries=5, exponential=False)
        >>> @retry_on_exception(config=config)
        >>> def another_operation():
        ...     return database_query()
    """
    if config is None:
        config = RetryConfig(**kwargs)
    elif kwargs:
        # Merge kwargs with config (kwargs take precedence)
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None

            for attempt in range(config.max_retries + 1):
                try:
                    if attempt > 0:
                        logger.info(
                            f"[Retry] {func.__name__} 重试第 {attempt} 次 "
                            f"(max_retries={config.max_retries})"
                        )
                    return func(*args, **kwargs)

                except Exception as e:
                    last_exception = e

                    if not _should_retry(e, config, attempt):
                        logger.error(
                            f"[Retry] {func.__name__} 失败，不再重试: {type(e).__name__}: {e}"
                        )
                        raise

                    # Calculate delay
                    delay = config.get_delay(attempt)
                    logger.warning(
                        f"[Retry] {func.__name__} 第 {attempt + 1} 次尝试失败: "
                        f"{type(e).__name__}: {e}。等待 {delay:.2f}s 后重试..."
                    )
                    time.sleep(delay)

            # Should not reach here, but just in case
            if last_exception:
                raise last_exception

        return wrapper
    return decorator


def retry_with_timeout(
    timeout: Optional[float] = None,
    config: Optional[RetryConfig] = None,
    **kwargs
) -> Callable:
    """
    Decorator to retry function with timeout support.

    This decorator combines timeout handling with retry logic. It's particularly
    useful for operations that may hang or take too long.

    Args:
        timeout: Timeout for each attempt in seconds. If None, uses config.timeout
        config: RetryConfig instance. If None, creates default config.
        **kwargs: Additional config parameters

    Returns:
        Decorated function with timeout and retry logic

    Examples:
        >>> @retry_with_timeout(timeout=60.0, max_retries=3)
        >>> def slow_api_call():
        ...     return external_api.request()

        >>> # Using custom config
        >>> config = RetryConfig(max_retries=5, timeout=120.0)
        >>> @retry_with_timeout(config=config)
        >>> def database_query():
        ...     return db.execute("SELECT * FROM large_table")
    """
    if config is None:
        # Set timeout in config if provided
        if timeout is not None:
            kwargs['timeout'] = timeout
        config = RetryConfig(**kwargs)
    elif timeout is not None:
        # Override config timeout
        config.timeout = timeout

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Check if function has a timeout parameter
            sig = inspect.signature(func)
            if 'timeout' in sig.parameters:
                # Pass timeout to function
                kwargs['timeout'] = config.timeout

            # Use retry_on_exception internally
            retry_decorator = retry_on_exception(config=config)
            return retry_decorator(func)(*args, **kwargs)

        return wrapper
    return decorator


class RetryContext:
    """
    Context manager for retrying operations.

    Useful for retrying blocks of code or operations that don't fit well
    with decorator pattern.

    Examples:
        >>> config = RetryConfig(max_retries=3, base_delay=1.0)
        >>> with RetryContext(config, operation_name="data_load"):
        ...     result = load_large_file()
    """

    def __init__(
        self,
        config: Optional[RetryConfig] = None,
        operation_name: str = "operation",
        **kwargs
    ):
        """
        Initialize retry context.

        Args:
            config: RetryConfig instance. If None, creates default config.
            operation_name: Name of the operation (for logging)
            **kwargs: Additional config parameters
        """
        if config is None:
            self.config = RetryConfig(**kwargs)
        else:
            self.config = config
        self.operation_name = operation_name
        self.attempt = 0

    def __enter__(self):
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Handle exceptions with retry logic."""
        if exc_type is None:
            return True  # No exception, success

        # Check if we should retry
        if not _should_retry(exc_val, self.config, self.attempt):
            logger.error(
                f"[Retry] {self.operation_name} 失败，不再重试: "
                f"{exc_type.__name__}: {exc_val}"
            )
            return False  # Re-raise exception

        # Calculate delay
        delay = self.config.get_delay(self.attempt)
        logger.warning(
            f"[Retry] {self.operation_name} 第 {self.attempt + 1} 次尝试失败: "
            f"{exc_type.__name__}: {exc_val}。等待 {delay:.2f}s 后重试..."
        )
        time.sleep(delay)

        # Increment attempt counter
        self.attempt += 1

        # Re-raise to allow retry
        return False

    def should_retry(self) -> bool:
        """
        Check if more retries are available.

        Returns:
            True if more retries are available
        """
        return self.attempt < self.config.max_retries


def async_retry_on_exception(
    config: Optional[RetryConfig] = None,
    **kwargs
) -> Callable:
    """
    Decorator for async functions to retry on specific exceptions.

    Args:
        config: RetryConfig instance. If None, uses default config.
        **kwargs: Alternative way to pass config parameters

    Returns:
        Decorated async function with retry logic

    Examples:
        >>> @async_retry_on_exception(max_retries=3)
        >>> async def async_api_call():
        ...     return await async_client.request()
    """
    import asyncio

    if config is None:
        config = RetryConfig(**kwargs)
    elif kwargs:
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_exception = None

            for attempt in range(config.max_retries + 1):
                try:
                    if attempt > 0:
                        logger.info(
                            f"[Retry] {func.__name__} 重试第 {attempt} 次 "
                            f"(max_retries={config.max_retries})"
                        )
                    return await func(*args, **kwargs)

                except Exception as e:
                    last_exception = e

                    if not _should_retry(e, config, attempt):
                        logger.error(
                            f"[Retry] {func.__name__} 失败，不再重试: "
                            f"{type(e).__name__}: {e}"
                        )
                        raise

                    # Calculate delay
                    delay = config.get_delay(attempt)
                    logger.warning(
                        f"[Retry] {func.__name__} 第 {attempt + 1} 次尝试失败: "
                        f"{type(e).__name__}: {e}。等待 {delay:.2f}s 后重试..."
                    )
                    await asyncio.sleep(delay)

            if last_exception:
                raise last_exception

        return wrapper
    return decorator


__all__ = [
    "RetryConfig",
    "retry_on_exception",
    "retry_with_timeout",
    "RetryContext",
    "async_retry_on_exception",
]
