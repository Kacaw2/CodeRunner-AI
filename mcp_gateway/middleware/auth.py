"""API Key verification for MCP Server."""

import hashlib
import logging

from core.db.session import get_session
from mcp_gateway.scopes import normalize_scopes

logger = logging.getLogger(__name__)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def verify_api_key(raw_key: str) -> dict | None:
    """Verify an API key and return caller info, or None if invalid."""
    from core.db.models.mcp_api_key import McpApiKey
    from app.core.timezone import now_china

    key_hash = hash_api_key(raw_key)
    session = get_session()
    try:
        key = (
            session.query(McpApiKey)
            .filter_by(key_hash=key_hash, revoked_at=None)
            .first()
        )
        if not key:
            return None
        key.last_used_at = now_china()
        session.commit()
        return {
            "api_key_id": key.id,
            "user_id": key.user_id,
            "role": key.role,
            "scopes": normalize_scopes(key.scopes),
            "rate_limit_rpm": key.rate_limit_rpm,
        }
    except Exception:
        session.rollback()
        logger.exception("API key verification failed")
        return None
    finally:
        session.close()
