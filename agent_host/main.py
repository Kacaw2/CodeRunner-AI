"""FastAPI Agent Host — entry point.

Run with:
    python -m agent_host.main
or:
    uvicorn agent_host.main:app --host 0.0.0.0 --port 8100 --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_host.api import chat, workflows, traces
from agent_host.core.config import get_settings
from agent_host.core.db import get_engine
from agent_host.worker.redis_buffer import get_redis
from agent_host.worker.task_runner import shutdown as shutdown_workers

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

    get_engine()
    logger.info("Database engine created")

    r = get_redis()
    if r:
        logger.info("Redis connected")
    else:
        logger.warning("Redis unavailable — SSE buffering will be degraded")

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
    return {
        "status": "ok",
        "service": "agent-host",
        "redis": "connected" if r else "unavailable",
    }


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "agent_host.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
