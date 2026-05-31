"""Background task runner for the FastAPI Agent Host.

Direct agent execution — no HTTP delegation to Flask.
The runner manages ChatTask lifecycle, streams events into Redis buffer,
and persists final status to the database.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from core.config import get_settings
from core.db.session import db_session
from core.db.models.ai_conversation import AIConversation, AIMessage
from core.db.models.chat_task import ChatTask
from core.db.models.agent_user import User
from core.db.models.workflow import WorkflowRun
from workers import redis_buffer

logger = logging.getLogger(__name__)

_CHINA_TZ = timezone(timedelta(hours=8))

_executor: ThreadPoolExecutor | None = None


def _now() -> datetime:
    return datetime.now(_CHINA_TZ).replace(tzinfo=None)


def get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        settings = get_settings()
        _executor = ThreadPoolExecutor(
            max_workers=settings.WORKER_MAX_THREADS,
            thread_name_prefix="agent-worker",
        )
    return _executor


def shutdown():
    global _executor
    if _executor:
        _executor.shutdown(wait=False)
        _executor = None


# ── Chat task ──────────────────────────────────────────────────

def submit_chat_task(task_id: str, jwt_token: str, message: str):
    """Submit a chat task for background execution."""
    get_executor().submit(_run_chat_task, task_id, jwt_token, message)


def _run_chat_task(task_id: str, jwt_token: str, message: str):
    """Execute a chat task by directly invoking agents."""
    try:
        with db_session() as session:
            task = session.get(ChatTask, task_id)
            if not task:
                logger.error("ChatTask %s not found", task_id)
                return

            task.status = "processing"
            task.started_at = _now()
            session.flush()

            redis_buffer.ct_set_status(task_id, "processing")

            # Load context
            conv = session.get(AIConversation, task.conversation_id) if task.conversation_id else None
            user_msg = session.get(AIMessage, task.user_message_id) if task.user_message_id else None
            if user_msg:
                message = user_msg.content

            user = session.get(User, task.user_id)
            user_role = user.role if user else "student"

            # Load conversation history
            from langchain_core.messages import HumanMessage, AIMessage as LCAIMessage

            history = []
            if task.conversation_id:
                rows = (
                    session.query(AIMessage)
                    .filter_by(conversation_id=task.conversation_id)
                    .order_by(AIMessage.id)
                    .all()
                )
                current_msg_id = user_msg.id if user_msg else None
                for r in rows:
                    if r.id == current_msg_id:
                        break
                    if r.role == "user":
                        history.append(HumanMessage(content=r.content))
                    elif r.role == "assistant":
                        history.append(LCAIMessage(content=r.content))

            context = {"conversation_id": task.conversation_id}

            # Configure the agent MCP client (transport or in-process).
            # The transport client runs tools in the mcp_gateway process and
            # needs no local runtime; the in-process client still binds a
            # session-scoped ToolRuntime for local/dev execution.
            from mcp_gateway.client import (
                configure_mcp_client_from_env,
                InProcessMCPToolClient,
            )
            mcp_client = configure_mcp_client_from_env()
            if isinstance(mcp_client, InProcessMCPToolClient):
                from mcp_gateway.bootstrap import bootstrap_tool_runtime
                bootstrap_tool_runtime(session_factory=lambda: session)

            try:
                # ── Try Supervisor workflow first ──
                from graph.supervisor import SupervisorAgent

                supervisor = SupervisorAgent(session=session)
                wf_result = supervisor.invoke_from_chat(
                    user_id=task.user_id,
                    user_role=user_role,
                    message=message,
                    conversation_id=task.conversation_id,
                    chat_task_id=task_id,
                    context=context,
                )

                if wf_result.get("use_workflow"):
                    # Supervisor handled it via workflow
                    for evt in wf_result.get("events", []):
                        redis_buffer.ct_push_event(task_id, evt)
                    full_response = _format_workflow_result(wf_result)
                    resolved_agent_type = "supervisor"
                else:
                    # ── Single agent path ──
                    from agents import (
                        TutorAgent, ReviewerAgent, GeneratorAgent, AnalyticsAgent,
                    )
                    from graph.runner import _classify_intent, MAX_HANDOFFS

                    _AGENT_MAP = {
                        "tutor": TutorAgent,
                        "reviewer": ReviewerAgent,
                        "generator": GeneratorAgent,
                        "analytics": AnalyticsAgent,
                    }

                    # Phase 3: prefer the agent resolved (and rate-limited) at submission.
                    resolved_agent_type = task.routed_agent or task.agent_type

                    state = {
                        "messages": history + [HumanMessage(content=message)],
                        "agent_type": resolved_agent_type,
                        "user_id": task.user_id,
                        "user_role": user_role,
                        "context": context,
                        "tool_results": [],
                        "final_response": "",
                    }

                    # Intent classification (fallback only)
                    if not resolved_agent_type or resolved_agent_type == "auto":
                        state = _classify_intent(state)
                        resolved_agent_type = state.get("agent_type", "tutor")

                    task.routed_agent = resolved_agent_type
                    if conv:
                        conv.agent_type = resolved_agent_type
                    session.flush()
                    redis_buffer.ct_set_status(task_id, "processing", resolved_agent_type)

                    redis_buffer.ct_push_event(task_id, {
                        "type": "start",
                        "conversation_id": task.conversation_id,
                        "agent_type": resolved_agent_type,
                    })

                    if resolved_agent_type != task.agent_type:
                        redis_buffer.ct_push_event(task_id, {
                            "type": "route",
                            "agent_type": resolved_agent_type,
                        })

                    # Stream from agent
                    agent_cls = _AGENT_MAP.get(resolved_agent_type, TutorAgent)
                    agent = agent_cls()
                    full_response = ""

                    for event in agent.stream(state):
                        if event["type"] == "token":
                            full_response += event["content"]
                        redis_buffer.ct_push_event(task_id, event)

                    # Handle handoffs
                    handoff_count = 0
                    previous_agents = [resolved_agent_type]

                    while (state.get("handoff_to")
                           and handoff_count < MAX_HANDOFFS
                           and state["handoff_to"] in _AGENT_MAP
                           and state["handoff_to"] not in previous_agents):

                        target_type = state["handoff_to"]
                        handoff_reason = state.get("handoff_reason", "")

                        redis_buffer.ct_push_event(task_id, {
                            "type": "handoff_start",
                            "target": target_type,
                            "reason": handoff_reason,
                        })

                        # Rebuild a compact context (original request + summary)
                        # and switch to the target; shared with the graph runner.
                        # Worker state is a plain list, so replace it directly.
                        from graph.handoff import apply_handoff
                        apply_handoff(state, use_reducer=False)

                        target_agent = _AGENT_MAP.get(target_type, TutorAgent)()
                        full_response = ""
                        for event in target_agent.stream(state):
                            if event["type"] == "token":
                                full_response += event["content"]
                            redis_buffer.ct_push_event(task_id, event)

                        previous_agents.append(target_type)
                        resolved_agent_type = target_type
                        handoff_count += 1

                        task.routed_agent = resolved_agent_type
                        if conv:
                            conv.agent_type = resolved_agent_type
                        session.flush()
                        redis_buffer.ct_set_status(task_id, "processing", resolved_agent_type)

                    if not full_response:
                        full_response = state.get("final_response", "")

                # ── Filter output ──
                from core.security import filter_output
                filtered = filter_output(full_response, resolved_agent_type, user_role)

                # ── Save assistant message ──
                assistant_msg = AIMessage(
                    conversation_id=task.conversation_id,
                    role="assistant",
                    content=filtered,
                )
                session.add(assistant_msg)
                if conv and not conv.title:
                    conv.title = message[:80]
                session.flush()

                task.result_message_id = assistant_msg.id
                task.status = "completed"
                task.completed_at = _now()

                # Done event
                done_payload = {"type": "done", "message_id": assistant_msg.id}
                redis_buffer.ct_push_event(task_id, done_payload)
                redis_buffer.ct_set_status(task_id, "completed", resolved_agent_type)

            finally:
                from tools.protocol.runtime import reset_tool_runtime
                reset_tool_runtime()

    except Exception as e:
        logger.exception("ChatTask %s failed", task_id)
        _fail_task(task_id, str(e)[:500])


def _format_workflow_result(wf_result: dict) -> str:
    """Format Supervisor workflow result into user-readable response text."""
    import json

    status = wf_result.get("status", "unknown")
    result = wf_result.get("result")
    error = wf_result.get("error")

    if status == "waiting_approval":
        return "题目已生成并保存为草稿，等待您的审批。"
    if status == "failed":
        return f"工作流执行失败：{error or '未知错误'}"
    if status == "completed" and result:
        if isinstance(result, dict):
            for step_output in result.values():
                if isinstance(step_output, dict) and "problem_data" in step_output:
                    return json.dumps(
                        step_output["problem_data"], indent=2, ensure_ascii=False
                    )
        return str(result)
    return "工作流已完成。"


def _update_routed_agent(task_id: str, agent_type: str | None):
    if not agent_type:
        return
    try:
        with db_session() as session:
            task = session.get(ChatTask, task_id)
            if task:
                task.routed_agent = agent_type
        redis_buffer.ct_set_status(task_id, "processing", agent_type)
    except Exception as e:
        logger.warning("Failed to update routed_agent for %s: %s", task_id, e)


def _complete_task(
    task_id: str,
    result_message_id: int | None = None,
    routed_agent: str | None = None,
):
    try:
        with db_session() as session:
            task = session.get(ChatTask, task_id)
            if task:
                task.status = "completed"
                task.completed_at = _now()
                if result_message_id:
                    task.result_message_id = result_message_id
                if routed_agent:
                    task.routed_agent = routed_agent
        redis_buffer.ct_set_status(task_id, "completed", routed_agent)
    except Exception as e:
        logger.error("Failed to mark task %s completed: %s", task_id, e)


def _fail_task(task_id: str, error: str = "Unknown error"):
    try:
        with db_session() as session:
            task = session.get(ChatTask, task_id)
            if task:
                task.status = "failed"
                task.error_detail = error
                task.completed_at = _now()
        redis_buffer.ct_push_event(task_id, {"type": "error", "message": error})
        redis_buffer.ct_set_status(task_id, "failed")
    except Exception as e:
        logger.error("Failed to mark task %s failed: %s", task_id, e)


# ── Workflow ───────────────────────────────────────────────────

def submit_workflow(run_id: str, jwt_token: str, goal: str, context: dict | None = None):
    """Submit a workflow run for background execution."""
    get_executor().submit(_run_workflow, run_id, jwt_token, goal, context)


def _run_workflow(run_id: str, jwt_token: str, goal: str, context: dict | None = None):
    """Execute a workflow directly via SupervisorAgent."""
    try:
        with db_session() as session:
            run = session.get(WorkflowRun, run_id)
            if not run:
                logger.error("WorkflowRun %s not found", run_id)
                return

            run.status = "executing"
            run.started_at = _now()
            session.flush()

            redis_buffer.wf_set_status(run_id, "executing")
            redis_buffer.wf_push_event(run_id, {
                "type": "workflow_start",
                "workflow_id": run_id,
            })

            user = session.get(User, run.user_id)
            user_role = user.role if user else "teacher"

            # Configure the agent MCP client (transport or in-process).
            # The transport client runs tools in the mcp_gateway process and
            # needs no local runtime; the in-process client still binds a
            # session-scoped ToolRuntime for local/dev execution.
            from mcp_gateway.client import (
                configure_mcp_client_from_env,
                InProcessMCPToolClient,
            )
            mcp_client = configure_mcp_client_from_env()
            if isinstance(mcp_client, InProcessMCPToolClient):
                from mcp_gateway.bootstrap import bootstrap_tool_runtime
                bootstrap_tool_runtime(session_factory=lambda: session)

            try:
                plan = run.plan_json if isinstance(run.plan_json, dict) else None
                if plan and plan.get("steps"):
                    from graph.engine import WorkflowEngine

                    state = WorkflowEngine(session=session).execute(
                        plan=plan,
                        user_id=run.user_id,
                        user_role=user_role,
                        conversation_id=run.conversation_id,
                        chat_task_id=run.chat_task_id,
                        workflow_run_id=run_id,
                    )
                else:
                    from graph.supervisor import SupervisorAgent

                    supervisor = SupervisorAgent(session=session)
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
        logger.exception("WorkflowRun %s failed", run_id)
        _fail_workflow(run_id, str(e)[:500])


def _complete_workflow(run_id: str, result: dict | None = None):
    try:
        with db_session() as session:
            run = session.get(WorkflowRun, run_id)
            if run:
                run.status = "completed"
                run.completed_at = _now()
                if result:
                    run.result = result
        redis_buffer.wf_push_event(run_id, {
            "type": "workflow_done",
            "workflow_id": run_id,
        })
        redis_buffer.wf_set_status(run_id, "completed")
    except Exception as e:
        logger.error("Failed to complete workflow %s: %s", run_id, e)


def _fail_workflow(run_id: str, error: str = "Unknown error"):
    try:
        with db_session() as session:
            run = session.get(WorkflowRun, run_id)
            if run:
                run.status = "failed"
                run.error_detail = error
                run.completed_at = _now()
        redis_buffer.wf_push_event(run_id, {
            "type": "workflow_error",
            "message": error,
        })
        redis_buffer.wf_set_status(run_id, "failed")
    except Exception as e:
        logger.error("Failed to mark workflow %s failed: %s", run_id, e)
