import asyncio
import logging
from functools import wraps
from typing import Awaitable, Callable, Optional, Tuple, Type, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


class RetryExhausted(Exception):
    """Raised when all retry attempts have been exhausted."""


async def async_retry(
    coro_factory: Callable[[], Awaitable[T]],
    max_attempts: int = 3,
    base_delay: float = 1.0,
    backoff: float = 2.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    operation_name: str = "operation",
) -> T:
    """Execute an async call with exponential backoff retry.

    Args:
        coro_factory: Async callable that returns the desired result.
        max_attempts: Maximum number of attempts (default 3).
        base_delay: Initial delay in seconds (default 1.0).
        backoff: Multiplier for each retry (default 2.0).
        retryable_exceptions: Tuple of exception types that trigger a retry.
        operation_name: Human-readable name for logging.

    Returns:
        The result of the successful coroutine call.

    Raises:
        RetryExhausted: After all attempts fail.
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await coro_factory()
        except retryable_exceptions as e:
            last_exc = e
            if attempt < max_attempts:
                delay = base_delay * (backoff ** (attempt - 1))
                logger.warning(
                    "%s attempt %d/%d failed: %s. Retrying in %.1fs...",
                    operation_name, attempt, max_attempts, e, delay
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "%s failed after %d attempts. Last error: %s",
                    operation_name, max_attempts, e
                )
    raise RetryExhausted(f"{operation_name} failed after {max_attempts} attempts") from last_exc


def retry_sync(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    backoff: float = 2.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """Decorator for sync functions with exponential backoff retry."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            import time
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exc = e
                    if attempt < max_attempts:
                        delay = base_delay * (backoff ** (attempt - 1))
                        logger.warning(
                            "%s attempt %d/%d failed: %s. Retrying in %.1fs...",
                            func.__name__, attempt, max_attempts, e, delay
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "%s failed after %d attempts. Last error: %s",
                            func.__name__, max_attempts, e
                        )
            raise RetryExhausted(f"{func.__name__} failed after {max_attempts} attempts") from last_exc
        return wrapper
    return decorator
