from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MemorySensitivity(str, Enum):
    INTERNAL = "internal"
    RESTRICTED = "restricted"


@dataclass(frozen=True)
class MemoryMetadata:
    source: str
    confidence: float = 1.0
    sensitivity: MemorySensitivity = MemorySensitivity.INTERNAL
    expires_at: datetime | None = None
    reason_included: str = ""


@dataclass(frozen=True)
class MemoryItem:
    key: str
    value: Any
    metadata: MemoryMetadata


@dataclass(frozen=True)
class RecentSessionMemory:
    conversation_id: int
    agent_type: str
    summary: str
    created_at: datetime | None
    metadata: MemoryMetadata


@dataclass(frozen=True)
class MemoryContext:
    student_profile: tuple[MemoryItem, ...] = field(default_factory=tuple)
    teacher_preference: tuple[MemoryItem, ...] = field(default_factory=tuple)
    recent_sessions: tuple[RecentSessionMemory, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not (
            self.student_profile
            or self.teacher_preference
            or self.recent_sessions
        )
