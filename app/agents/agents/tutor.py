from app.agents.agents.base import BaseAgent
from app.agents.security import SECURITY_PROMPT_ADDENDUM
from app.agents.state import AgentState
from app.agents.prompts.tutor import TUTOR_SYSTEM_PROMPT
from app.agents.tools.code_executor import execute_code
from app.agents.tools.question_query import get_question_detail
from app.agents.tools.submission_query import get_student_submissions, get_submission_detail
from app.agents.tools.knowledge_tools import search_knowledge, search_error_patterns

TUTOR_TOOLS = [execute_code, get_question_detail, get_student_submissions, get_submission_detail,
               search_knowledge, search_error_patterns]


class TutorAgent(BaseAgent):
    name = "tutor"
    description = "Socratic tutoring agent for students"

    def _build_system_context(self, state: dict) -> str:
        from app.agents.memory import MemoryService

        context = state.get("context", {})
        parts = [TUTOR_SYSTEM_PROMPT + SECURITY_PROMPT_ADDENDUM]

        memory_ctx = MemoryService.get_memory_context(state["user_id"], state.get("user_role", "student"))
        if memory_ctx:
            parts.append(f"\n## Student Profile (from previous sessions)\n{memory_ctx}")

        if state.get("user_id"):
            parts.append(f"\nCurrent student's user ID (use as student_id for tools): {state['user_id']}")
        if context.get("question_id"):
            parts.append(f"Current question ID: {context['question_id']}")
        if context.get("submission_id"):
            parts.append(f"Current submission ID: {context['submission_id']}")
        if context.get("error_status"):
            parts.append(f"Error status: {context['error_status']}")
        if context.get("code"):
            parts.append(f"\nStudent's current code:\n```\n{context['code']}\n```")
        return "\n".join(parts)

    def invoke(self, state: AgentState) -> AgentState:
        return self._invoke_with_tools(state, TUTOR_TOOLS, self._build_system_context(state))

    def stream(self, state: AgentState):
        yield from self._stream_with_tools(state, TUTOR_TOOLS, self._build_system_context(state))
