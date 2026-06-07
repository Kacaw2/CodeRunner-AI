# Dual-ORM Collapse onto Flask `db.Model` — Delete the FastAPI Agent Host

> **Status: archived / partially superseded (2026-06-06).**
>
> - **Phase 1 remains valid and completed** in commit `f1f0a9f`: the old
>   FastAPI Agent Host, proxy branches, worker service, and seven duplicate
>   business-table mappings were removed.
> - **The original Phase 2 is cancelled.** Do not move trace/eval/MCP and every
>   headless process into a Flask application context, and do not delete the
>   runtime-neutral session capability in favor of a Flask-only ORM.
> - The replacement route is
>   [`2026-06-06-shared-sqlalchemy-domain-fastapi-agent-runtime-plan.md`](2026-06-06-shared-sqlalchemy-domain-fastapi-agent-runtime-plan.md):
>   one shared SQLAlchemy 2.0 model graph, process-local sync/async sessions,
>   and a newly designed FastAPI Agent Runtime.

**Status:** Phase 1 completed; Phase 2 superseded
**Phase 1:** completed 2026-06-06
**Created:** 2026-06-06
**Owner:** (assign)

## Goal

CodeRunner-AI currently runs **two ORM registries against one MySQL database**:

1. **Flask-SQLAlchemy** (`app/core/extensions.py:db`, models in `app/models/*`) — the web app.
2. **Runtime-neutral plain SQLAlchemy** (`core/db/session.py:Base` + its own engine, models in `core/db/models/*`) — used by a **separate FastAPI "Agent Host" OS process**, the MCP Gateway process, and the eval/trace stack.

Seven tables are **mapped twice** (once in each registry). That duplication is a standing correctness hazard (schema drift, mapper-registry collisions, `DetachedInstanceError`). It is guarded today only by a brittle drift test (`tests/test_dual_mapping_consistency.py`).

This plan removes the duplication in two phases:

- **Phase 1** — Delete the FastAPI Agent Host process entirely and collapse the **7 dual-mapped tables** onto Flask `db.Model` as their single ORM. The chat path already has a complete Flask twin, so chat-folding is mostly *deletion*. The workflow path has **no Flask twin** and must be *authored* (one Flask worker + one set of Flask blueprint routes). After this phase the only remaining users of `core.db.session.Base` are the trace/eval/mcp stack.
- **Phase 2** — Port the remaining runtime-neutral trace/eval/mcp models onto Flask `db.Model`, wrap the context-free writers (`core/observability/*`, `evals/*`) in a Flask app context, reconcile the MCP Gateway and eval-CI processes onto a Flask app context, and finally **delete `core/db/session.py`'s `Base` + engine** (or reduce it to a thin app-context-bound shim).

## Architecture (current → target)

```
CURRENT
  ┌─ Flask web (gunicorn run:app :9900) ── Flask-SQLAlchemy db ── engine A
  ├─ FastAPI Agent Host (uvicorn workers.__main__:app :8100) ── core Base ── engine B
  ├─ MCP Gateway (python -m mcp_gateway :8200) ── app.models + core.get_session ── engine B
  └─ eval CI (python -m evals.ci) ── core Base ── engine B

TARGET (after Phase 2)
  ┌─ Flask web (gunicorn run:app :9900) ── Flask-SQLAlchemy db ── engine A
  ├─ MCP Gateway (python -m mcp_gateway :8200) ── Flask app context ── engine A
  └─ eval CI (python -m evals.ci) ── Flask app context ── engine A
  (core/db/session.py Base+engine deleted)
```

## Tech Stack

- Python 3.11, Flask + Flask-SQLAlchemy + Flask-Migrate (Alembic), Flask-Smorest.
- FastAPI + uvicorn + sse-starlette (the stack being **deleted** in Phase 1).
- Redis (SSE event buffer), MySQL 8 (prod), SQLite in-memory (tests).
- Background work runs in a `ThreadPoolExecutor`, **not** an event loop (verified — no real async deps).
- LangChain message types for agent streaming.

---

## Verified current state (read before trusting the map)

Every claim below was confirmed by opening the file on 2026-06-06. **Corrections to the original exploration are called out in bold.**

### The two processes
- **Flask web app**: `bp = Blueprint("ai", __name__, url_prefix="/api/v1/ai")` (`app/api/v1/ai.py:15`), registered at `app/__init__.py:195-196`. Flask-SQLAlchemy `db` from `app/core/extensions.py:17`.
- **FastAPI Agent Host**: `app = FastAPI(...)` at `workers/__main__.py:83`; `uvicorn.run("workers.__main__:app", ...)` at `workers/__main__.py:138-143`; `docker/Dockerfile.workers:56` runs `uvicorn workers.__main__:app --port 8100`. Routers mounted at `workers/__main__.py:98-100` (`chat.router`, `workflows.router`, `traces.router`). Genuinely separate OS process; `traces.py` HTTP-proxies back to Flask via `app/services/agent_client.py`.
- **`compose.yaml`** defines BOTH a `workers` service (FastAPI Agent Host, port 8100, `workers/__main__.py:135-143`, `compose.yaml:185-249`) AND an `mcp_gateway` service (`compose.yaml:251-300`, entrypoint `python -m mcp_gateway`). They **share `docker/Dockerfile.workers`**. The `web` service sets `AGENT_HOST_URL: http://workers:8100` and `USE_AGENT_HOST_PROXY: ${USE_AGENT_HOST_PROXY:-true}` (`compose.yaml:101-102`).

### Async reality
- Only 2 async handlers exist: `chat.py:149-191` and `workflows.py:164-210`, both `await asyncio.sleep(...)` poll loops. No `httpx.AsyncClient`, no async LLM SDK, no `asyncio.create_task`, no `BackgroundTasks`. Heavy work runs in `ThreadPoolExecutor` (`workers/task_runner.py:31-39`), using the **sync** `db_session()` from `core/db/session.py:69`. **The async tier carries no real concurrency; deleting it loses nothing.**

### Chat already has a Flask twin (folding chat ≈ deletion)
- Flask async-chat routes exist in `app/api/v1/ai.py`: `POST /chat/async` (`:548`, submits via `workers.chat.submit_chat_task(task.id, current_app._get_current_object())` at `:615-616`), `GET /chat/task/<id>/stream` SSE (`:635-637`, `stream_with_context` + `mimetype="text/event-stream"` at `:696-697`), `GET /chat/task/<id>` status (`:708`), `POST /chat/stream` (`:390`).
- `workers/chat.py` is the Flask sync twin of `workers/task_runner.py`: same Redis buffer pattern but `with app.app_context():` (`:107`) + `db.session` (`:121`) + `app.models.*` imports (`:108-109`).
- **`POST /chat/async` (`ai.py:585-591`) and the status/stream routes call `is_proxy_enabled()` and, when `USE_AGENT_HOST_PROXY=true`, forward to the Agent Host via `app/api/v1/ai_proxy.py`.** Because Phase 1 deletes the Agent Host, **the proxy branches and `app/api/v1/ai_proxy.py` itself must be removed** (otherwise prod with the default `USE_AGENT_HOST_PROXY=true` would 503).

### Workflows have NO Flask twin (the one real authoring task)
- `workers/` contains only `chat.py` (Flask) — **there is no `workers/workflow*.py` Flask worker.** Workflow execution + SSE exist ONLY on the FastAPI side (`workers/task_runner.py:318-441`, `app/api/v1/agents/workflows.py`).
- `app/models/workflow.py` already has the full Flask `WorkflowRun` (`:7`, `to_dict()` at `:44`) and `WorkflowStep` (`:65`, `to_dict()` at `:105`) models, plus a `WorkflowApproval` model (`:129`). `WorkflowRun` exposes `plan_json`, `result`, `status`, `started_at`, `completed_at`, and a `steps` relationship (`lazy="dynamic"`).
- `graph/engine.py:WorkflowEngine` takes a `session=` kwarg (used at `task_runner.py:363`) and **does not import `core.db` at all** — it operates on whatever session is passed. So it works with `db.session` unchanged. `graph/supervisor.py:SupervisorAgent` likewise takes `session=`.
- **CORRECTION:** the original map listed `graph/engine.py` as a Phase-1 neutral consumer. It is **not** — it imports no `core.db` symbol. Removed from the Phase-1 rewire list.

### The 7 dual-mapped core classes (delete in Phase 1)
| Table | Core class (delete) | File:line | Flask authority |
|---|---|---|---|
| `users` | `User` | `core/db/models/agent_user.py:9` | `app/models/user.py:User` (full; core is id+role subset) |
| `ai_conversations` | `AIConversation` | `core/db/models/ai_conversation.py:21` | `app/models/ai_conversation.py:AIConversation` |
| `ai_messages` | `AIMessage` | `core/db/models/ai_conversation.py:42` | `app/models/ai_conversation.py:AIMessage` |
| `chat_tasks` | `ChatTask` | `core/db/models/chat_task.py:22` | `app/models/chat_task.py:ChatTask` |
| `workflow_runs` | `WorkflowRun` | `core/db/models/workflow.py:22` | `app/models/workflow.py:WorkflowRun` |
| `workflow_steps` | `WorkflowStep` | `core/db/models/workflow.py:83` | `app/models/workflow.py:WorkflowStep` |
| `eval_runs` | `EvalRun` | `core/db/models/agent_trace.py:141` (tablename `:150`) | `app/models/eval_run.py:EvalRun` |

`core/db/models/agent_trace.py` ALSO defines the trace family (`AgentTraceRun:43`, `AgentTraceSpan:79`, `AgentTraceEvent:102`, `AgentTraceArtifact:113`, `AgentTraceLink:129`) and `EvalCaseRun:163`, `EvalCaseGraderResult:186`. **Those are Phase-2 tables — only `EvalRun` is removed from this file in Phase 1.**

### Who reads/writes the 7 tables (Phase-1 rewire surface)
- **Agent Host (delete wholesale):** `workers/__main__.py`, `workers/task_runner.py`, `app/api/v1/agents/{chat,workflows,traces}.py`, `app/api/v1/agents/__init__.py` (empty), `app/services/agent_client.py`, `app/api/v1/ai_proxy.py`.
- **CORRECTION — `app/api/v1/ai.py` needs NO Phase-1 model rewire.** Verified: the eval WRITE at `ai.py:1887-1899` already uses `app.models.eval_run.EvalRun`; eval history at `ai.py:1970-1974` uses Flask. The ONLY `core.db` import in `ai.py` is at `ai.py:2001-2002` (`from core.db.session import db_session` + `from core.db.models.agent_trace import EvalCaseRun, EvalCaseGraderResult`) — those are **Phase-2** tables. `ai.py`'s Phase-1 change is limited to deleting the *proxy* branches.
- **CORRECTION — `app/services/trace_query_service.py` needs NO Phase-1 rewire.** Verified: it READS `core.db.models.agent_trace.AgentTrace*` (all Phase-2 tables) via `db.session.execute(select(...))`. It never touches the 7 tables. Phase-2 concern only.
- **`app/api/v1/mcp_keys.py:13`** imports `core.db.models.mcp_api_key.McpApiKey`; **`app/api/v1/mcp_approvals.py:8`** imports `core.db.models.mcp_approval.McpToolApproval`. Those `mcp_*` model files use Flask `db.Column` (they are registered on the Flask `db` registry at `extensions.py:70-71`), so they are **already Flask models living in the wrong folder** — Phase-2 relocation, not Phase-1.

### Migration / guardrail facts
- Alembic baseline `migrations/versions/e21895a59f7d_baseline_full_schema.py` exists (`down_revision=None`). **The 7 tables' SCHEMA does not change** — only which Python class maps them — so **Phase 1 needs NO new Alembic migration.**
- `core/db/metadata.py:build_target_metadata()` (`:29`) merges Flask metadata + core-only tables for Alembic autogenerate, deduping shared names with Flask winning (`:39-41`). After Phase 1 the 7 tables come only from Flask metadata; the dedup loop still works but the comment is stale.
- `tests/test_combined_metadata.py` asserts the 7 shared names appear once and core-only trace tables appear (still valid after Phase 1 — trace tables stay on core Base until Phase 2).
- `tests/test_dual_mapping_consistency.py` becomes **obsolete** the moment the 7 core classes are deleted (its `SHARED_TABLES` list is exactly those 7). **Delete it in the same commit that removes the last core duplicate.**
- `tests/conftest.py:21-45` builds BOTH registries onto one in-memory SQLite engine: `_db.create_all()` then points `core_session._engine`/`_SessionLocal` at `_db.engine` and runs `core_session.Base.metadata.create_all()`. After Phase 1 the 7 tables come from Flask `_db.create_all()`; the core `Base` still carries the trace/eval tables, so the conftest dual-bind **must stay** until Phase 2. The teardown loop (`conftest.py:59-62`) clears both registries' tables — leave it.

---

## Phase 1 — Delete the FastAPI Agent Host; collapse the 7 tables onto Flask

> Order rationale: deletion before the workflow twin exists would leave a feature gap. So **author the workflow Flask worker + routes first (T1, T2)**, prove them green, *then* delete the FastAPI path (T4), *then* remove the now-dead core classes (T5), *then* fix tests (T6). T3 (remove proxy branches) is independent and small.

### T1 — Author `workers/workflow.py` (Flask workflow worker) — TDD

Model it on `workers/chat.py` (app-context + `db.session` + `app.models.*`) and on the FastAPI `_run_workflow` logic in `workers/task_runner.py:323-406`. The engine/supervisor calls are session-agnostic and reused verbatim.

**T1.1 — Write the failing test first.**

Create `tests/test_workflow_worker.py`:

```python
"""workers/workflow.py runs a WorkflowRun to completion inside a Flask app
context, mirroring workers/chat.py. The Supervisor/engine layer is mocked so
the test exercises the worker's lifecycle + persistence, not the LLM."""

from unittest.mock import patch

from app.core.extensions import db
from app.models.workflow import WorkflowRun


def _make_run(user_id: int) -> str:
    run = WorkflowRun(
        user_id=user_id,
        goal="Generate a binary-search problem",
        workflow_type="general",
        status="planning",
        plan_json={"goal": "g", "steps": []},
        total_steps=0,
    )
    db.session.add(run)
    db.session.commit()
    return run.id


def test_worker_marks_run_completed(app, db_session, teacher_user):
    run_id = _make_run(teacher_user.id)

    fake_state = {"status": "completed", "final_result": {"ok": True}, "_events": [
        {"type": "workflow_start", "workflow_id": run_id},
    ]}

    from workers import workflow as wf

    # SupervisorAgent.run_workflow is called when plan has no steps.
    with patch("graph.supervisor.SupervisorAgent") as MockSup:
        MockSup.return_value.run_workflow.return_value = fake_state
        wf._run_workflow(run_id, app._get_current_object(), "g", None)

    run = db.session.get(WorkflowRun, run_id)
    assert run.status == "completed"
    assert run.result == {"ok": True}
    assert run.started_at is not None
    assert run.completed_at is not None


def test_worker_marks_run_failed_on_exception(app, db_session, teacher_user):
    run_id = _make_run(teacher_user.id)

    from workers import workflow as wf

    with patch("graph.supervisor.SupervisorAgent") as MockSup:
        MockSup.return_value.run_workflow.side_effect = RuntimeError("boom")
        wf._run_workflow(run_id, app._get_current_object(), "g", None)

    run = db.session.get(WorkflowRun, run_id)
    assert run.status == "failed"
    assert "boom" in (run.error_detail or "")
```

Run it — it MUST fail with `ModuleNotFoundError: No module named 'workers.workflow'`:

```bash
cd C:/Users/libie/Desktop/program/CodeRunner-AI
python -m pytest tests/test_workflow_worker.py -q
```
Expected: `ERROR ... No module named 'workers.workflow'` (collection error).

**T1.2 — Implement `workers/workflow.py`.**

Create `workers/workflow.py`:

```python
"""Async workflow worker: runs multi-step workflows in a background thread pool.

Flask twin of the deleted FastAPI workers/task_runner.py workflow path. Uses a
Flask app context + db.session + app.models.workflow, and streams SSE events
through the shared workers.redis_buffer (wf_* keys) so the Flask
/api/v1/ai/workflows/<id>/stream route can replay them.

Redis keys per run (TTL = workers.redis_buffer._ttl()):
  workflow:{run_id}:status  ->  "planning" | "executing" | "completed" | "failed" | "waiting_approval"
  workflow:{run_id}:buffer  ->  List of SSE event JSON strings
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from app.core.extensions import db
from app.core.timezone import now_china
from workers import redis_buffer

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="workflow-worker")


# ── Public API ───────────────────────────────────────────────

def submit_workflow(run_id: str, app, goal: str, context: dict | None = None):
    """Submit a workflow run to the thread pool for async execution."""
    _executor.submit(_run_workflow, run_id, app, goal, context)


# ── Worker logic ─────────────────────────────────────────────

def _run_workflow(run_id: str, app, goal: str, context: dict | None = None):
    """Execute a workflow run inside a Flask app context."""
    with app.app_context():
        from app.models.workflow import WorkflowRun

        run = db.session.get(WorkflowRun, run_id)
        if not run:
            logger.error("WorkflowRun %s not found", run_id)
            return

        run.status = "executing"
        run.started_at = now_china()
        db.session.commit()

        redis_buffer.wf_set_status(run_id, "executing")
        redis_buffer.wf_push_event(run_id, {
            "type": "workflow_start",
            "workflow_id": run_id,
        })

        try:
            from app.models.user import User
            user = db.session.get(User, run.user_id)
            user_role = (user.role.value
                         if user and hasattr(user.role, "value")
                         else str(user.role) if user else "teacher")

            # Configure the agent MCP client (transport or in-process), matching
            # the deleted FastAPI worker. In-process binds a session-scoped runtime.
            from mcp_gateway.client import (
                configure_mcp_client_from_env,
                InProcessMCPToolClient,
            )
            mcp_client = configure_mcp_client_from_env()
            if isinstance(mcp_client, InProcessMCPToolClient):
                from mcp_gateway.bootstrap import bootstrap_tool_runtime
                bootstrap_tool_runtime(session_factory=lambda: db.session)

            try:
                plan = run.plan_json if isinstance(run.plan_json, dict) else None
                if plan and plan.get("steps"):
                    from graph.engine import WorkflowEngine
                    state = WorkflowEngine(session=db.session).execute(
                        plan=plan,
                        user_id=run.user_id,
                        user_role=user_role,
                        conversation_id=run.conversation_id,
                        chat_task_id=run.chat_task_id,
                        workflow_run_id=run_id,
                    )
                else:
                    from graph.supervisor import SupervisorAgent
                    supervisor = SupervisorAgent(session=db.session)
                    state = supervisor.run_workflow(
                        user_id=run.user_id,
                        user_role=user_role,
                        goal=goal,
                        context=context,
                        conversation_id=run.conversation_id,
                        chat_task_id=run.chat_task_id,
                        workflow_run_id=run_id,
                    )

                for evt in state.get("_events", []):
                    redis_buffer.wf_push_event(run_id, evt)

                final_status = state.get("status", "completed")
                if final_status == "completed":
                    _complete_workflow(run_id, result=state.get("final_result"))
                elif final_status == "waiting_approval":
                    redis_buffer.wf_set_status(run_id, "waiting_approval")
                    redis_buffer.wf_push_event(run_id, {
                        "type": "workflow_waiting_approval",
                        "workflow_id": run_id,
                    })
                else:
                    _fail_workflow(run_id, state.get("error", "Workflow failed"))
            finally:
                from tools.protocol.runtime import reset_tool_runtime
                reset_tool_runtime()

        except Exception as e:
            db.session.rollback()
            logger.exception("WorkflowRun %s failed", run_id)
            _fail_workflow(run_id, str(e)[:500])


def _complete_workflow(run_id: str, result: dict | None = None):
    from app.models.workflow import WorkflowRun
    run = db.session.get(WorkflowRun, run_id)
    if run:
        run.status = "completed"
        run.completed_at = now_china()
        if result:
            run.result = result
        db.session.commit()
    redis_buffer.wf_push_event(run_id, {"type": "workflow_done", "workflow_id": run_id})
    redis_buffer.wf_set_status(run_id, "completed")


def _fail_workflow(run_id: str, error: str = "Unknown error"):
    from app.models.workflow import WorkflowRun
    db.session.rollback()
    run = db.session.get(WorkflowRun, run_id)
    if run:
        run.status = "failed"
        run.error_detail = error
        run.completed_at = now_china()
        db.session.commit()
    redis_buffer.wf_push_event(run_id, {"type": "workflow_error", "message": error})
    redis_buffer.wf_set_status(run_id, "failed")
```

> Note: `redis_buffer.wf_*` helpers (`workers/redis_buffer.py:140-157`) already exist and are process-shared, so the Flask SSE route can replay them. `app.core.timezone.now_china` is the Flask convention (used in `workers/chat.py:20`).

Run the test — it MUST pass:

```bash
python -m pytest tests/test_workflow_worker.py -q
```
Expected: `2 passed`.

**Commit:** `feat(workers): add Flask workflow worker (twin of deleted FastAPI path)`

### T2 — Author Flask workflow routes + SSE on the `ai` blueprint — TDD

The `agent_client` URLs already imply the target paths: `POST /api/v1/ai/workflows`, `GET /api/v1/ai/workflows/<id>` (`agent_client.py:116,134`). Add list + stream too, modeled on the chat routes in `ai.py:548-703`.

**T2.1 — Write the failing test first.**

Create `tests/test_workflow_routes.py`:

```python
"""Flask /api/v1/ai/workflows routes: create returns 202 + workflow_id, get
returns the run dict, stream is an SSE response. The worker submit is patched
so no real agent runs."""

import json
from unittest.mock import patch

from app.core.extensions import db
from app.models.workflow import WorkflowRun


def test_create_workflow_returns_202(client, mock_auth_teacher):
    with patch("workers.workflow.submit_workflow") as submit:
        resp = client.post(
            "/api/v1/ai/workflows",
            json={"goal": "Generate a problem", "workflow_type": "general"},
        )
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["workflow_id"]
    assert body["status"] == "planning"
    submit.assert_called_once()
    run = db.session.get(WorkflowRun, body["workflow_id"])
    assert run is not None
    assert run.goal == "Generate a problem"


def test_create_workflow_requires_goal(client, mock_auth_teacher):
    resp = client.post("/api/v1/ai/workflows", json={"goal": "   "})
    assert resp.status_code == 400


def test_get_workflow_returns_run(client, mock_auth_teacher):
    run = WorkflowRun(user_id=1, goal="g", workflow_type="general", status="completed")
    # owner must match the patched teacher user id
    from app.auth.decorators import get_current_user_or_401  # noqa: F401
    run.user_id = mock_auth_teacher.id
    db.session.add(run)
    db.session.commit()

    resp = client.get(f"/api/v1/ai/workflows/{run.id}")
    assert resp.status_code == 200
    assert resp.get_json()["id"] == run.id


def test_get_missing_workflow_404(client, mock_auth_teacher):
    resp = client.get("/api/v1/ai/workflows/does-not-exist")
    assert resp.status_code == 404


def test_stream_workflow_is_sse(client, mock_auth_teacher):
    run = WorkflowRun(user_id=mock_auth_teacher.id, goal="g",
                      workflow_type="general", status="completed")
    db.session.add(run)
    db.session.commit()

    # redis is unavailable in tests -> buffer reads return [] and status None,
    # so the generator should emit [DONE] quickly after draining nothing.
    resp = client.get(f"/api/v1/ai/workflows/{run.id}/stream")
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"
```

Run it — MUST fail with 404s (routes don't exist yet):

```bash
python -m pytest tests/test_workflow_routes.py -q
```
Expected: failures (`404 != 202`, etc.).

**T2.2 — Implement the routes.** Append to `app/api/v1/ai.py` (same `bp`, after the chat routes block, before the eval routes). Reuse the existing helpers `get_current_user_or_401`, `require_auth`, `_error_response`, `stream_with_context`, `time`, `json`, `current_app` already imported at the top of `ai.py` (`:5-6`).

```python
# ── Workflows: POST /api/v1/ai/workflows  (async run) ─────────

@bp.route("/workflows", methods=["POST"])
@require_auth
def workflow_create():
    """Create a workflow run and submit it for background execution. 202."""
    user = get_current_user_or_401()
    data = request.get_json(silent=True) or {}

    goal = (data.get("goal") or "").strip()
    if not goal:
        return _error_response("invalid_request", "goal is required", 400)

    from app.models.workflow import WorkflowRun, WorkflowStep

    steps = data.get("steps") or []
    try:
        run = WorkflowRun(
            user_id=user.id,
            conversation_id=data.get("conversation_id"),
            goal=goal,
            workflow_type=data.get("workflow_type", "general"),
            status="planning",
            max_steps=data.get("max_steps", 10),
            timeout_seconds=data.get("timeout_seconds", 300),
            total_steps=len(steps),
        )
        db.session.add(run)
        db.session.flush()

        plan_steps = []
        for idx, s in enumerate(steps):
            step = WorkflowStep(
                workflow_run_id=run.id,
                step_index=idx,
                step_type=s.get("step_type", "agent_call"),
                agent_type=s.get("agent_type"),
                instruction=s.get("instruction", ""),
                risk_level=s.get("risk_level", "low"),
                requires_approval=s.get("requires_approval", False),
                depends_on=s.get("depends_on"),
                status="pending",
            )
            db.session.add(step)
            plan_steps.append({
                "step_index": idx,
                "step_type": step.step_type,
                "agent_type": step.agent_type,
                "instruction": step.instruction,
                "risk_level": step.risk_level,
                "requires_approval": step.requires_approval,
            })

        run.plan_json = {"goal": goal, "steps": plan_steps}
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to create workflow run")
        return _error_response("ai_service_error", "Failed to create workflow.", 500)

    wf_context = {
        "language": data.get("language", "python"),
        "difficulty": data.get("difficulty", "medium"),
        "topic": data.get("topic", ""),
    }
    from workers.workflow import submit_workflow
    submit_workflow(run.id, current_app._get_current_object(), goal, wf_context)

    return jsonify({"workflow_id": run.id, "status": run.status}), 202


# ── Workflows: GET /api/v1/ai/workflows  (list) ───────────────

@bp.route("/workflows", methods=["GET"])
@require_auth
def workflow_list():
    user = get_current_user_or_401()
    from app.models.workflow import WorkflowRun

    status = request.args.get("status")
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))

    query = WorkflowRun.query.filter_by(user_id=user.id)
    if status:
        query = query.filter_by(status=status)
    total = query.count()
    runs = (query.order_by(WorkflowRun.created_at.desc())
            .offset(offset).limit(limit).all())
    return jsonify({"total": total, "workflows": [r.to_dict() for r in runs]})


# ── Workflows: GET /api/v1/ai/workflows/<id>  (status) ────────

@bp.route("/workflows/<run_id>", methods=["GET"])
@require_auth
def workflow_get(run_id):
    user = get_current_user_or_401()
    from app.models.workflow import WorkflowRun
    run = WorkflowRun.query.filter_by(id=run_id, user_id=user.id).first()
    if not run:
        return _error_response("not_found", "Workflow not found", 404)
    return jsonify(run.to_dict())


# ── Workflows: GET /api/v1/ai/workflows/<id>/stream  (SSE) ────

@bp.route("/workflows/<run_id>/stream", methods=["GET"])
@require_auth
def workflow_stream(run_id):
    user = get_current_user_or_401()
    from app.models.workflow import WorkflowRun
    run = WorkflowRun.query.filter_by(id=run_id, user_id=user.id).first()
    if not run:
        return _error_response("not_found", "Workflow not found", 404)

    last_event = request.args.get("last_event", 0, type=int)

    def generate():
        from workers import redis_buffer
        cursor = last_event
        idle = 0
        max_idle = 600  # ~5 min at 0.5s
        while idle < max_idle:
            events = redis_buffer.wf_get_events(run_id, start=cursor)
            if events:
                idle = 0
                for evt in events:
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                    cursor += 1
                    if evt.get("type") in ("workflow_done", "workflow_error"):
                        yield "data: [DONE]\n\n"
                        return
            else:
                status = redis_buffer.wf_get_status(run_id)
                if status in ("completed", "failed"):
                    for evt in redis_buffer.wf_get_events(run_id, start=cursor):
                        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                yield ": heartbeat\n\n"
                idle += 1
                time.sleep(0.5)
        yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
```

> The `mock_auth_teacher` fixture (`conftest.py:104`) patches `get_current_user_or_401`, so `user.id` resolves to the teacher's id. The `test_stream_workflow_is_sse` test relies on Redis being unavailable in CI (`conftest.py` points `REDIS_URL` at a non-running db 15); `wf_get_events`/`wf_get_status` then return `[]`/`None` (see the try/except in `redis_buffer.py:89-108,68-75`) so the generator emits `[DONE]` immediately.

Run the tests — MUST pass:

```bash
python -m pytest tests/test_workflow_routes.py tests/test_workflow_worker.py -q
```
Expected: `7 passed`.

**Commit:** `feat(ai): add Flask workflow create/list/get/stream routes`

### T3 — Remove the Agent-Host proxy branches from the chat path

The proxy forwards to the Agent Host, which T4 deletes. Make the Flask chat path the only path.

Files + exact edits:
- `app/api/v1/ai.py`:
  - In `chat_async` (`:548`), delete the import + branch at `:555` and `:585-591`:
    - remove `from app.api.v1.ai_proxy import is_proxy_enabled, proxy_chat_create`
    - remove the entire `if is_proxy_enabled(): ... return proxy_chat_create(...)` block.
  - In `chat_task_stream` (`:635`), delete `:639-641` (`from app.api.v1.ai_proxy import is_proxy_enabled, proxy_chat_stream` + `if is_proxy_enabled(): return proxy_chat_stream(task_id)`).
  - In `chat_task_status` (`:708`), delete `:712-714` (`from app.api.v1.ai_proxy import is_proxy_enabled, proxy_chat_status` + `if is_proxy_enabled(): return proxy_chat_status(task_id)`).
- Delete the file `app/api/v1/ai_proxy.py` entirely.
- `compose.yaml`: in the `web` service env, delete `AGENT_HOST_URL: http://workers:8100` and `USE_AGENT_HOST_PROXY: ${USE_AGENT_HOST_PROXY:-true}` (`:101-102`).

Verify no remaining references:

```bash
python - <<'PY'
import subprocess, sys
hits = subprocess.run(["git","grep","-n","-E","ai_proxy|USE_AGENT_HOST_PROXY|is_proxy_enabled"],
                      capture_output=True, text=True).stdout
print(hits or "(clean)")
sys.exit(1 if hits.strip() else 0)
PY
```
Expected: `(clean)` and exit 0.

Run the chat tests to confirm the non-proxy path still works:

```bash
python -m pytest tests/ -q -k "chat or async" 
```
Expected: pass (no proxy-dependent failures).

**Commit:** `refactor(ai): drop Agent-Host proxy; Flask serves chat directly`

### T4 — Delete the FastAPI Agent Host process

> **This is the irreversible-ish step. Do not start it until T1 + T2 + T3 are committed and green.**

Delete these files:
- `workers/__main__.py` (FastAPI app + uvicorn entry)
- `workers/task_runner.py` (FastAPI ThreadPool worker — chat + workflow)
- `app/api/v1/agents/chat.py`
- `app/api/v1/agents/workflows.py`
- `app/api/v1/agents/traces.py`
- `app/api/v1/agents/__init__.py` (and the now-empty `app/api/v1/agents/` directory)
- `app/services/agent_client.py` (HTTP adapter back into Flask — only the deleted routers used it)
- `docker/Dockerfile.workers` **only if** no other service uses it. **It is shared by `mcp_gateway` (`compose.yaml:254`)** — so do NOT delete the Dockerfile; instead **rename its purpose**: edit `docker/Dockerfile.workers:1` comment and `docker/Dockerfile.workers:56` `CMD` to a no-op/MCP-appropriate default, since the `workers` compose service is being removed.

`compose.yaml` edits:
- Delete the entire `workers:` service block (`:185-249`).
- In `mcp_gateway` (`:251-300`), nothing references the `workers` service; leave it. It already overrides `entrypoint:` so the base `CMD` is irrelevant. (Recommended: change `docker/Dockerfile.workers` `CMD` to `["python", "-m", "mcp_gateway"]` so a bare run of the image does something sane.)
- In `workers/__main__.py`-dependent health/launch refs: none outside the deleted service.

Check `requirements.txt` for now-unused deps — but DO NOT remove yet if anything else imports them. `sse_starlette` and `fastapi`/`uvicorn` were used ONLY by the Agent Host (`mcp_gateway` uses `mcp`'s own server, not FastAPI). Grep to confirm before removing:

```bash
python - <<'PY'
import subprocess
for mod in ("fastapi","uvicorn","sse_starlette"):
    out = subprocess.run(["git","grep","-l",mod],capture_output=True,text=True).stdout
    print(mod, "->", out.replace("\n"," ") or "(no imports)")
PY
```
If a module shows only deleted files / `requirements.txt`, remove its line from `requirements.txt`. If it appears in a kept file, leave it. (Document the decision in the commit message.)

Verify nothing imports the deleted modules:

```bash
python - <<'PY'
import subprocess, sys
hits = subprocess.run(["git","grep","-n","-E",
  r"workers\.__main__|workers\.task_runner|app\.api\.v1\.agents|app\.services\.agent_client"],
  capture_output=True, text=True).stdout
print(hits or "(clean)")
sys.exit(1 if hits.strip() else 0)
PY
```
Expected: `(clean)`, exit 0. (If tests reference these, fix in T6.)

**Commit:** `feat(arch)!: delete FastAPI Agent Host process (chat+workflow now Flask-native)`

### T5 — Delete the 7 dual-mapped core classes + the drift guard

Edit / delete:
- Delete file `core/db/models/agent_user.py` (the whole `User` class is the only content).
- Delete file `core/db/models/ai_conversation.py` (both `AIConversation` + `AIMessage`).
- Delete file `core/db/models/chat_task.py` (`ChatTask`).
- Delete file `core/db/models/workflow.py` (both `WorkflowRun` + `WorkflowStep`).
- Edit `core/db/models/agent_trace.py`: delete the `EvalRun` class (`:141-160`) and its import-time docstring reference. **Keep** `AgentTraceRun/Span/Event/Artifact/Link`, `EvalCaseRun`, `EvalCaseGraderResult` (Phase 2).
- **Delete `tests/test_dual_mapping_consistency.py`** in this same commit (its `SHARED_TABLES` are exactly the 7 just removed; it can no longer import them).

Update `core/db/metadata.py`: the dedup loop (`:36-41`) still works (Flask now owns the 7 names and the core registry no longer declares them). Refresh the stale module docstring (`:1-10`) and the inline comment at `:5-7` to say only trace/eval tables remain core-exclusive. No logic change required.

Verify the 7 classes are gone from the core registry and nothing imports them:

```bash
python - <<'PY'
import subprocess, sys
hits = subprocess.run(["git","grep","-n","-E",
  r"core\.db\.models\.(agent_user|ai_conversation|chat_task|workflow)\b|core\.db\.models\.agent_trace import[^\\n]*\\bEvalRun\\b"],
  capture_output=True, text=True).stdout
print(hits or "(clean)")
sys.exit(1 if hits.strip() else 0)
PY
```
Expected: `(clean)`. If hits remain in tests, fix them in T6 (they may legitimately still appear there until T6 runs — in that case, sequence T5 and T6 in one working session and only assert clean after T6).

Confirm `build_target_metadata()` still yields each of the 7 names exactly once:

```bash
python -m pytest tests/test_combined_metadata.py -q
```
Expected: `3 passed`.

**Commit:** `feat(db)!: delete 7 dual-mapped core classes; Flask db.Model is sole ORM`

### T6 — Repair the test suite; full green

`tests/conftest.py`: **leave the dual-bind in place** (`:31-45`) — the core `Base` still carries the trace/eval tables (Phase 2). `core.db.models.agent_trace` still imports cleanly (it lost only `EvalRun`).

Find and fix every test that imported a now-deleted core class or the deleted Agent-Host modules:

```bash
python - <<'PY'
import subprocess
pat = (r"core\.db\.models\.(agent_user|ai_conversation|chat_task|workflow)|"
       r"from core\.db\.models\.agent_trace import[^\n]*EvalRun|"
       r"workers\.task_runner|app\.api\.v1\.agents|app\.services\.agent_client")
print(subprocess.run(["git","grep","-n","-E",pat,"tests/"],
                     capture_output=True,text=True).stdout or "(no test hits)")
PY
```

For each hit, repoint the import to the Flask twin:
- `core.db.models.ai_conversation` → `app.models.ai_conversation`
- `core.db.models.chat_task` → `app.models.chat_task`
- `core.db.models.workflow` → `app.models.workflow`
- `core.db.models.agent_user.User` → `app.models.user.User`
- `core.db.models.agent_trace import EvalRun` → `app.models.eval_run import EvalRun`
- any reference to deleted Agent-Host modules → delete the test or rewrite against the Flask route/worker.

Likely-affected files (verify): `tests/test_workflow_trace_binding.py`, `tests/test_workflow_*`, `tests/test_trace_*` (trace tables unchanged — these should be unaffected unless they also imported `EvalRun` from core). Most trace tests use `core.db.models.agent_trace.AgentTrace*`, which are untouched.

Run the full suite:

```bash
python -m pytest -q
```
Expected: all green. Investigate any `DetachedInstanceError` or `Mapper failed to initialize` — those signal a missed app-context wrap or a stale core import (see Risks).

**Commit:** `test: repoint suite off deleted dual-mapped core classes`

### Phase 1 acceptance criteria

**Completion evidence (2026-06-06):** Phase 1 implementation is complete. The
runtime-code/config/test grep for deleted Agent Host, proxy and dual-mapped core
symbols is clean; `tests/test_workflow_worker.py`, `tests/test_workflow_routes.py`,
`tests/test_combined_metadata.py` and the full suite are green. No migration file
was added or modified (`git diff --name-only -- migrations` is empty). A local
`flask db check` was attempted but the testing SQLite target database was not
upgraded, so it stopped with `Target database is not up to date`.

- [ ] `workers/workflow.py` exists; `tests/test_workflow_worker.py` green.
- [ ] `POST/GET /api/v1/ai/workflows[...]` routes serve create/list/get/stream; `tests/test_workflow_routes.py` green.
- [ ] No `git grep` hits for `ai_proxy`, `USE_AGENT_HOST_PROXY`, `is_proxy_enabled`.
- [ ] `workers/__main__.py`, `workers/task_runner.py`, `app/api/v1/agents/*`, `app/services/agent_client.py`, `app/api/v1/ai_proxy.py` deleted; no imports of them remain.
- [ ] `compose.yaml` `workers:` service removed; `web` env has no `AGENT_HOST_URL`/`USE_AGENT_HOST_PROXY`.
- [ ] The 7 core classes deleted; `core/db/models/` no longer declares `users`/`ai_conversations`/`ai_messages`/`chat_tasks`/`workflow_runs`/`workflow_steps`/`eval_runs`.
- [ ] `tests/test_dual_mapping_consistency.py` deleted.
- [ ] `tests/test_combined_metadata.py` green (7 shared names present once; trace tables still present).
- [ ] No new Alembic migration was created (schema unchanged) — confirmed by `alembic check` / autogenerate producing an empty diff (run `flask db migrate -m _probe` in a scratch DB, confirm "No changes", then discard).
- [ ] `python -m pytest -q` fully green.

---

## Phase 2 — Port trace/eval/mcp onto Flask; delete `core/db/session.py` Base+engine

After Phase 1, the ONLY users of `core.db.session.Base` are: the trace/eval models (`core/db/models/agent_trace.py`), `core/observability/trace_store.py` (`db_session` writer), `core/observability/audit.py`, the `evals/*` stack, the MCP Gateway process, and the eval-CI process. The `mcp_*` model files are physically under `core/db/models/` but already use Flask `db.Column`.

### T7 — Relocate the already-Flask `mcp_*` models for honesty

`core/db/models/mcp_api_key.py`, `mcp_audit_log.py`, `mcp_approval.py` already subclass Flask `db.Model` (registered at `extensions.py:70-71`). Move them to `app/models/`:
- `git mv core/db/models/mcp_api_key.py app/models/mcp_api_key.py` (likewise audit_log, approval).
- Repoint imports: `app/core/extensions.py:70-71`, `app/api/v1/mcp_keys.py:13`, `app/api/v1/mcp_approvals.py:8`, `mcp_gateway/middleware/auth.py`, and any test (`tests/test_mcp_gateway*.py`). Grep:
  ```bash
  git grep -n "core.db.models.mcp_"
  ```
  Repoint each to `app.models.mcp_*`. No schema change (Alembic diff stays empty).

**Commit:** `refactor(models): move Flask mcp_* models into app/models`

### T8 — Port trace/eval models onto Flask `db.Model`

Rewrite `core/db/models/agent_trace.py`'s 7 remaining classes (`AgentTraceRun/Span/Event/Artifact/Link`, `EvalCaseRun`, `EvalCaseGraderResult`) from plain `Base` + `Column` to Flask `db.Model` + `db.Column`, then move the file to `app/models/agent_trace_complete.py` (avoid clobbering the existing `app/models/agent_trace.py` which holds the legacy `AgentRun`/`AgentRunStep`). Register it in `app/core/extensions.py`'s model-import block.

This is a mechanical `Column(` → `db.Column(`, `String` → `db.String`, etc. rewrite. **Schema must stay byte-identical** to the Alembic-owned definition — diff the column set before/after. Keep the `_now_china`/`_uuid` defaults (Flask uses the same `app.core.timezone.now_china`; swap to it for consistency).

Update readers `app/services/trace_query_service.py:22-28` to import from the new `app.models.agent_trace_complete`.

**TDD:** `tests/test_trace_store_runtime_neutral.py` and `tests/test_trace_schema_contract.py` already exercise these tables; run them after the rewrite — they become the acceptance gate.

**Commit:** `feat(db): port trace/eval models onto Flask db.Model`

### T9 — Wrap context-free writers in an app context

`core/observability/trace_store.py` uses `with db_session() as session:` (`:21,44`). It explicitly must NOT import `app.core.extensions.db` (per its docstring). Replace the writer with a Flask-app-context-bound session that callers already have:
- Workers (`workers/chat.py`, `workers/workflow.py`) already run inside `app.app_context()` — so `TraceStore.save_run` can use `db.session` directly when a context is active.
- For callers with no context (`evals/ci.py`, `evals/harness/eval_harness.py`, `evals/reports/generator.py`, `evals/datasets/store.py`, `core/observability/audit.py`), wrap the call site in `with create_app(...).app_context():` or accept an injected session.

Concretely: change `TraceStore` to use `db.session` and require an active app context; update the `evals/*` entry points and `core/observability/audit.py` to push a Flask app context (build a singleton app via `app.create_app`). Repoint `ai.py:2001-2002` (`eval_case_by_trace`) to query `db.session` against the relocated models instead of `core.db.session.db_session`.

**TDD gate:** `tests/test_eval_harness_trace_binding.py`, `tests/test_agent_harness_trace_binding.py`, `tests/test_eval_report_generator.py`, `tests/test_trace_*`.

**Commit:** `refactor(observability): write traces through Flask db.session in app context`

### T10 — Reconcile the MCP Gateway + eval CI onto a Flask app context

- `mcp_gateway/__main__.py:34-60`: replace `init_db(settings.database_url)` + `get_session` with a Flask app: `from app import create_app; app = create_app(...)`; bootstrap the tool runtime with `session_factory=lambda: db.session` inside a pushed app context. The gateway already imports `app.models.*` and calls `configure_mappers()` (`:49-55`) — that block becomes redundant once `create_app()` runs the factory, so simplify it. Verify `mcp_gateway/bootstrap.py` and `mcp_gateway/middleware/auth.py` no longer import `core.db.session`.
- `evals/ci.py`: the harness mode (`--use-harness`) persists through the trace store; wrap its run in an app context and drop `--db-url`/`--bootstrap-schema` plumbing that pointed at the standalone engine (or repoint `--db-url` to configure the Flask `SQLALCHEMY_DATABASE_URI`).

**TDD gate:** `tests/test_mcp_gateway.py`, `tests/test_gateway_bootstrap_import.py`, `tests/test_evals_ci.py`.

**Commit:** `refactor(mcp,evals): run gateway + eval CI inside a Flask app context`

### T11 — Delete `core/db/session.py` Base + engine

Once nothing imports `Base`, `get_engine`, `get_session`, `get_db`, `db_session`, `init_db`, `get_session_factory` from `core.db.session`:

```bash
git grep -n -E "core\.db\.session|from core\.db import session"
```
Expected: only `core/db/metadata.py` (which no longer needs the core import — its loop becomes Flask-only) and possibly `tests/conftest.py:34-42` (the dual-bind, now removable).

- Simplify `core/db/metadata.py:build_target_metadata()` to return `db.metadata` directly (Flask now owns every table). Update `tests/test_combined_metadata.py` accordingly (the "core-only tables" assertions become "trace tables present in Flask metadata").
- Remove the core dual-bind from `tests/conftest.py:34-42` and the core-table teardown at `:59-60` (Flask `create_all`/`drop_all` now covers everything). Keep the Flask teardown (`:61-62`).
- Delete `core/db/session.py`. If `core/db/__init__.py` re-exports from it, clean that too.

**TDD gate:** `python -m pytest -q` fully green; `migrations/env.py` (uses `build_target_metadata`) still autogenerates an empty diff against a migrated DB.

**Commit:** `feat(db)!: remove runtime-neutral Base+engine; single ORM remains`

### Phase 2 acceptance criteria

- [ ] `mcp_*` models live under `app/models/`; no `core.db.models.mcp_*` imports remain.
- [ ] Trace/eval models are Flask `db.Model`; `tests/test_trace_schema_contract.py` green.
- [ ] No code imports `core.db.session` (verified by `git grep`).
- [ ] `core/db/session.py` deleted; `core/db/metadata.py` returns Flask metadata only.
- [ ] MCP Gateway and `evals.ci` run inside a Flask app context (no standalone engine).
- [ ] Alembic autogenerate against a migrated DB yields an empty diff (no schema drift introduced).
- [ ] `python -m pytest -q` fully green.

---

## Risks & Mitigations

1. **Mapper-registry collision / `DetachedInstanceError` in threadpool workers (the real one).** The whole point of the dual ORM was to let workers write without triggering Flask mapper configuration. Collapsing onto `db.Model` means worker threads MUST run inside `with app.app_context():` (as `workers/chat.py:107` already does and `workers/workflow.py` does in T1). A write outside a context, or a model instance accessed after its session closed, raises `DetachedInstanceError` or `Mapper failed to initialize`. *Mitigation:* every worker entry point opens an app context for its whole body; commit before yielding objects across thread boundaries; the T1/T2 tests assert end-to-end persistence so a missed context fails loudly.
2. **Prod default `USE_AGENT_HOST_PROXY=true`.** If T4 (delete Agent Host) ships before T3 (remove proxy), prod chat 503s. *Mitigation:* T3 precedes T4 and removes both the branches and the env var; acceptance gate greps for residue.
3. **Shared Dockerfile.** `docker/Dockerfile.workers` is used by BOTH the deleted `workers` service and the kept `mcp_gateway`. *Mitigation:* T4 keeps the file, deletes only the compose service, and retargets the base `CMD`.
4. **Hidden schema drift.** The collapse must not alter any table. *Mitigation:* no Alembic migration is authored in Phase 1; an autogenerate "no changes" probe is an explicit acceptance item in both phases.
5. **Rollback.** Each task is a separate commit. T1–T3 and T6 are reversible. **T4 (FastAPI deletion) is the irreversible-ish gate** — do not start it until T1+T2+T3 are committed and green; if a regression appears post-T4, `git revert` the T4 commit restores the Agent Host (it depends only on still-present `core.db` code until T5).
6. **`requirements.txt` over-pruning.** Removing `fastapi`/`uvicorn`/`sse_starlette` could break an unseen importer. *Mitigation:* T4 greps for each module's importers and only prunes lines with zero kept-file references.

## What this plan does NOT do

- Does **not** change any table schema, add columns, or write a new Alembic migration for the dedup (schema is identical; only the mapping Python class changes).
- Does **not** introduce async I/O — the deleted async tier carried no real concurrency; all work stays sync in `ThreadPoolExecutor` + Flask app context.
- Does **not** touch the executor (`docker/Dockerfile.executor`, port 8300) or Chroma/Redis services.
- Does **not** migrate the legacy `agent_runs`/`agent_run_steps` tables (`app/models/agent_trace.py`) or change the trace API's read shape.
- Phase 2 does **not** merge the legacy `AgentRun` model with the new `AgentTraceRun` model — they remain distinct tables with a read-only fallback.
