from app.agents.agents.base import BaseAgent
from app.agents.security import SECURITY_PROMPT_ADDENDUM
from app.agents.handoff import HANDOFF_PROMPT_ADDENDUM
from app.agents.state import AgentState
from app.agents.prompts.reviewer import REVIEWER_SYSTEM_PROMPT
from app.agents.tools.code_executor import execute_code
from app.agents.tools.question_query import get_problem_detail

REVIEWER_TOOLS = [execute_code, get_problem_detail]


class ReviewerAgent(BaseAgent):
    name = "reviewer"
    description = "Code review agent"

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
        return self._invoke_with_tools(state, REVIEWER_TOOLS, self._build_system_context(state))

    def stream(self, state: AgentState):
        yield from self._stream_with_tools(state, REVIEWER_TOOLS, self._build_system_context(state))
