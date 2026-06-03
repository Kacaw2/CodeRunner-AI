"""Tool-call execution across the MCP client boundary (Phase 4.2).

Extracted from ``BaseAgent`` so the MCP client-call concern lives in one place
and can be tested/reused independently of the LLM loop. The public behavior is
unchanged: agents still cross the MCP client boundary instead of importing the
server runtime, and the returned ToolMessage envelope is identical.
"""

import json

from langchain_core.messages import ToolMessage


class ToolCallExecutor:
    """Runs a single LLM tool call through the MCP client adapter."""

    def run(self, tool_call: dict, state: dict, default_agent: str, *, session=None) -> ToolMessage:
        from mcp_gateway.client import MCPClientIdentity, get_mcp_tool_client
        from agents.hooks import HookContext, HookEvent, get_hook_manager

        name = tool_call["name"]
        args = tool_call.get("args", {})
        tc_id = tool_call.get("id", "")

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
            content = json.dumps(envelope.get("data", {}), ensure_ascii=False)
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
