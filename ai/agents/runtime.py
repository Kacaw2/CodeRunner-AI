"""AgentRuntime — thin facade that owns the invoke/stream orchestration.

The loop body is the same logic previously inlined in BaseAgent, now driven by
an AgentSession so trace/identity/budget come from one carrier. Trace ownership
(acquire/owns/finalize) is unchanged.
"""

import json
import logging

from langchain_core.messages import AIMessage, SystemMessage

from ai.agents.config import AIConfig, MAX_LLM_CALLS_PER_TRACE, MAX_TOOL_ITERATIONS
from ai.agents.executor import ToolCallExecutor
from ai.agents.llm_runner import LLMRunner
from ai.agents.base import (
    _legacy_tag_names,
    _parse_legacy_function_text,
    _split_safe_stream_content,
    _trace_links_from_state,
)
from core.exceptions import AgentExecutionLimitError, LLMError
from ai.llm.tiers import ModelTier
from ai.tools.protocol.adapters import parse_llm_tool_call

logger = logging.getLogger(__name__)

_HANDOFF_KEYS = (
    "handoff_to", "handoff_reason", "handoff_summary",
    "handoff_source", "previous_agents",
)

# Tool calls whose result is a durable run output worth surfacing on the trace
# Artifacts tab: (artifact_type, display name).
_ARTIFACT_TOOLS = {
    "coderunner.code.execute": ("code_execution", "Code execution result"),
    "coderunner.code.execute_internal": ("code_execution", "Code execution result"),
    "coderunner.problem.save_generated": ("generated_problem", "Generated problem"),
}


def _record_tool_artifact(trace, tool_name: str, content) -> None:
    """Persist an artifact for artifact-worthy tools. Best-effort: never raises."""
    meta = _ARTIFACT_TOOLS.get(tool_name)
    if not meta:
        return
    artifact_type, name = meta
    payload = None
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            payload = parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            payload = None
    elif isinstance(content, dict):
        payload = content
    trace.add_artifact(
        artifact_type=artifact_type,
        name=name,
        preview_text=content if isinstance(content, str) else None,
        payload_json=payload,
    )


def _hydrate_legacy_tool_args(tool_call: dict, session) -> dict:
    """Fill arguments that legacy text tags omitted but page context provides."""
    if tool_call.get("name") != "coderunner.problem.get_detail":
        return tool_call
    args = dict(tool_call.get("args") or {})
    if args.get("problem_id"):
        return tool_call
    problem_id = session.context.get("problem_id") or session.context.get("question_id")
    if not problem_id:
        return tool_call
    hydrated = dict(tool_call)
    hydrated["args"] = {**args, "problem_id": problem_id}
    return hydrated


class AgentRuntime:
    """Run one agent session as invoke() or stream()."""

    _executor = ToolCallExecutor()

    @staticmethod
    def _max_iterations(session) -> int:
        defn = session.definition
        if defn is not None and getattr(defn, "max_tool_iterations", None):
            return defn.max_tool_iterations
        return MAX_TOOL_ITERATIONS  # fallback for unregistered agents

    def _acquire(self, session, system_ctx, tool_names):
        from core.observability.tracing import acquire_trace
        from ai.tools.protocol import get_tool_runtime
        from ai.tools.protocol.adapters import descriptors_to_llm_tools

        state = session.to_state()
        trace, owns_trace = acquire_trace(
            agent_type=session.agent_name,
            user_id=session.user_id,
            conversation_id=session.context.get("conversation_id"),
            links=_trace_links_from_state(state),
            input_message=(
                getattr(session.messages[-1], "content", "") if session.messages else ""
            ),
            input_context=session.context,
        )
        session.trace = trace
        session.trace_id = trace.run_id  # available to tool calls BEFORE the loop

        runtime = get_tool_runtime()
        descriptors = runtime.list_tools(names=tool_names)
        tool_schemas = descriptors_to_llm_tools(descriptors)

        tier = session.definition.default_model_tier if session.definition else ModelTier.BALANCED
        llm = AIConfig.get_llm(tier=tier)
        llm_with_tools = llm.bind_tools(tool_schemas)

        messages = [SystemMessage(content=system_ctx)] + list(session.messages)
        compaction = LLMRunner.compact_window(messages, max_messages=20)
        messages = compaction.messages
        trace.trace_compaction(compaction)
        return trace, owns_trace, llm_with_tools, messages

    def _apply_after_run(self, session, out_state):
        """Fire AFTER_AGENT_RUN and reflect handoff keys back onto the session so
        the caller's state (e.g. AgentHarness) sees them.

        Handoff fields are populated by the ``delegate`` tool call inside the loop
        (see ToolCallExecutor); this method only mirrors them — there is no
        free-text marker detection."""
        from ai.agents.hooks import HookContext, HookEvent, get_hook_manager

        get_hook_manager().fire(HookContext(
            event=HookEvent.AFTER_AGENT_RUN,
            agent_name=session.agent_name,
            state=out_state,
            final_response=session.final_response,
        ))
        for k in _HANDOFF_KEYS:
            if out_state.get(k) is not None:
                session.extra_state[k] = out_state[k]
        return out_state

    def run(self, session, *, tool_names, system_ctx):
        from core.observability.tracing import finalize_trace

        trace, owns_trace, llm_with_tools, messages = self._acquire(
            session, system_ctx, tool_names)
        state = session.to_state()  # boundary dict for executor/hooks

        response = None
        limit_exceeded = False
        try:
            for iteration in range(self._max_iterations(session)):
                if trace.llm_call_count >= MAX_LLM_CALLS_PER_TRACE:
                    logger.warning("Trace %s hit LLM budget; aborting %s loop",
                                   trace.run_id, session.agent_name)
                    limit_exceeded = True
                    break
                with trace.trace_llm_call() as llm_step:
                    try:
                        response = LLMRunner.invoke(llm_with_tools, messages)
                    except LLMError:
                        if iteration == 0:
                            raise
                        break
                    in_tok, out_tok = LLMRunner.extract_usage(response)
                    if in_tok or out_tok:
                        trace.total_input_tokens += in_tok
                        trace.total_output_tokens += out_tok
                        llm_step["prompt_tokens"] = in_tok
                        llm_step["completion_tokens"] = out_tok

                messages.append(response)
                legacy = _parse_legacy_function_text(getattr(response, "content", ""), tool_names)
                if legacy and not response.tool_calls:
                    response = AIMessage(
                        content="",
                        tool_calls=[_hydrate_legacy_tool_args(legacy, session)],
                    )
                    messages[-1] = response

                if not response.tool_calls:
                    break

                for tc in response.tool_calls:
                    req = parse_llm_tool_call(tc)
                    tc = {"name": req.tool_name, "args": req.args, "id": req.tool_call_id}
                    tc = _hydrate_legacy_tool_args(tc, session)
                    with trace.trace_tool_call(tc["name"], tc["args"]) as tool_step:
                        tool_msg = self._executor.run(tc, state, session.agent_name, session=session)
                        tool_step["tool_output"] = tool_msg.content
                        messages.append(tool_msg)
                    _record_tool_artifact(trace, tc["name"], tool_msg.content)
                compaction = LLMRunner.compact_window(messages, max_messages=20)
                messages = compaction.messages
                trace.trace_compaction(compaction)
            else:
                limit_exceeded = bool(response and response.tool_calls)

            session.messages = [m for m in messages if not isinstance(m, SystemMessage)]

            if limit_exceeded:
                error = AgentExecutionLimitError(session.agent_name, self._max_iterations(session))
                session.final_response = error.user_message
                finalize_trace(trace, owns_trace, status="limit_exceeded",
                               response=error.user_message, error=error)
                return session.to_state()

            session.final_response = (response.content if response and response.content else "")
            out_state = self._apply_after_run(session, session.to_state())
            finalize_trace(trace, owns_trace, status="completed",
                           response=session.final_response)
            return out_state
        except Exception as e:
            finalize_trace(trace, owns_trace, status="failed", error=e)
            raise

    def stream(self, session, *, tool_names, system_ctx):
        from core.observability.tracing import finalize_trace

        trace, owns_trace, llm_with_tools, messages = self._acquire(
            session, system_ctx, tool_names)
        state = session.to_state()
        tag_names = _legacy_tag_names(tool_names)

        trace_saved = False
        limit_exceeded = False
        try:
            for iteration in range(self._max_iterations(session)):
                if trace.llm_call_count >= MAX_LLM_CALLS_PER_TRACE:
                    limit_exceeded = True
                    break

                collected_content = ""
                pending_content = ""
                tool_calls = []
                try:
                    with trace.trace_llm_call() as llm_step:
                        for chunk in LLMRunner.stream(llm_with_tools, messages):
                            if chunk.content:
                                collected_content += chunk.content
                                pending_content += chunk.content
                                safe, pending_content = _split_safe_stream_content(pending_content, tag_names)
                                if safe:
                                    yield {"type": "token", "content": safe}
                            if chunk.tool_call_chunks:
                                for tcc in chunk.tool_call_chunks:
                                    if tcc.get("index") is not None:
                                        idx = tcc["index"]
                                        while len(tool_calls) <= idx:
                                            tool_calls.append({"name": "", "args": "", "id": ""})
                                        if tcc.get("name"):
                                            tool_calls[idx]["name"] = tcc["name"]
                                        if tcc.get("args"):
                                            tool_calls[idx]["args"] += tcc["args"]
                                        if tcc.get("id"):
                                            tool_calls[idx]["id"] = tcc["id"]
                            in_tok, out_tok = LLMRunner.extract_usage(chunk)
                            if in_tok or out_tok:
                                trace.total_input_tokens += in_tok
                                trace.total_output_tokens += out_tok
                                llm_step["prompt_tokens"] = llm_step.get("prompt_tokens", 0) + in_tok
                                llm_step["completion_tokens"] = llm_step.get("completion_tokens", 0) + out_tok
                except LLMError as e:
                    if iteration == 0:
                        yield {"type": "error", "message": e.user_message}
                        finalize_trace(trace, owns_trace, status="failed", error=e)
                        trace_saved = True
                        return
                    break

                legacy = _parse_legacy_function_text(collected_content, tool_names)
                if legacy and not tool_calls:
                    tool_calls = [_hydrate_legacy_tool_args(legacy, session)]
                    collected_content = ""

                if not tool_calls:
                    if pending_content:
                        yield {"type": "token", "content": pending_content}
                    session.final_response = collected_content
                    messages.append(AIMessage(content=collected_content))
                    break

                parsed_calls = []
                for tc in tool_calls:
                    if not tc["name"]:
                        continue
                    args = tc["args"]
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    req = parse_llm_tool_call(
                        {"name": tc["name"], "args": args, "id": tc["id"]}
                    )
                    parsed_calls.append(
                        _hydrate_legacy_tool_args(
                            {
                                "name": req.tool_name,
                                "args": req.args,
                                "id": req.tool_call_id,
                            },
                            session,
                        )
                    )

                messages.append(AIMessage(content=collected_content, tool_calls=parsed_calls))
                for tc in parsed_calls:
                    yield {"type": "tool_call", "tool": tc["name"], "input": str(tc["args"])}
                    with trace.trace_tool_call(tc["name"], tc["args"]) as tool_step:
                        tool_msg = self._executor.run(tc, state, session.agent_name, session=session)
                        tool_step["tool_output"] = tool_msg.content
                        messages.append(tool_msg)
                    _record_tool_artifact(trace, tc["name"], tool_msg.content)
                    yield {"type": "tool_result", "tool": tc["name"],
                           "summary": f"Fetched {tc['name']} result"}
                compaction = LLMRunner.compact_window(messages, max_messages=20)
                messages = compaction.messages
                trace.trace_compaction(compaction)
            else:
                limit_exceeded = True

            session.messages = [m for m in messages if not isinstance(m, SystemMessage)]

            if limit_exceeded:
                error = AgentExecutionLimitError(session.agent_name, self._max_iterations(session))
                session.final_response = error.user_message
                yield {"type": "error", "message": error.user_message}
                finalize_trace(trace, owns_trace, status="limit_exceeded",
                               response=error.user_message, error=error)
                trace_saved = True
                return

            out_state = self._apply_after_run(session, session.to_state())
            if out_state.get("handoff_to"):
                yield {"type": "handoff", "target": out_state["handoff_to"],
                       "reason": out_state.get("handoff_reason", "")}

            finalize_trace(trace, owns_trace, status="completed",
                           response=session.final_response)
            trace_saved = True
        except GeneratorExit:
            if not trace_saved:
                finalize_trace(trace, owns_trace, status="interrupted")
                trace_saved = True
        except Exception as e:
            if not trace_saved:
                finalize_trace(trace, owns_trace, status="failed", error=e)
                trace_saved = True
            raise
