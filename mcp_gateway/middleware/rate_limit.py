"""Per-key rate limiting for MCP Server using Redis."""

import logging
import time

logger = logging.getLogger(__name__)

_redis_client = None


def init_rate_limiter(redis_url: str):
    global _redis_client
    try:
        import redis
        _redis_client = redis.from_url(redis_url, decode_responses=True)
        _redis_client.ping()
        logger.info("Rate limiter connected to Redis")
    except Exception as e:
        _redis_client = None
        logger.warning("Rate limiter disabled (Redis unavailable): %s", e)


def check_rate_limit(api_key_id: str, rpm_limit: int) -> bool:
    """Return True if the request is within limits, False if rate limited."""
    if _redis_client is None or rpm_limit <= 0:
        return True

    key = f"mcp_rate:{api_key_id}"
    try:
        current = _redis_client.get(key)
        if current is not None and int(current) >= rpm_limit:
            return False
        pipe = _redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60)
        pipe.execute()
        return True
    except Exception as e:
        logger.warning("Rate limit check failed (allowing): %s", e)
        return True
