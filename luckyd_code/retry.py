"""Retry logic with exponential backoff for API calls."""

import time
import random
from functools import wraps
from collections.abc import Callable
from typing import Any

from .exceptions import RetryableError, NonRetryableError, ModelNotFoundError
from .log import get_logger

__all__ = ["with_retry", "RetryableError", "NonRetryableError", "ModelNotFoundError"]


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: bool = True,
) -> Callable[..., Any]:
    """Decorator that retries a function on retryable errors with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts (default 3)
        base_delay: Initial delay in seconds (default 1.0)
        max_delay: Maximum delay in seconds (default 30.0)
        jitter: Add random jitter to delay (default True)
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            delay = base_delay
            logger = get_logger()

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except RetryableError as e:
                    last_exception = e
                    if attempt < max_retries:
                        actual_delay = delay
                        if jitter:
                            actual_delay = delay * (0.5 + random.random() * 0.5)
                        logger.warning("Attempt %d failed, retrying in %.1fs...", attempt + 1, actual_delay)
                        time.sleep(actual_delay)
                        delay = min(delay * 2, max_delay)
                except (NonRetryableError, ModelNotFoundError) as e:
                    raise e
                except Exception:
                    # Unclassified errors - retry once on the first attempt, then give up
                    if attempt == 0:
                        actual_delay = delay * (0.5 + random.random() * 0.5)
                        logger.warning("Transient error, retrying in %.1fs...", actual_delay)
                        time.sleep(actual_delay)
                    else:
                        raise

            raise last_exception or RuntimeError("Max retries exceeded")
        return wrapper
    return decorator
