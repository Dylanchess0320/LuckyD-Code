"""All custom exceptions for LuckyD Code.

Import from here — not from individual modules — to keep the exception
hierarchy in one place and avoid circular imports.
"""


class LuckyDCodeError(Exception):
    """Base class for all LuckyD Code errors."""


__all__ = [
    "LuckyDCodeError",
    "DeepSeekAPIError",
    "AuthenticationError",
    "RetryableError",
    "NonRetryableError",
    "ModelNotFoundError",
    "ContextLengthError",
    "ToolExecutionError",
]


# Backwards-compatible alias — kept so any code (or user scripts) that
# imported DeepSeekAPIError still works without modification.
DeepSeekAPIError = LuckyDCodeError


class AuthenticationError(LuckyDCodeError):
    """API key was rejected or is missing."""


class RetryableError(LuckyDCodeError):
    """Transient error that can be retried (rate limit, timeout, server error)."""


class NonRetryableError(LuckyDCodeError):
    """Permanent error that must NOT be retried (bad request, auth failure)."""


class ModelNotFoundError(NonRetryableError):
    """The requested model does not exist or is not available on this provider."""


class ContextLengthError(NonRetryableError):
    """Request exceeds the model's context-window limit."""


class ToolExecutionError(LuckyDCodeError):
    """A built-in tool raised an exception during execution."""
