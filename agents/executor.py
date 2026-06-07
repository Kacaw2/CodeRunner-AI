"""Tool-call execution across the MCP client boundary (Phase 4.2).

Extracted from ``BaseAgent`` so the MCP client-call concern lives in one place
and can be tested/reused independently of the LLM loop. The public behavior is
unchanged: agents still cross the MCP client boundary instead of importing the
server runtime, and the returned ToolMessage envelope is identical.
"""

import json

from langchain_core.messages import ToolMessage

DELEGATE_TOOL = "coderunner.agent.delegate"
_HANDOFF_RESULT_KEYS = (
    "handoff_to", "handoff_reason", "handoff_source", "handoff_summary",
)


class ToolCallExecutor:
    """Runs a single LLM tool call through the MCP client adapter."""

    def run(self, tool_call: dict, state: dict, default_agent: str, *, session=None) -> ToolMessage:
        from mcp_gateway.client import MCPClientIdentity, get_mcp_tool_client
        from agents.hooks import HookContext, HookEvent, get_hook_manager
        from tools.protocol.adapters import parse_llm_tool_call

        request = parse_llm_tool_call(tool_call)
        name = request.tool_name
        args = request.args
        tc_id = request.tool_call_id
        tool_call = {"name": name, "args": args, "id": tc_id}

        agent_name = session.agent_name if session is not None else state.get("agent_type", default_agent)
        hooks = get_hook_manager()

        # BeforeToolCall: enforce the agent's tool allowlist before the call
        # crosses the MCP client boundary.
        before = hooks.fire(HookContext(
            event=HookEvent.BEFORE_TOOL_CALL,
            agent_name=agent_name,
            state=state,
            tool_call=tool_call,
        ))
        if not before.allowed:
            content = json.dumps({
                "error": "TOOL_NOT_ALLOWED",
                "message": before.error or f"Tool '{name}' is not allowed",
            }, ensure_ascii=False)
            return ToolMessage(content=content, tool_call_id=tc_id)

        if session is not None:
            identity = session.mcp_identity()
        else:
            identity = MCPClientIdentity(
                user_id=state.get("user_id", 0),
                role=state.get("user_role", "student"),
                agent_type=state.get("agent_type", default_agent),
                task_id=state.get("context", {}).get("task_id"),
                conversation_id=state.get("context", {}).get("conversation_id"),
                trace_id=state.get("trace_id") or state.get("context", {}).get("trace_id"),
            )

        envelope = get_mcp_tool_client().call_tool(name, args, identity, tool_call_id=tc_id)

        # AfterToolCall: normalize/audit the tool result (warn-only).
        hooks.fire(HookContext(
            event=HookEvent.AFTER_TOOL_CALL,
            agent_name=agent_name,
            state=state,
            tool_call=tool_call,
            tool_result=envelope,
        ))

        if envelope.get("ok"):
            data = envelope.get("data", {})
            # Delegation is a structured tool call: the handler validated the
            # target edge + role at the boundary and returned the handoff fields.
            # Reflect them onto the session so the runner/worker switches agents
            # after the run (replaces the old free-text marker path).
            if name == DELEGATE_TOOL and session is not None and isinstance(data, dict):
                for key in _HANDOFF_RESULT_KEYS:
                    if data.get(key):
                        session.extra_state[key] = data[key]
            content = json.dumps(data, ensure_ascii=False)
        elif envelope.get("status") == "approval_required":
            err = envelope.get("error") or {}
            content = json.dumps({
                "status": "approval_required",
                "approval_id": envelope.get("approval_id", ""),
                "message": err.get("message", ""),
            }, ensure_ascii=False)
        else:
            err = envelope.get("error") or {}
            content = json.dumps({
                "error": err.get("code", "MCP_INTERNAL_ERROR"),
                "message": err.get("message", "Tool call failed"),
            }, ensure_ascii=False)

        return ToolMessage(content=content, tool_call_id=tc_id)
