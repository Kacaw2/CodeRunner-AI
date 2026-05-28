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
        "workers.__main__:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
