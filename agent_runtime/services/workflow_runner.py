"""Remote workflow execution using async claims and the existing sync kernel."""

from __future__ import annotations

import asyncio
import json
import logging

from graph.engine import WorkflowEngine

from domain.repositories.workflows import (
    AsyncWorkflowRepository,
    SyncWorkflowRepository,
)

logger = logging.getLogger(__name__)

_STATUS_KEY = "workflow:{run_id}:status"
_BUFFER_KEY = "workflow:{run_id}:buffer"
_TTL = 3600


class WorkflowRedisWriter:
    def __init__(self, redis_client) -> None:
        self.redis = redis_client

    def set_status(self, run_id: str, status: str) -> None:
        if not self.redis:
            return
        try:
            self.redis.set(_STATUS_KEY.format(run_id=run_id), status, ex=_TTL)
        except Exception as exc:  # pragma: no cover - optional infra
            logger.warning("Redis workflow status write failed: %s", exc)

    def push_event(self, run_id: str, event: dict) -> None:
        if not self.redis:
            return
        try:
            key = _BUFFER_KEY.format(run_id=run_id)
            self.redis.rpush(key, json.dumps(event, ensure_ascii=False))
            self.redis.expire(key, _TTL)
        except Exception as exc:  # pragma: no cover
            logger.warning("Redis workflow event write failed: %s", exc)

    def read_status(self, run_id: str) -> str | None:
        if not self.redis:
            return None
        try:
            return self.redis.get(_STATUS_KEY.format(run_id=run_id))
        except Exception:  # pragma: no cover
            return None

    def read_events(self, run_id: str, start: int = 0) -> list[dict]:
        if not self.redis:
            return []
        try:
            raw = self.redis.lrange(_BUFFER_KEY.format(run_id=run_id), start, -1)
            return [json.loads(item) for item in raw]
        except Exception:  # pragma: no cover
            return []


class AsyncWorkflowRunner:
    """Claim with AsyncSession, then run the sync workflow kernel off-loop."""

    def __init__(self, session, redis_client=None) -> None:
        self.session = session
        self.repo = AsyncWorkflowRepository(session)
        self.sse = WorkflowRedisWriter(redis_client)

    @staticmethod
    def _execute_sync(run_id: str, user_role: str) -> tuple[dict, list[dict]]:
        from core.db.session import db_session

        with db_session() as session:
            repo = SyncWorkflowRepository(session)
            run = repo.get_run(run_id)
            if not run:
                return {"status": "not_found"}, []
            engine = WorkflowEngine(repository=repo)
            state = engine.execute(
                plan=run.plan_json or {"goal": run.goal, "steps": []},
                user_id=run.user_id,
                user_role=user_role,
                conversation_id=run.conversation_id,
                chat_task_id=run.chat_task_id,
                workflow_run_id=run.id,
            )
            return state, list(engine.events)

    async def run(self, run_id: str) -> dict:
        run = await self.repo.get_run(run_id)
        if not run:
            return {"claimed": False, "status": "not_found"}

        if not await self.repo.transition_run(
            run_id,
            "planning",
            "executing",
            completed_at=None,
            error_detail=None,
        ):
            return {"claimed": False, "status": run.status}
        await self.session.commit()
        self.sse.set_status(run_id, "executing")
        self.sse.push_event(
            run_id, {"type": "workflow_start", "workflow_id": run_id}
        )

        try:
            from domain.repositories.users import AsyncUserRepository

            user = await AsyncUserRepository(self.session).get_by_id(run.user_id)
            user_role = (
                user.role.value
                if user and hasattr(user.role, "value")
                else (str(user.role) if user else "teacher")
            )
            state, events = await asyncio.to_thread(
                self._execute_sync, run_id, user_role
            )
            for event in events:
                self.sse.push_event(run_id, event)

            final_status = state.get("status", "failed")
            values = {}
            if final_status == "completed":
                values["result"] = state.get("final_result")
            elif final_status == "failed":
                values["error_detail"] = state.get("error", "Workflow failed")

            await self.repo.transition_run(
                run_id,
                ("executing", final_status),
                final_status,
                **values,
            )
            await self.session.commit()

            if final_status == "completed":
                self.sse.push_event(
                    run_id, {"type": "workflow_done", "workflow_id": run_id}
                )
            elif final_status == "failed":
                self.sse.push_event(
                    run_id,
                    {
                        "type": "workflow_error",
                        "workflow_id": run_id,
                        "message": values["error_detail"],
                    },
                )
            elif final_status == "waiting_approval":
                self.sse.push_event(
                    run_id,
                    {
                        "type": "workflow_waiting_approval",
                        "workflow_id": run_id,
                    },
                )
            self.sse.set_status(run_id, final_status)
            return {"claimed": True, "status": final_status}
        except Exception as exc:  # noqa: BLE001 - runtime boundary
            await self.session.rollback()
            logger.exception("WorkflowRun %s failed (remote)", run_id)
            await self.repo.transition_run(
                run_id,
                ("planning", "executing", "failed"),
                "failed",
                error_detail=str(exc)[:500],
            )
            await self.session.commit()
            self.sse.push_event(
                run_id,
                {
                    "type": "workflow_error",
                    "workflow_id": run_id,
                    "message": str(exc),
                },
            )
            self.sse.set_status(run_id, "failed")
            return {"claimed": True, "status": "failed"}
