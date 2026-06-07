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

    # ── Register all ORM models ──
    # The gateway runs outside the Flask app factory. Import the shared domain
    # mappings directly, plus the still-unmigrated non-agent business mappings
    # referenced by User relationships, then configure mappers eagerly.
    import domain.models  # noqa: F401
    import app.models  # noqa: F401
    from sqlalchemy.orm import configure_mappers
    configure_mappers()
    logger.info("ORM models registered")

    from core.db.session import get_session
    from ai.mcp_gateway.bootstrap import bootstrap_tool_runtime
    bootstrap_tool_runtime(session_factory=get_session)
    logger.info("ToolRuntime bootstrapped")

    # ── Init rate limiter ──
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    from ai.mcp_gateway.middleware.rate_limit import init_rate_limiter
    init_rate_limiter(redis_url)

    # ── Authentication mode ──
    # Production default: per-request bearer-token auth (resolved inside the
    # gateway middleware for every call). The startup MCP_API_KEY may set a
    # process-wide fallback identity ONLY in local-development stdio mode.
    dev_startup = os.environ.get(
        "MCP_ALLOW_STARTUP_KEY_DEV_MODE", "false"
    ).strip().lower() in ("1", "true", "yes")

    if dev_startup:
        if args.transport != "stdio":
            logger.error(
                "MCP_ALLOW_STARTUP_KEY_DEV_MODE is for local stdio development "
                "only; refusing to use a process-wide startup key on "
                "transport=%s. Use per-request bearer auth instead.",
                args.transport,
            )
            sys.exit(1)

        raw_key = os.environ.get("MCP_API_KEY", "").strip()
        if not raw_key:
            logger.warning(
                "DEV MODE active but MCP_API_KEY not set — calls without "
                "per-request auth will be rejected"
            )
        else:
            from ai.mcp_gateway.middleware.auth import verify_api_key
            caller = verify_api_key(raw_key)
            if caller is None:
                logger.error("MCP_API_KEY is invalid or revoked — exiting")
                sys.exit(1)
            from ai.mcp_gateway.middleware import set_caller_info
            set_caller_info(caller)
            logger.warning(
                "DEV MODE: startup MCP_API_KEY fallback identity active "
                "(user_id=%s role=%s). NOT FOR PRODUCTION.",
                caller["user_id"],
                caller["role"],
            )
    else:
        logger.info(
            "Production auth mode: per-request bearer-token authentication "
            "required for every tool call"
        )

    # Knowledge base loads lazily on first knowledge tool call. Pre-warming here
    # would block the embedding-model download before the gateway binds its
    # port, leaving the service unhealthy and stalling dependents.

    # ── Create & run server ──
    from ai.mcp_gateway.server import create_mcp_server

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
