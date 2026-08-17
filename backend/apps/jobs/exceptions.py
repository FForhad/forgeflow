"""
Exception hierarchy for ForgeFlow Job Processing.
Distinguishes between transient/recoverable errors (Retryable) and permanent failures (Non-Retryable).
"""


class JobExecutionError(Exception):
    """Base class for all job execution exceptions."""
    pass


class RetryableJobError(JobExecutionError):
    """
    Exception indicating a transient, recoverable failure.
    Triggers exponential backoff and a delayed retry attempt.
    """
    pass


class NonRetryableJobError(JobExecutionError):
    """
    Exception indicating a fatal, permanent failure.
    Immediately fails the job without consuming retry attempts.
    """
    pass


# Concrete Retryable Exceptions
class NetworkTimeoutError(RetryableJobError):
    """External API or service connection timed out."""
    pass


class DatabaseTemporaryLockError(RetryableJobError):
    """Database row lock contention or temporary connection saturation."""
    pass


class RateLimitExceededError(RetryableJobError):
    """Downstream service returned HTTP 429 Too Many Requests."""
    pass


class ServiceUnavailableError(RetryableJobError):
    """Downstream service returned HTTP 502 / 503 / 504."""
    pass


# Concrete Non-Retryable Exceptions
class InvalidPayloadError(NonRetryableJobError):
    """Job payload is malformed or missing required parameters."""
    pass


class ResourceNotFoundError(NonRetryableJobError):
    """Referenced database entity or remote file does not exist."""
    pass


class PermissionDeniedTaskError(NonRetryableJobError):
    """Authentication or authorization permanently failed."""
    pass


# Standard permanent Python exceptions that should never be retried
PERMANENT_EXCEPTION_TYPES = (
    NonRetryableJobError,
    KeyError,
    TypeError,
    ValueError,
    ZeroDivisionError,
    AttributeError,
    IndexError,
    NotImplementedError,
)

TRANSIENT_EXCEPTION_TYPES = (
    RetryableJobError,
    TimeoutError,
    ConnectionError,
    ConnectionResetError,
    ConnectionRefusedError,
)


def is_retryable_exception(exc: Exception) -> bool:
    """
    Determines whether a raised exception should trigger a retry attempt.
    """
    if isinstance(exc, PERMANENT_EXCEPTION_TYPES):
        return False
    if isinstance(exc, TRANSIENT_EXCEPTION_TYPES):
        return True
    # For general unclassified errors (e.g. generic RuntimeError), check if marked as non-retryable
    return True
