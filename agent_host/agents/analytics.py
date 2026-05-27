from agent_host.agents.base import BaseAgent
from agent_host.model_router.tiers import ModelTier
from agent_host.security import SECURITY_PROMPT_ADDENDUM
from agent_host.handoff import HANDOFF_PROMPT_ADDENDUM
from agent_host.state import AgentState
from agent_host.prompts.analytics import ANALYTICS_SYSTEM_PROMPT

ANALYTICS_MCP_TOOLS = [
    "coderunner.problem.get_detail",
    "coderunner.submission.list_for_student",
    "coderunner.submission.get_detail",
    "coderunner.analytics.student_stats",
    "coderunner.analytics.student_activity",
    "coderunner.analytics.class_statistics",
    "coderunner.analytics.problem_difficulty",
]


class AnalyticsAgent(BaseAgent):
    name = "analytics"
    description = "Learning analytics agent"
    default_model_tier = ModelTier.STRONG
    mcp_tool_names = ANALYTICS_MCP_TOOLS

    def _build_system_context(self, state: dict) -> str:
        from agent_host.memory import MemoryService

        context = state.get("context", {})
        parts = [ANALYTICS_SYSTEM_PROMPT + SECURITY_PROMPT_ADDENDUM + HANDOFF_PROMPT_ADDENDUM]

        memory_ctx = MemoryService.get_memory_context(
            state.get("user_id", 0), state.get("user_role", "student")
        )
        if memory_ctx:
            parts.append(f"\n## User Profile Context\n{memory_ctx}")

        if state.get("user_id"):
            parts.append(f"\nCurrent user ID: {state['user_id']}")
        if state.get("user_role"):
            parts.append(f"Current user role: {state['user_role']}")
        if context.get("target_student_id"):
            parts.append(f"Target student ID to analyze: {context['target_student_id']}")
        if context.get("question_id"):
            parts.append(f"Focus on question ID: {context['question_id']}")
        if context.get("period"):
            parts.append(f"Analysis period: {context['period']}")
        return "\n".join(parts)

    def invoke(self, state: AgentState) -> AgentState:
        return self._invoke_with_mcp_tools(state, ANALYTICS_MCP_TOOLS, self._build_system_context(state))

    def stream(self, state: AgentState):
        yield from self._stream_with_mcp_tools(state, ANALYTICS_MCP_TOOLS, self._build_system_context(state))
