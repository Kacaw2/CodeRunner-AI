"""Governed memory lifecycle API: listing and subject-scoped governance."""


def test_user_can_list_own_memory_items(client, mock_auth_student, db_session, student_user):
    from domain.repositories.memory import SyncMemoryRepository

    SyncMemoryRepository(db_session).create_active(
        subject_type="student",
        subject_id=str(student_user.id),
        memory_kind="profile",
        memory_key="learning_summary",
        value_json={"value": "Visible to owner"},
        source_type="manual",
    )
    db_session.commit()

    resp = client.get("/api/v1/ai/memory")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["items"][0]["memory_key"] == "learning_summary"


def test_user_can_suppress_own_memory_item(client, mock_auth_student, db_session, student_user):
    from domain.repositories.memory import SyncMemoryRepository

    item = SyncMemoryRepository(db_session).create_active(
        subject_type="student",
        subject_id=str(student_user.id),
        memory_kind="profile",
        memory_key="learning_summary",
        value_json={"value": "Forget me"},
        source_type="manual",
    )
    db_session.commit()

    resp = client.delete(f"/api/v1/ai/memory/{item.id}")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "suppressed"


def test_teacher_can_approve_own_candidate(client, mock_auth_teacher, db_session, teacher_user):
    from domain.repositories.memory import SyncMemoryRepository

    item = SyncMemoryRepository(db_session).create_candidate(
        subject_type="teacher",
        subject_id=str(teacher_user.id),
        memory_kind="preference",
        memory_key="preferred_language",
        value_json={"value": "java"},
        source_type="generation",
    )
    db_session.commit()

    resp = client.post(f"/api/v1/ai/memory/{item.id}/approve")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "active"


def test_student_cannot_suppress_other_student_memory(client, mock_auth_student, db_session):
    from domain.models.memory import MemoryItemRecord
    from domain.repositories.memory import SyncMemoryRepository

    item = SyncMemoryRepository(db_session).create_active(
        subject_type="student",
        subject_id="999999",
        memory_kind="profile",
        memory_key="learning_summary",
        value_json={"value": "Not yours"},
        source_type="manual",
    )
    db_session.commit()
    item_id = item.id

    resp = client.delete(f"/api/v1/ai/memory/{item_id}")

    assert resp.status_code == 403
    assert resp.get_json()["error"]["code"] == "memory_forbidden"
    db_session.expire_all()
    assert db_session.get(MemoryItemRecord, item_id).status == "active"


def test_teacher_cannot_operate_student_memory_without_class_scope(
    client, mock_auth_teacher, db_session
):
    from domain.models.memory import MemoryItemRecord
    from domain.repositories.memory import SyncMemoryRepository

    item = SyncMemoryRepository(db_session).create_candidate(
        subject_type="student",
        subject_id="888888",
        memory_kind="profile",
        memory_key="learning_summary",
        value_json={"value": "Student data"},
        source_type="manual",
    )
    db_session.commit()
    item_id = item.id

    resp = client.post(f"/api/v1/ai/memory/{item_id}/approve")

    assert resp.status_code == 403
    assert resp.get_json()["error"]["code"] == "memory_forbidden"
    db_session.expire_all()
    assert db_session.get(MemoryItemRecord, item_id).status == "candidate"
