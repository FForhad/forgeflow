import logging
import time
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)

# Global registry mapping task type names to callable functions
TASK_REGISTRY: Dict[str, Callable[[Dict[str, Any]], Any]] = {}


def register_task(task_type: str):
    """
    Decorator to register a function as a job task handler.
    """
    def decorator(fn: Callable[[Dict[str, Any]], Any]):
        TASK_REGISTRY[task_type] = fn
        return fn
    return decorator


def get_task_handler(task_type: str) -> Callable[[Dict[str, Any]], Any]:
    """
    Retrieves the handler for a given task type, raising KeyError if not found.
    """
    if task_type not in TASK_REGISTRY:
        raise KeyError(
            f"No handler registered for task type '{task_type}'. "
            f"Available types: {list(TASK_REGISTRY.keys())}"
        )
    return TASK_REGISTRY[task_type]


# -----------------------------------------------------------------------------
# BUILT-IN TASK HANDLERS
# -----------------------------------------------------------------------------

@register_task("echo")
def task_echo(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Simple echo task returning the received payload."""
    return {"status": "echoed", "data": payload}


@register_task("math_compute")
def task_math_compute(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Performs basic arithmetic operations.
    Payload: {"op": "add"|"subtract"|"multiply"|"divide"|"power", "a": 10, "b": 5}
    """
    op = payload.get("op", "add")
    a = float(payload.get("a", 0))
    b = float(payload.get("b", 0))

    if op == "add":
        res = a + b
    elif op == "subtract":
        res = a - b
    elif op == "multiply":
        res = a * b
    elif op == "divide":
        if b == 0:
            raise ZeroDivisionError("Cannot divide by zero in math_compute task.")
        res = a / b
    elif op == "power":
        res = a ** b
    else:
        raise ValueError(f"Unsupported math operation '{op}'")

    return {"op": op, "a": a, "b": b, "result": res}


@register_task("sleep_task")
def task_sleep(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Simulates a long-running task by sleeping for N seconds."""
    seconds = float(payload.get("seconds", 1.0))
    time.sleep(seconds)
    return {"slept_seconds": seconds, "status": "completed"}


@register_task("text_transform")
def task_text_transform(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Transforms input text (upper, lower, reverse, word_count)."""
    text = str(payload.get("text", ""))
    return {
        "original": text,
        "uppercase": text.upper(),
        "lowercase": text.lower(),
        "reversed": text[::-1],
        "word_count": len(text.split()),
        "char_count": len(text),
    }


@register_task("failing_task")
def task_failing(payload: Dict[str, Any]) -> None:
    """Intentionally raises an exception for testing error handling and failure tracing."""
    error_msg = payload.get("error_message", "Intentionally raised failure for testing.")
    raise RuntimeError(error_msg)


@register_task("flaky_service")
def task_flaky_service(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Simulates a flaky upstream dependency that fails N times before recovering.
    Payload: {"key": "test-flaky-1", "fail_times": 2}
    """
    from apps.core.redis_client import get_redis_client
    from apps.jobs.exceptions import ServiceUnavailableError

    key = payload.get("key", "default_flaky")
    fail_times = int(payload.get("fail_times", 2))
    redis_key = f"forgeflow:task:flaky:{key}"

    r = get_redis_client()
    attempts = r.incr(redis_key)

    if attempts <= fail_times:
        raise ServiceUnavailableError(
            f"HTTP 503 Upstream payment gateway unavailable (attempt #{attempts} of {fail_times})"
        )

    # Cleanup counter on success
    r.delete(redis_key)
    return {
        "status": "success",
        "recovered_after_attempts": attempts,
        "message": "Downstream payment processed successfully.",
    }


@register_task("permanent_fail")
def task_permanent_fail(payload: Dict[str, Any]) -> None:
    """
    Simulates a fatal non-retryable error (e.g. malformed payload).
    """
    from apps.jobs.exceptions import InvalidPayloadError
    raise InvalidPayloadError(
        payload.get("error_message", "Invalid payload: missing required 'customer_id' parameter.")
    )
