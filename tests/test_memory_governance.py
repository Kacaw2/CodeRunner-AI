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
