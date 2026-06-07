from ai.agents.base import BaseAgent
from core.security import SECURITY_PROMPT_ADDENDUM
from ai.graph.handoff import HANDOFF_PROMPT_ADDENDUM
from core.state import AgentState
from ai.agents.reviewer.prompt import REVIEWER_SYSTEM_PROMPT


class ReviewerAgent(BaseAgent):
    name = "reviewer"

    def _build_system_context(self, state: dict) -> str:
        context = state.get("context", {})
        parts = [REVIEWER_SYSTEM_PROMPT + SECURITY_PROMPT_ADDENDUM + HANDOFF_PROMPT_ADDENDUM]
        if context.get("question_id"):
            parts.append(f"\nProblem ID (use get_problem_detail to fetch requirements): {context['question_id']}")
        if context.get("language"):
            parts.append(f"Programming language: {context['language']}")
        if context.get("code"):
            parts.append(f"\nCode to review:\n```\n{context['code']}\n```")
        return "\n".join(parts)

    def invoke(self, state: AgentState) -> AgentState:
        return self._invoke_with_mcp_tools(state, self.mcp_tool_names, self._build_system_context(state))

    def stream(self, state: AgentState):
        yield from self._stream_with_mcp_tools(state, self.mcp_tool_names, self._build_system_context(state))
