"""MCP tool wrapper for agent trace operations (medium risk — sanitized output)."""

import json

from mcp.server import FastMCP

from tools.traces.queries import get_agent_trace_impl
from core.db.session import get_session
from mcp_gateway.middleware import run_mcp_guard
from mcp_gateway.middleware.sanitizer import sanitize_agent_trace


def register_trace_tools(mcp: FastMCP):
    @mcp.tool(
        name="get_agent_trace",
        description=(
            "Get sanitized execution trace for an AI agent run. "
            "Returns agent type, status, latency metrics, token usage, "
            "and tool call steps. System prompts and full code are redacted."
        ),
    )
    def get_agent_trace(run_id: str) -> str:
        args = {"run_id": run_id}
        guard = run_mcp_guard("get_agent_trace", args)
        if guard.rejected:
            return guard.error_json
        session = get_session()
        try:
            raw = get_agent_trace_impl(run_id, session=session)
            if "error" in raw:
                guard.record_success("get_agent_trace", args)
                return json.dumps(raw, ensure_ascii=False)
            sanitized = sanitize_agent_trace(raw["run"], raw["steps"])
            guard.record_success("get_agent_trace", args)
            return json.dumps(sanitized, ensure_ascii=False, default=str)
        except Exception as e:
            guard.record_error("get_agent_trace", args, e)
            return json.dumps({"error": str(e)})
        finally:
            session.close()
