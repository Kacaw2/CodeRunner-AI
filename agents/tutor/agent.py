from agents.base import BaseAgent
from models.tiers import ModelTier
from core.security import SECURITY_PROMPT_ADDENDUM
from graph.handoff import HANDOFF_PROMPT_ADDENDUM
from core.state import AgentState
from agents.tutor.prompt import TUTOR_SYSTEM_PROMPT


class TutorAgent(BaseAgent):
    name = "tutor"
    description = "Socratic tutoring agent for students"
    default_model_tier = ModelTier.BALANCED

    def _build_system_context(self, state: dict) -> str:
        from memory.service import MemoryService

        context = state.get("context", {})
        parts = [TUTOR_SYSTEM_PROMPT + SECURITY_PROMPT_ADDENDUM + HANDOFF_PROMPT_ADDENDUM]

        memory_ctx = MemoryService.get_memory_context(state["user_id"], state.get("user_role", "student"))
        if memory_ctx:
            parts.append(f"\n## Student Profile (from previous sessions)\n{memory_ctx}")

        kb_context = self._get_kb_context(state)
        if kb_context:
            parts.append(kb_context)

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

    MIN_KNOWLEDGE_SCORE = 0.3

    def _get_kb_context(self, state: dict) -> str:
        """Retrieve relevant knowledge and error patterns from the KB based on context."""
        try:
            from knowledge.store import get_knowledge_base
            kb = get_knowledge_base()
        except Exception:
            return ""

        parts = []
        context = state.get("context", {})
        messages = state.get("messages", [])
        last_msg = messages[-1].content if messages else ""

        error_status = context.get("error_status", "")
        if error_status:
            query = f"{error_status} {context.get('code', '')[:200]}"
            patterns = kb.search_error_patterns(query, n=2)
            patterns = [p for p in patterns if p.get("score", 0) >= self.MIN_KNOWLEDGE_SCORE]
            if patterns:
                parts.append("\n## Relevant Error Patterns (from knowledge base)")
                for p in patterns:
                    parts.append(f"- [{p.get('error_type', '')}] {p['content'][:300]}")
                parts.append("Use these patterns to guide your diagnosis — do NOT paste them verbatim to the student.")

        topic_query = context.get("topic") or last_msg[:200]
        if topic_query:
            knowledge = kb.search_knowledge(topic_query, n=2)
            knowledge = [k for k in knowledge if k.get("score", 0) >= self.MIN_KNOWLEDGE_SCORE]
            if knowledge:
                parts.append("\n## Relevant Knowledge Points (from knowledge base)")
                for k in knowledge:
                    parts.append(f"- [{k.get('topic', '')}] {k['content'][:300]}")
                parts.append("Reference these for accuracy, but explain in your own words using Socratic method.")

        return "\n".join(parts)

    def invoke(self, state: AgentState) -> AgentState:
        return self._invoke_with_mcp_tools(state, self.mcp_tool_names, self._build_system_context(state))

    def stream(self, state: AgentState):
        yield from self._stream_with_mcp_tools(state, self.mcp_tool_names, self._build_system_context(state))
