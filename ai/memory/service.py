import logging
from app.core.timezone import now_china

from langchain_core.messages import HumanMessage

from ai.memory.context import (
    MemoryContext,
    MemoryItem,
    MemoryMetadata,
    RecentSessionMemory,
)

logger = logging.getLogger(__name__)


class MemoryService:
    """Manages cross-conversation memory and profile updates."""

    @staticmethod
    def generate_conversation_summary(conversation_id: int) -> str:
        """After a conversation ends, generate a summary for mid-term memory."""
        from app.core.extensions import db
        from ai.agents.config import AIConfig
        from domain.repositories.chat import SyncChatRepository

        repo = SyncChatRepository(db.session)
        messages = repo.get_messages_ordered(conversation_id)
        if len(messages) < 4:
            return ""

        try:
            from ai.llm.tiers import ModelTier
            llm = AIConfig.get_llm(tier=ModelTier.FAST)
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
        profile.updated_at = now_china()
        db.session.commit()

    @staticmethod
    def _student_profile_items(
        student_id: int, reason: str
    ) -> tuple[MemoryItem, ...]:
        from app.models.student_profile import StudentProfile

        profile = StudentProfile.query.filter_by(student_id=student_id).first()
        if profile is None:
            return ()

        metadata = MemoryMetadata(
            source=f"student_profile:{student_id}",
            reason_included=reason,
        )
        items: list[MemoryItem] = []
        if profile.learning_summary:
            items.append(MemoryItem(
                key="learning_summary",
                value=profile.learning_summary,
                metadata=metadata,
            ))
        if profile.error_patterns:
            items.append(MemoryItem(
                key="error_patterns",
                value=dict(profile.error_patterns),
                metadata=metadata,
            ))
        if profile.knowledge_map:
            weak_areas = tuple(
                key
                for key, score in profile.knowledge_map.items()
                if score < 0.5
            )
            if weak_areas:
                items.append(MemoryItem(
                    key="weak_areas",
                    value=weak_areas,
                    metadata=metadata,
                ))
        if profile.current_hint_level:
            items.append(MemoryItem(
                key="current_hint_level",
                value=dict(profile.current_hint_level),
                metadata=metadata,
            ))
        return tuple(items)

    @staticmethod
    def _teacher_preference_items(
        teacher_id: int, reason: str
    ) -> tuple[MemoryItem, ...]:
        from app.models.student_profile import TeacherPreference

        preference = TeacherPreference.query.filter_by(
            teacher_id=teacher_id
        ).first()
        if preference is None:
            return ()

        metadata = MemoryMetadata(
            source=f"teacher_preference:{teacher_id}",
            reason_included=reason,
        )
        items: list[MemoryItem] = []
        if preference.style_notes:
            items.append(MemoryItem(
                key="style_notes",
                value=preference.style_notes,
                metadata=metadata,
            ))
        if preference.class_weak_areas:
            items.append(MemoryItem(
                key="class_weak_areas",
                value=tuple(preference.class_weak_areas),
                metadata=metadata,
            ))
        return tuple(items)

    @staticmethod
    def _recent_sessions(
        user_id: int,
        *,
        exclude_conversation_id: int | None,
        limit: int,
        agent_types: tuple[str, ...] | None,
        reason: str,
    ) -> tuple[RecentSessionMemory, ...]:
        from app.core.extensions import db
        from domain.repositories.chat import SyncChatRepository

        rows = SyncChatRepository(db.session).get_recent_summarized_conversations(
            user_id,
            exclude_conversation_id=exclude_conversation_id,
            limit=limit,
            agent_types=agent_types,
        )
        return tuple(
            RecentSessionMemory(
                conversation_id=row.id,
                agent_type=row.agent_type,
                summary=row.summary.strip(),
                created_at=row.created_at,
                metadata=MemoryMetadata(
                    source=f"ai_conversation:{row.id}",
                    reason_included=reason,
                ),
            )
            for row in rows
            if row.summary and row.summary.strip()
        )

    @staticmethod
    def build_memory_context(
        user_id: int,
        user_role: str,
        conversation_id: int | None = None,
        *,
        profile_kind: str | None = None,
        include_recent_summaries: bool = True,
        recent_summary_agent_types: tuple[str, ...] | None = None,
        max_recent_summaries: int = 3,
        target_student_id: int | None = None,
        allow_target_student: bool = False,
    ) -> MemoryContext:
        """Build a structured ``MemoryContext`` for the given actor and policy.

        With ``profile_kind=None`` this reproduces the legacy role-based
        behavior. ``target_student_id`` only takes effect when
        ``allow_target_student`` is set and the actor is a teacher/admin; it
        redirects the profile subject but never the recent-summary owner.
        """
        try:
            resolved_profile_kind = profile_kind
            if resolved_profile_kind is None:
                if user_role == "student":
                    resolved_profile_kind = "student"
                elif user_role == "teacher":
                    resolved_profile_kind = "teacher"
                else:
                    resolved_profile_kind = "none"
            elif resolved_profile_kind == "actor":
                resolved_profile_kind = (
                    user_role if user_role in {"student", "teacher"} else "none"
                )

            student_profile: tuple[MemoryItem, ...] = ()
            teacher_preference: tuple[MemoryItem, ...] = ()

            can_use_target = (
                allow_target_student
                and target_student_id is not None
                and user_role in {"teacher", "admin"}
            )
            if can_use_target:
                resolved_profile_kind = "student"
                profile_subject_id = target_student_id
                profile_reason = "target student allowed by agent memory policy"
            else:
                profile_subject_id = user_id
                profile_reason = "actor profile allowed by memory policy"

            try:
                if resolved_profile_kind == "student":
                    student_profile = MemoryService._student_profile_items(
                        profile_subject_id,
                        profile_reason,
                    )
                elif resolved_profile_kind == "teacher":
                    teacher_preference = (
                        MemoryService._teacher_preference_items(
                            profile_subject_id,
                            profile_reason,
                        )
                    )
            except Exception as exc:
                logger.debug("Memory profile unavailable: %s", exc)

            recent_sessions: tuple[RecentSessionMemory, ...] = ()
            if include_recent_summaries and max_recent_summaries > 0:
                try:
                    recent_sessions = MemoryService._recent_sessions(
                        user_id,
                        exclude_conversation_id=conversation_id,
                        limit=max_recent_summaries,
                        agent_types=recent_summary_agent_types,
                        reason="recent summaries allowed by memory policy",
                    )
                except Exception as exc:
                    logger.debug(
                        "Recent conversation summaries unavailable: %s",
                        exc,
                    )

            return MemoryContext(
                student_profile=student_profile,
                teacher_preference=teacher_preference,
                recent_sessions=recent_sessions,
            )
        except Exception as exc:
            logger.debug(
                "Memory context unavailable (table may not exist yet): %s",
                exc,
            )
            return MemoryContext()

    @staticmethod
    def render_memory_context(context: MemoryContext) -> str:
        """Render a ``MemoryContext`` to the legacy prompt string.

        Only legacy labels and ordering are emitted; metadata, source keys and
        internal IDs are never exposed in the rendered text.
        """
        parts: list[str] = []

        student_labels = {
            "learning_summary": "Student Background",
            "error_patterns": "Error History",
            "weak_areas": "Weak Areas",
            "current_hint_level": "Previous Hints Given",
        }
        for item in context.student_profile:
            value = item.value
            if item.key == "weak_areas":
                value = ", ".join(value)
            parts.append(f"{student_labels[item.key]}: {value}")

        teacher_labels = {
            "style_notes": "Teacher Preferences",
            "class_weak_areas": "Class Weak Areas",
        }
        for item in context.teacher_preference:
            value = item.value
            if item.key == "class_weak_areas":
                value = ", ".join(value)
            parts.append(f"{teacher_labels[item.key]}: {value}")

        if context.recent_sessions:
            summaries = "\n".join(
                f"- {session.summary}" for session in context.recent_sessions
            )
            parts.append(f"Recent Sessions:\n{summaries}")

        return "\n".join(parts)

    @staticmethod
    def _policy_options(agent_name: str | None) -> dict:
        """Resolve an agent's ``MemoryPolicy`` into build_memory_context kwargs.

        Returns ``{}`` for no agent name or an unknown agent so the legacy
        role-based behavior is preserved.
        """
        if not agent_name:
            return {}

        from core.definitions import get_definition

        definition = get_definition(agent_name)
        if definition is None:
            return {}
        policy = definition.memory_policy
        return {
            "profile_kind": policy.profile_kind.value,
            "include_recent_summaries": policy.include_recent_summaries,
            "recent_summary_agent_types": tuple(
                sorted(policy.recent_summary_agent_types)
            ),
            "max_recent_summaries": policy.max_recent_summaries,
            "allow_target_student": policy.allow_target_student,
        }

    @staticmethod
    def get_memory_context(
        user_id: int,
        user_role: str,
        conversation_id: int = None,
        *,
        agent_name: str | None = None,
        target_student_id: int | None = None,
    ) -> str:
        """Backward-compatible string entry point for memory injection.

        With ``agent_name`` the registered ``AgentDefinition.memory_policy``
        decides profile kind, summary scope and target-student access. Without
        it the legacy role-based behavior is preserved. Delegates to
        ``build_memory_context`` + ``render_memory_context`` so callers keep the
        exact legacy prompt text.
        """
        options = MemoryService._policy_options(agent_name)
        context = MemoryService.build_memory_context(
            user_id,
            user_role,
            conversation_id,
            target_student_id=target_student_id,
            **options,
        )
        return MemoryService.render_memory_context(context)

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
            from ai.agents.config import AIConfig
            transcript_parts = []
            for m in early:
                content = getattr(m, "content", "")
                if content:
                    role = getattr(m, "type", "unknown")
                    transcript_parts.append(f"[{role}] {content[:300]}")
            if transcript_parts:
                from ai.llm.tiers import ModelTier
                llm = AIConfig.get_llm(tier=ModelTier.FAST)
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
