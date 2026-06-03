"""FastAPI Agent Host — entry point.

Run with:
    python -m workers.__main__
or:
    uvicorn workers.__main__:app --host 0.0.0.0 --port 8100 --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.agents import chat, workflows, traces
from core.config import get_settings
from core.db.session import get_engine
from workers.redis_buffer import get_redis
from workers.task_runner import shutdown as shutdown_workers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    settings = get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Agent Host starting on %s:%s", settings.HOST, settings.PORT)

    # Optional OpenTelemetry tracing (F2) — no-op unless OTEL_ENABLED=true.
    try:
        from core.observability.otel import init_otel
        init_otel("coderunner-agent-host")
    except Exception:
        logger.debug("OTel init skipped", exc_info=True)

    engine = get_engine()
    logger.info("Database engine created")

    # Core-Base trace/eval tables have no Flask model and are not covered by the
    # Flask app's db.create_all(); create the missing ones here so trace.save()
    # and the eval pages work on any DB. Idempotent (checkfirst skips existing).
    try:
        import core.db.models.agent_trace  # noqa: F401  registers trace/eval tables
        from core.db.session import Base

        Base.metadata.create_all(engine)
        logger.info("Core trace/eval tables ensured")
    except Exception:
        logger.warning("Core trace/eval table creation skipped", exc_info=True)

    r = get_redis()
    if r:
        logger.info("Redis connected")
    else:
        logger.warning("Redis unavailable — SSE buffering will be degraded")

    # F6: warm up the knowledge base (loads the embedding model from the
    # offline cache) so the first RAG query isn't slow. Warn-only — a degraded
    # KB must not block startup; searches degrade to empty results.
    try:
        from knowledge.store import kb_health

        kb = kb_health()
        if kb.get("status") == "ok":
            logger.info("Knowledge base ready: %s", kb)
        else:
            logger.warning("Knowledge base degraded at startup: %s", kb.get("error"))
    except Exception:
        logger.warning("Knowledge base warm-up skipped", exc_info=True)

    yield

    # ── Shutdown ──
    logger.info("Agent Host shutting down")
    shutdown_workers()


app = FastAPI(
    title="CodeRunner Agent Host",
    version="0.1.0",
    description="FastAPI service for AI agent orchestration (Phase 1)",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(workflows.router)
app.include_router(traces.router)


@app.get("/api/health", tags=["system"])
def health():
    r = get_redis()
    from knowledge.store import kb_health

    kb = kb_health()
    return {
        "status": "ok",
        "service": "agent-host",
        "redis": "connected" if r else "unavailable",
        "knowledge_base": kb.get("status", "unknown"),
    }


@app.get("/live", tags=["system"])
def live():
    """Liveness probe — process is up, no dependency checks."""
    return {"status": "alive", "service": "agent-host"}


@app.get("/metrics", tags=["system"])
def metrics():
    """Prometheus metrics for the agent-host process (F2)."""
    from fastapi import Response

    from core.observability.metrics import metrics_response

    body, status_code, content_type = metrics_response()
    return Response(content=body, status_code=status_code, media_type=content_type)


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "workers.__main__:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
