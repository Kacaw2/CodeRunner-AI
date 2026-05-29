"""MCP tool wrapper for agent trace operations (medium risk — sanitized output)."""

from mcp.server import FastMCP

from mcp_gateway.middleware import _guarded, call_via_runtime


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
        return _guarded(lambda: call_via_runtime(
            "coderunner.trace.get_agent_trace",
            {"run_id": run_id},
        ))
