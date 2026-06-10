"""Lifecycle integration: legacy backfill, governed read path, extractor."""


def test_backfill_student_profile_creates_active_items(app, db_session, student_user):
    from app.models.student_profile import StudentProfile
    from ai.memory.lifecycle import backfill_user_memory_items
    from domain.repositories.memory import SyncMemoryRepository

    db_session.add(StudentProfile(
        student_id=student_user.id,
        learning_summary="Needs recursion practice",
        error_patterns={"WA": 2},
    ))
    db_session.commit()

    created = backfill_user_memory_items(student_user.id, "student")

    assert created >= 2
    rows = SyncMemoryRepository(db_session).active_for_subject(
        "student",
        str(student_user.id),
    )
    keys = {row.memory_key for row in rows}
    assert {"learning_summary", "error_patterns"} <= keys


def test_backfill_is_idempotent(app, db_session, teacher_user):
    from app.models.student_profile import TeacherPreference
    from ai.memory.lifecycle import backfill_user_memory_items

    db_session.add(TeacherPreference(
        teacher_id=teacher_user.id,
        preferred_language="python",
        style_notes="Concise prompts",
    ))
    db_session.commit()

    first = backfill_user_memory_items(teacher_user.id, "teacher")
    second = backfill_user_memory_items(teacher_user.id, "teacher")

    assert first >= 2
    assert second == 0


def test_suppressed_memory_item_no_longer_enters_prompt(app, db_session, student_user):
    from domain.repositories.memory import SyncMemoryRepository
    from ai.memory.service import MemoryService

    repo = SyncMemoryRepository(db_session)
    item = repo.create_active(
        subject_type="student",
        subject_id=str(student_user.id),
        memory_kind="profile",
        memory_key="learning_summary",
        value_json={"value": "Do not inject this"},
        source_type="manual",
    )
    db_session.flush()
    repo.suppress(item.id)
    db_session.commit()

    rendered = MemoryService.get_memory_context(
        student_user.id,
        "student",
        agent_name="tutor",
    )

    assert "Do not inject this" not in rendered
