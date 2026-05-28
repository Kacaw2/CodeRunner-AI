"""python -m mcp_gateway [--transport stdio|sse|streamable-http] [--port 8200]"""

import argparse
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("mcp_gateway")


def main():
    parser = argparse.ArgumentParser(description="CodeRunner MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8200)
    args = parser.parse_args()

    # ── Load .env ──
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # ── Init DB ──
    from core.config import get_settings
    from core.db.session import init_db

    settings = get_settings()
    init_db(settings.database_url)
    logger.info("Database connected")

    # ── Init rate limiter ──
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    from mcp_gateway.middleware.rate_limit import init_rate_limiter
    init_rate_limiter(redis_url)

    # ── Verify API Key ──
    raw_key = os.environ.get("MCP_API_KEY", "").strip()
    if raw_key:
        from mcp_gateway.middleware.auth import verify_api_key
        caller = verify_api_key(raw_key)
        if caller is None:
            logger.error("MCP_API_KEY is invalid or revoked — exiting")
            sys.exit(1)
        from mcp_gateway.middleware import set_caller_info
        set_caller_info(caller)
        logger.info(
            "Authenticated as user_id=%s role=%s",
            caller["user_id"],
            caller["role"],
        )
    else:
        logger.warning(
            "MCP_API_KEY not set — all tool calls will be rejected"
        )

    # ── Pre-warm knowledge base ──
    try:
        from knowledge.store import get_knowledge_base
        get_knowledge_base()
        logger.info("Knowledge base pre-loaded")
    except Exception as e:
        logger.warning("Knowledge base pre-load failed (non-fatal): %s", e)

    # ── Create & run server ──
    from mcp_gateway.server import create_mcp_server

    mcp = create_mcp_server()
    mcp.settings.host = args.host
    mcp.settings.port = args.port

    logger.info(
        "Starting MCP Server (transport=%s, host=%s, port=%d)",
        args.transport,
        args.host,
        args.port,
    )
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
