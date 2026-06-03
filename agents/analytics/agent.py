from agents.base import BaseAgent
from models.tiers import ModelTier
from core.security import SECURITY_PROMPT_ADDENDUM
from graph.handoff import HANDOFF_PROMPT_ADDENDUM
from core.state import AgentState
from agents.analytics.prompt import ANALYTICS_SYSTEM_PROMPT


class AnalyticsAgent(BaseAgent):
    name = "analytics"
    description = "Learning analytics agent"
    default_model_tier = ModelTier.STRONG

    def _build_system_context(self, state: dict) -> str:
        from memory.service import MemoryService

        context = state.get("context", {})
        parts = [ANALYTICS_SYSTEM_PROMPT + SECURITY_PROMPT_ADDENDUM + HANDOFF_PROMPT_ADDENDUM]

        memory_ctx = MemoryService.get_memory_context(
            state.get("user_id", 0),
            state.get("user_role", "student"),
            conversation_id=context.get("conversation_id"),
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
        return self._invoke_with_mcp_tools(state, self.mcp_tool_names, self._build_system_context(state))

    def stream(self, state: AgentState):
        yield from self._stream_with_mcp_tools(state, self.mcp_tool_names, self._build_system_context(state))
