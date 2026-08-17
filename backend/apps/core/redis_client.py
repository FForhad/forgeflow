import logging
import redis
from django.conf import settings

logger = logging.getLogger(__name__)

_redis_client = None


def get_redis_client(decode_responses=True) -> redis.Redis:
    """
    Returns a configured Redis client instance using Django settings.
    """
    global _redis_client
    if _redis_client is None:
        redis_url = getattr(settings, "REDIS_URL", "redis://127.0.0.1:6379/0")
        _redis_client = redis.Redis.from_url(
            redis_url,
            decode_responses=decode_responses,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
        )
    return _redis_client


def check_redis_connection() -> bool:
    """
    Pings Redis to verify connectivity. Returns True if connected, False otherwise.
    """
    try:
        client = get_redis_client()
        return client.ping()
    except Exception as exc:
        logger.warning(f"Redis health check failed: {exc}")
        return False
