import logging
from datetime import datetime

from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)


class MemoryService:
    """Manages cross-conversation memory and profile updates."""

    @staticmethod
    def generate_conversation_summary(conversation_id: int) -> str:
        """After a conversation ends, generate a summary for mid-term memory."""
        from app.models.ai_conversation import AIMessage
        from app.agents.config import AIConfig

        messages = AIMessage.query.filter_by(conversation_id=conversation_id).all()
        if len(messages) < 4:
            return ""

        try:
            llm = AIConfig.get_llm()
            transcript = "\n".join(
                f"[{m.role}] {m.content[:500]}" for m in messages[-10:]
            )
            prompt = (
                "Summarize this tutoring conversation in 2-3 sentences. "
                "Focus on: what the student struggled with, what hints were given, "
                f"what they learned.\n\n{transcript}"
            )
            response = llm.invoke([HumanMessage(content=prompt)])
            return response.content
        except Exception as e:
            logger.warning("Failed to generate conversation summary: %s", e)
            return ""

    @staticmethod
    def update_student_profile(student_id: int):
        """Rebuild student profile from recent submission data."""
        from app.core.extensions import db
        from app.models.submission import Submission
        from app.models.student_profile import StudentProfile

        recent = (
            Submission.query.filter_by(student_id=student_id)
            .order_by(Submission.submitted_at.desc())
            .limit(50)
            .all()
        )

        error_counts = {"WA": 0, "RE": 0, "CE": 0, "TLE": 0, "AC": 0}
        for s in recent:
            status = (s.status or "").upper()
            if status == "COMPLETED":
                error_counts["AC"] += 1
            elif status == "ERROR":
                error_counts["RE"] += 1
            elif status in error_counts:
                error_counts[status] += 1

        profile = StudentProfile.query.filter_by(student_id=student_id).first()
        if not profile:
            profile = StudentProfile(student_id=student_id)
            db.session.add(profile)

        profile.error_patterns = error_counts
        profile.recent_questions = [s.question_id for s in recent[:10]]
        profile.updated_at = datetime.utcnow()
        db.session.commit()

    @staticmethod
    def get_memory_context(user_id: int, user_role: str) -> str:
        """Build memory context string to inject into system prompt.

        Returns empty string if profile tables are not yet migrated,
        ensuring graceful degradation before migration is applied.
        """
        try:
            if user_role == "student":
                from app.models.student_profile import StudentProfile

                profile = StudentProfile.query.filter_by(student_id=user_id).first()
                if not profile:
                    return ""
                parts = []
                if profile.learning_summary:
                    parts.append(f"Student Background: {profile.learning_summary}")
                if profile.error_patterns:
                    parts.append(f"Error History: {profile.error_patterns}")
                if profile.knowledge_map:
                    weak = [k for k, v in profile.knowledge_map.items() if v < 0.5]
                    if weak:
                        parts.append(f"Weak Areas: {', '.join(weak)}")
                if profile.current_hint_level:
                    parts.append(f"Previous Hints Given: {profile.current_hint_level}")
                return "\n".join(parts)

            elif user_role == "teacher":
                from app.models.student_profile import TeacherPreference

                pref = TeacherPreference.query.filter_by(teacher_id=user_id).first()
                if not pref:
                    return ""
                parts = []
                if pref.style_notes:
                    parts.append(f"Teacher Preferences: {pref.style_notes}")
                if pref.class_weak_areas:
                    parts.append(f"Class Weak Areas: {', '.join(pref.class_weak_areas)}")
                return "\n".join(parts)

        except Exception as e:
            logger.debug("Memory context unavailable (table may not exist yet): %s", e)
            return ""

        return ""

    @staticmethod
    def compact_messages(messages: list, max_messages: int = 20) -> list:
        """If conversation exceeds max_messages, summarize early messages.

        Uses LLM to compress early messages into a summary, falling back
        to simple truncation if the LLM call fails.
        """
        if len(messages) <= max_messages:
            return messages

        system_msg = messages[0]
        early = messages[1:-max_messages]
        recent = messages[-max_messages:]

        try:
            from app.agents.config import AIConfig
            transcript_parts = []
            for m in early:
                content = getattr(m, "content", "")
                if content:
                    role = getattr(m, "type", "unknown")
                    transcript_parts.append(f"[{role}] {content[:300]}")
            if transcript_parts:
                llm = AIConfig.get_llm()
                prompt = (
                    "Compress the following conversation history into a brief summary "
                    "(max 200 words). Preserve key facts, decisions, and context.\n\n"
                    + "\n".join(transcript_parts)
                )
                response = llm.invoke([HumanMessage(content=prompt)])
                summary_text = f"Previous conversation summary:\n{response.content}"
                return [system_msg, HumanMessage(content=summary_text)] + recent
        except Exception as e:
            logger.warning("LLM compression failed, falling back to truncation: %s", e)

        topics = []
        for m in early:
            content = getattr(m, "content", "")
            if content:
                topics.append(content[:100])
        summary_text = (
            "Previous conversation summary: discussed "
            + "; ".join(topics[:5])
            + ("..." if len(topics) > 5 else "")
        )
        return [system_msg, HumanMessage(content=summary_text)] + recent
