"""Backfill and materialized-view sync between legacy profile tables and the
governed ``memory_items`` store.

Backfill turns existing ``StudentProfile`` / ``TeacherPreference`` rows into
``active`` governed items (idempotently, by value hash). Every governed value
is stored uniformly as ``{"value": <original>}`` so the read path can convert
items back to ``MemoryItem`` without per-key special-casing.
"""

from __future__ import annotations

from core.hashing import canonical_json_hash
from domain.repositories.memory import SyncMemoryRepository

_STUDENT_KIND = "profile"
_TEACHER_KIND = "preference"
_STUDENT_SOURCE = "legacy_student_profile"
_TEACHER_SOURCE = "legacy_teacher_preference"


def _student_fields(user_id: int) -> dict:
    from app.models.student_profile import StudentProfile

    profile = StudentProfile.query.filter_by(student_id=user_id).first()
    if profile is None:
        return {}

    fields: dict = {}
    if profile.learning_summary:
        fields["learning_summary"] = profile.learning_summary
    if profile.error_patterns:
        fields["error_patterns"] = dict(profile.error_patterns)
    weak_areas = [
        key
        for key, score in (profile.knowledge_map or {}).items()
        if score < 0.5
    ]
    if weak_areas:
        fields["weak_areas"] = weak_areas
    if profile.current_hint_level:
        fields["current_hint_level"] = dict(profile.current_hint_level)
    return fields


def _teacher_fields(user_id: int) -> dict:
    from app.models.student_profile import TeacherPreference

    preference = TeacherPreference.query.filter_by(teacher_id=user_id).first()
    if preference is None:
        return {}

    fields: dict = {}
    if preference.style_notes:
        fields["style_notes"] = preference.style_notes
    if preference.preferred_language:
        fields["preferred_language"] = preference.preferred_language
    if preference.preferred_difficulty:
        fields["preferred_difficulty"] = preference.preferred_difficulty
    if preference.class_weak_areas:
        fields["class_weak_areas"] = list(preference.class_weak_areas)
    if preference.preferred_topics:
        fields["preferred_topics"] = list(preference.preferred_topics)
    return fields


def backfill_user_memory_items(user_id: int, role: str) -> int:
    """Materialize legacy profile/preference rows into active governed items.

    Returns the number of newly-created items. Re-running is a no-op for values
    that already exist (deduplicated by canonical value hash).
    """
    from app.core.extensions import db

    if role == "student":
        subject_type, memory_kind, source_type = (
            "student",
            _STUDENT_KIND,
            _STUDENT_SOURCE,
        )
        fields = _student_fields(user_id)
    else:
        subject_type, memory_kind, source_type = (
            "teacher",
            _TEACHER_KIND,
            _TEACHER_SOURCE,
        )
        fields = _teacher_fields(user_id)

    if not fields:
        return 0

    repo = SyncMemoryRepository(db.session)
    existing_hashes = {
        item.value_hash
        for item in repo.active_for_subject(subject_type, str(user_id))
    }

    created = 0
    for memory_key, value in fields.items():
        value_json = {"value": value}
        if canonical_json_hash(value_json) in existing_hashes:
            continue
        repo.create_active(
            subject_type=subject_type,
            subject_id=str(user_id),
            memory_kind=memory_kind,
            memory_key=memory_key,
            value_json=value_json,
            source_type=source_type,
            created_by_user_id=user_id,
        )
        created += 1

    if created:
        db.session.flush()
    return created
