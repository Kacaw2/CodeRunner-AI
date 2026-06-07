"""Health endpoints for the agent runtime.

``/health/live`` is a cheap liveness probe (process is up). ``/health/ready``
checks DB + Redis reachability and degrades gracefully (returns 503 with
per-check detail) so it is safe to call in tests where neither is available.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text

from agent_runtime.dependencies import get_redis, get_session
from agent_runtime.schemas import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse(status="ok", checks={"process": "ok"})


@router.get("/ready", response_model=HealthResponse)
async def ready(
    response: Response,
    session=Depends(get_session),
    redis_client=Depends(get_redis),
) -> HealthResponse:
    checks: dict[str, str] = {}

    try:
        await session.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:  # pragma: no cover - infra dependent
        checks["db"] = f"error: {exc.__class__.__name__}"

    if redis_client is None:
        checks["redis"] = "unavailable"
    else:
        try:
            redis_client.ping()
            checks["redis"] = "ok"
        except Exception as exc:  # pragma: no cover
            checks["redis"] = f"error: {exc.__class__.__name__}"

    healthy = checks.get("db") == "ok"
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="ok" if healthy else "degraded", checks=checks)
