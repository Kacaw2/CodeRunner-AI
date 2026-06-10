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

# memory_key -> legacy column for the materialized-view sync. Only keys that map
# cleanly to a stored column are written back; derived keys (e.g. ``weak_areas``,
# reconstructed from ``knowledge_map``) are intentionally omitted.
_TEACHER_LEGACY_KEYS = {
    "style_notes": "style_notes",
    "preferred_language": "preferred_language",
    "preferred_difficulty": "preferred_difficulty",
    "class_weak_areas": "class_weak_areas",
    "preferred_topics": "preferred_topics",
}
_STUDENT_LEGACY_KEYS = {
    "learning_summary": "learning_summary",
    "error_patterns": "error_patterns",
    "current_hint_level": "current_hint_level",
}


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


def sync_legacy_profile_from_active_items(subject_type: str, subject_id) -> None:
    """Mirror the subject's active governed items back onto the legacy table.

    Keeps ``StudentProfile`` / ``TeacherPreference`` usable as a compatibility
    materialized view. Only keys that governance has ever owned for this subject
    are touched: an active item sets its column, a suppressed/superseded one
    clears it to ``None``. Columns never governed are left alone so approving one
    candidate never wipes unrelated legacy data.
    """
    from sqlalchemy import select

    from app.core.extensions import db
    from domain.models.memory import MemoryItemRecord

    repo = SyncMemoryRepository(db.session)
    active_values = {
        item.memory_key: (item.value_json or {}).get("value")
        for item in repo.active_for_subject(subject_type, str(subject_id))
    }

    governed_keys = set(
        db.session.execute(
            select(MemoryItemRecord.memory_key).where(
                MemoryItemRecord.subject_type == subject_type,
                MemoryItemRecord.subject_id == str(subject_id),
            )
        ).scalars()
    )

    key_map = (
        _TEACHER_LEGACY_KEYS if subject_type == "teacher" else _STUDENT_LEGACY_KEYS
    )
    managed = {
        memory_key: attr
        for memory_key, attr in key_map.items()
        if memory_key in governed_keys
    }
    if not managed:
        return

    if subject_type == "teacher":
        from app.models.student_profile import TeacherPreference

        row = TeacherPreference.query.filter_by(teacher_id=int(subject_id)).first()
        if row is None:
            row = TeacherPreference(teacher_id=int(subject_id))
            db.session.add(row)
    else:
        from app.models.student_profile import StudentProfile

        row = StudentProfile.query.filter_by(student_id=int(subject_id)).first()
        if row is None:
            row = StudentProfile(student_id=int(subject_id))
            db.session.add(row)

    for memory_key, attr in managed.items():
        setattr(row, attr, active_values.get(memory_key))
    db.session.flush()
