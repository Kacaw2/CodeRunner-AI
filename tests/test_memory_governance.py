from datetime import datetime


def test_memory_metadata_carries_priority_and_expiry():
    from ai.memory.context import MemoryMetadata

    expiry = datetime(2030, 1, 1)
    metadata = MemoryMetadata(
        source="student_profile:7",
        reason_included="tutor profile policy",
        priority=90,
        expires_at=expiry,
    )

    assert metadata.priority == 90
    assert metadata.expires_at == expiry


def test_every_agent_memory_policy_has_enforced_budget():
    from core.definitions import AGENT_DEFINITIONS

    expected = {
        "tutor": (4000, 1000),
        "generator": (3000, 750),
        "analytics": (3000, 750),
        "reviewer": (0, 0),
    }
    for name, definition in AGENT_DEFINITIONS.items():
        policy = definition.memory_policy
        assert (
            policy.max_memory_chars,
            policy.max_memory_tokens,
        ) == expected[name]


def test_selector_filters_expired_and_restricted_items():
    from datetime import datetime, timedelta
    from ai.memory.context import (
        MemoryContext,
        MemoryItem,
        MemoryMetadata,
        MemorySensitivity,
    )
    from ai.memory.governance import select_memory_context
    from core.definitions import MemoryPolicy, MemoryProfileKind

    now = datetime(2026, 6, 8, 12, 0, 0)
    context = MemoryContext(student_profile=(
        MemoryItem(
            key="learning_summary",
            value="keep me",
            metadata=MemoryMetadata(
                source="profile:1",
                reason_included="test",
                priority=80,
            ),
        ),
        MemoryItem(
            key="old_state",
            value="expired",
            metadata=MemoryMetadata(
                source="memory:old",
                reason_included="test",
                priority=100,
                expires_at=now - timedelta(seconds=1),
            ),
        ),
        MemoryItem(
            key="private_identity",
            value="restricted",
            metadata=MemoryMetadata(
                source="memory:restricted",
                reason_included="test",
                priority=100,
                sensitivity=MemorySensitivity.RESTRICTED,
            ),
        ),
    ))
    policy = MemoryPolicy(
        profile_kind=MemoryProfileKind.STUDENT,
        max_memory_chars=1000,
        max_memory_tokens=250,
    )

    result = select_memory_context(context, policy, now=now)

    assert result.rendered == "Student Background: keep me"
    reasons = {d.key: d.reason.value for d in result.decisions}
    assert reasons["old_state"] == "expired"
    assert reasons["private_identity"] == "sensitivity"


def test_selector_keeps_high_priority_items_under_budget():
    from ai.memory.context import MemoryContext, MemoryItem, MemoryMetadata
    from ai.memory.governance import select_memory_context
    from core.definitions import MemoryPolicy, MemoryProfileKind

    context = MemoryContext(student_profile=(
        MemoryItem(
            key="learning_summary",
            value="A" * 30,
            metadata=MemoryMetadata(
                source="profile:1",
                reason_included="test",
                priority=100,
            ),
        ),
        MemoryItem(
            key="error_patterns",
            value={"WA": 4},
            metadata=MemoryMetadata(
                source="profile:1",
                reason_included="test",
                priority=40,
            ),
        ),
    ))
    policy = MemoryPolicy(
        profile_kind=MemoryProfileKind.STUDENT,
        max_memory_chars=60,
        max_memory_tokens=100,
    )

    first = select_memory_context(context, policy)
    second = select_memory_context(context, policy)

    assert "Student Background" in first.rendered
    assert "Error History" not in first.rendered
    assert first.snapshot_hash == second.snapshot_hash
    assert len(first.snapshot_hash) == 64
    reasons = {d.key: d.reason.value for d in first.decisions}
    assert reasons["error_patterns"] in ("char_budget", "token_budget")


def test_prepare_memory_context_returns_render_and_audit(app, db_session):
    with app.app_context():
        from domain.models.user import User, UserRole
        from app.models.student_profile import StudentProfile
        from ai.memory.service import MemoryService

        user = User(
            username="memory_prepare",
            password="x",
            email="memory-prepare@test.com",
            role=UserRole.STUDENT,
        )
        db_session.add(user)
        db_session.flush()
        db_session.add(StudentProfile(
            student_id=user.id,
            learning_summary="Needs recursion practice.",
        ))
        db_session.commit()

        selection = MemoryService.prepare_memory_context(
            user.id,
            "student",
            agent_name="tutor",
        )

        assert "Needs recursion practice." in selection.rendered
        assert selection.rendered_chars > 0
        assert selection.snapshot_hash
        assert any(d.included for d in selection.decisions)


def _student_context(value="Needs recursion practice.", *, key="learning_summary",
                     source="profile:1", priority=80):
    from ai.memory.context import MemoryContext, MemoryItem, MemoryMetadata

    return MemoryContext(student_profile=(
        MemoryItem(
            key=key,
            value=value,
            metadata=MemoryMetadata(
                source=source,
                reason_included="test",
                priority=priority,
            ),
        ),
    ))


def test_zero_budget_includes_nothing():
    from ai.memory.governance import select_memory_context
    from core.definitions import MemoryPolicy, MemoryProfileKind

    context = _student_context()
    policy = MemoryPolicy(
        profile_kind=MemoryProfileKind.STUDENT,
        max_memory_chars=0,
        max_memory_tokens=0,
    )

    result = select_memory_context(context, policy)

    assert result.rendered == ""
    assert sum(1 for d in result.decisions if d.included) == 0
    non_empty = [d for d in result.decisions if d.reason.value != "empty"]
    assert non_empty
    assert all(d.reason.value in ("char_budget", "token_budget") for d in non_empty)


def test_exact_budget_boundary_is_included():
    from ai.memory.governance import select_memory_context, estimate_tokens
    from ai.memory.service import MemoryService
    from core.definitions import MemoryPolicy, MemoryProfileKind

    context = _student_context()
    rendered_single = MemoryService.render_memory_context(context)
    chars = len(rendered_single)
    tokens = estimate_tokens(rendered_single)

    policy = MemoryPolicy(
        profile_kind=MemoryProfileKind.STUDENT,
        max_memory_chars=chars,
        max_memory_tokens=tokens,
    )

    result = select_memory_context(context, policy)

    included = [d for d in result.decisions if d.included]
    assert len(included) == 1
    assert included[0].reason.value == "included"


def test_snapshot_hash_changes_when_included_value_changes():
    from ai.memory.governance import select_memory_context
    from core.definitions import MemoryPolicy, MemoryProfileKind

    policy = MemoryPolicy(
        profile_kind=MemoryProfileKind.STUDENT,
        max_memory_chars=4000,
        max_memory_tokens=1000,
    )

    first = select_memory_context(_student_context(value="alpha summary"), policy)
    second = select_memory_context(_student_context(value="beta summary"), policy)

    assert first.snapshot_hash != second.snapshot_hash


def test_audit_payload_does_not_include_memory_value():
    import json
    from ai.agents.runtime import _record_memory_selection
    from ai.memory.governance import select_memory_context
    from core.definitions import MemoryPolicy, MemoryProfileKind

    secret = "SECRET_MEMORY_VALUE"
    context = _student_context(value=secret)
    policy = MemoryPolicy(
        profile_kind=MemoryProfileKind.STUDENT,
        max_memory_chars=4000,
        max_memory_tokens=1000,
    )
    selection = select_memory_context(context, policy)

    class _Recorder:
        def __init__(self):
            self.calls = []

        def add_event(self, **kwargs):
            self.calls.append(kwargs)

        def add_artifact(self, **kwargs):
            self.calls.append(kwargs)

    recorder = _Recorder()
    _record_memory_selection(recorder, selection)

    assert recorder.calls
    serialized = json.dumps(recorder.calls, default=str)
    assert secret not in serialized
