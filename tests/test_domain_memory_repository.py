"""Lifecycle contract for the governed memory item repository."""


def test_memory_repository_creates_candidate_and_promotes(db_session):
    from domain.repositories.memory import SyncMemoryRepository

    repo = SyncMemoryRepository(db_session)
    candidate = repo.create_candidate(
        subject_type="student",
        subject_id="7",
        memory_kind="profile",
        memory_key="learning_summary",
        value_json={"value": "Needs recursion practice"},
        source_type="conversation_summary",
        source_id="11",
        created_by_user_id=7,
        reason="student asked for help with recursion",
    )
    db_session.flush()

    assert candidate.status == "candidate"
    active = repo.promote(candidate.id)
    db_session.flush()

    assert active.status == "active"
    assert repo.active_for_subject("student", "7")[0].id == active.id


def test_promote_supersedes_conflicting_active_item(db_session):
    from domain.repositories.memory import SyncMemoryRepository

    repo = SyncMemoryRepository(db_session)
    first = repo.create_active(
        subject_type="teacher",
        subject_id="3",
        memory_kind="preference",
        memory_key="preferred_language",
        value_json={"value": "python"},
        source_type="manual",
    )
    second = repo.create_candidate(
        subject_type="teacher",
        subject_id="3",
        memory_kind="preference",
        memory_key="preferred_language",
        value_json={"value": "java"},
        source_type="generation",
    )
    db_session.flush()

    promoted = repo.promote(second.id)
    db_session.refresh(first)

    assert promoted.status == "active"
    assert first.status == "superseded"
    assert first.superseded_by_id == promoted.id


def test_suppressed_and_expired_items_are_not_active(db_session):
    from datetime import datetime, timedelta
    from domain.repositories.memory import SyncMemoryRepository

    repo = SyncMemoryRepository(db_session)
    suppressed = repo.create_active(
        subject_type="student",
        subject_id="9",
        memory_kind="profile",
        memory_key="learning_summary",
        value_json={"value": "hide me"},
        source_type="manual",
    )
    expired = repo.create_active(
        subject_type="student",
        subject_id="9",
        memory_kind="profile",
        memory_key="temporary_preference",
        value_json={"value": "also hide"},
        source_type="manual",
        expires_at=datetime.utcnow() - timedelta(days=1),
    )
    db_session.flush()
    repo.suppress(suppressed.id)

    assert repo.active_for_subject("student", "9") == []
