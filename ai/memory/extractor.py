"""Deterministic governed-memory candidate extractors.

These extractors only read already-structured fields (generation request params,
generated-question metadata, a persisted conversation summary). They never call
an LLM, parse free-form private text, or read the vector store. Every extracted
value becomes a ``candidate`` item — never directly ``active`` — so a human
approve step is always required before it enters the prompt.
"""

from __future__ import annotations

from typing import Iterable

from core.hashing import canonical_json_hash
from domain.repositories.memory import SyncMemoryRepository


def _create_candidates(
    subject_type: str,
    subject_id: int,
    memory_kind: str,
    fields: Iterable[tuple[str, object]],
    *,
    source_type: str,
    source_id: str | None = None,
    created_by_user_id: int | None = None,
) -> int:
    """Create candidate items for ``fields``, skipping values that already
    exist as a candidate or active item for the subject (dedup by value hash)."""
    from app.core.extensions import db

    repo = SyncMemoryRepository(db.session)
    existing = {
        item.value_hash
        for item in repo.candidates_for_subject(subject_type, str(subject_id))
    }
    existing |= {
        item.value_hash
        for item in repo.active_for_subject(subject_type, str(subject_id))
    }

    created = 0
    for memory_key, value in fields:
        if value in (None, "", [], {}):
            continue
        value_json = {"value": value}
        if canonical_json_hash(value_json) in existing:
            continue
        repo.create_candidate(
            subject_type=subject_type,
            subject_id=str(subject_id),
            memory_kind=memory_kind,
            memory_key=memory_key,
            value_json=value_json,
            source_type=source_type,
            source_id=source_id,
            created_by_user_id=created_by_user_id,
        )
        created += 1

    if created:
        db.session.flush()
    return created


def extract_from_teacher_generation(
    *,
    teacher_id: int,
    request_params: dict,
    generated_question: dict,
) -> int:
    """Derive teacher preference candidates from a successful generation."""
    request_params = request_params or {}
    generated_question = generated_question or {}

    language = (
        generated_question.get("programming_language")
        or request_params.get("language")
    )
    difficulty = (
        generated_question.get("difficulty")
        or request_params.get("difficulty")
    )
    topic = request_params.get("topic")

    fields: list[tuple[str, object]] = []
    if language:
        fields.append(("preferred_language", language))
    if difficulty:
        fields.append(("preferred_difficulty", difficulty))
    if topic:
        fields.append(("preferred_topics", [topic]))

    return _create_candidates(
        "teacher",
        teacher_id,
        "preference",
        fields,
        source_type="generation",
        created_by_user_id=teacher_id,
    )


def extract_from_conversation_summary(
    *,
    user_id: int,
    user_role: str,
    conversation_id: int,
    summary: str,
) -> int:
    """Turn a persisted conversation summary into a learning_summary candidate."""
    text = (summary or "").strip()
    if not text:
        return 0

    subject_type = "student" if user_role == "student" else "teacher"
    return _create_candidates(
        subject_type,
        user_id,
        "profile",
        [("learning_summary", text)],
        source_type="conversation_summary",
        source_id=str(conversation_id),
        created_by_user_id=user_id,
    )
