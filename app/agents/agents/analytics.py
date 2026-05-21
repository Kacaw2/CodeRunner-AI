from app.agents.agents.base import BaseAgent
from app.agents.state import AgentState
from app.agents.prompts.analytics import ANALYTICS_SYSTEM_PROMPT
from app.agents.tools.question_query import get_question_detail
from app.agents.tools.submission_query import get_student_submissions, get_submission_detail
from app.agents.tools.stats_query import get_student_stats

ANALYTICS_TOOLS = [get_question_detail, get_student_submissions, get_submission_detail, get_student_stats]


class AnalyticsAgent(BaseAgent):
    name = "analytics"
    description = "Learning analytics agent"

    def _build_system_context(self, state: dict) -> str:
        context = state.get("context", {})
        parts = [ANALYTICS_SYSTEM_PROMPT]
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
        return self._invoke_with_tools(state, ANALYTICS_TOOLS, self._build_system_context(state))

    def stream(self, state: AgentState):
        yield from self._stream_with_tools(state, ANALYTICS_TOOLS, self._build_system_context(state))
