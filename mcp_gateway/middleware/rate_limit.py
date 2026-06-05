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
        # Atomic fixed-window counter: INCR is atomic (no GET-then-check TOCTOU),
        # and EXPIRE is set only on the first hit of the window so the 60s TTL is
        # NOT refreshed on every call (the old pipeline reset the window each
        # time, turning it into an unbounded sliding window).
        count = _redis_client.incr(key)
        if count == 1:
            _redis_client.expire(key, 60)
        return count <= rpm_limit
    except Exception as e:
        logger.warning("Rate limit check failed (allowing): %s", e)
        return True


def claim_jti(jti: str, ttl_seconds: int) -> bool:
    """Claim a capability token's ``jti`` exactly once.

    Returns True on first use, False if the jti was already claimed (replay).
    The claim is held for ``ttl_seconds`` (the token's remaining lifetime), after
    which the token itself is expired and the jti can be safely re-used.

    Fail-open when Redis is unavailable, consistent with ``check_rate_limit``:
    the token still has a short TTL bounding any replay window.
    """
    if _redis_client is None or not jti or ttl_seconds <= 0:
        return True
    try:
        # SET NX EX returns None when the key already exists (i.e. replay).
        ok = _redis_client.set(f"mcp_jti:{jti}", "1", nx=True, ex=ttl_seconds)
        return bool(ok)
    except Exception as e:
        logger.warning("jti replay check failed (allowing): %s", e)
        return True
