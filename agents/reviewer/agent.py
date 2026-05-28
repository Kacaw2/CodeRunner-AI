from agents.base import BaseAgent
from models.tiers import ModelTier
from core.security import SECURITY_PROMPT_ADDENDUM
from graph.handoff import HANDOFF_PROMPT_ADDENDUM
from core.state import AgentState
from agents.reviewer.prompt import REVIEWER_SYSTEM_PROMPT

REVIEWER_MCP_TOOLS = [
    "coderunner.code.execute",
    "coderunner.problem.get_detail",
]


class ReviewerAgent(BaseAgent):
    name = "reviewer"
    description = "Code review agent"
    default_model_tier = ModelTier.BALANCED
    mcp_tool_names = REVIEWER_MCP_TOOLS

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
        return self._invoke_with_mcp_tools(state, REVIEWER_MCP_TOOLS, self._build_system_context(state))

    def stream(self, state: AgentState):
        yield from self._stream_with_mcp_tools(state, REVIEWER_MCP_TOOLS, self._build_system_context(state))
