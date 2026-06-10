from datetime import datetime, timedelta


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
