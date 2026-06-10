from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ai.memory.context import MemoryContext, MemoryItem, RecentSessionMemory


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def canonical_snapshot_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class MemoryFilterReason(str, Enum):
    INCLUDED = "included"
    EMPTY = "empty"
    EXPIRED = "expired"
    SENSITIVITY = "sensitivity"
    CHAR_BUDGET = "char_budget"
    TOKEN_BUDGET = "token_budget"


@dataclass(frozen=True)
class MemoryDecision:
    source: str
    key: str
    included: bool
    reason: MemoryFilterReason
    rendered_chars: int
    estimated_tokens: int
    priority: int


@dataclass(frozen=True)
class MemorySelection:
    context: MemoryContext
    rendered: str
    decisions: tuple[MemoryDecision, ...]
    rendered_chars: int
    estimated_tokens: int
    snapshot_hash: str


# Section order constants
_SECTION_STUDENT = 0
_SECTION_TEACHER = 1
_SECTION_RECENT = 2


@dataclass
class _Candidate:
    section: str  # "student_profile" | "teacher_preference" | "recent_sessions"
    section_order: int
    key: str
    metadata: object  # MemoryMetadata
    source_obj: object  # MemoryItem or RecentSessionMemory
    rendered: str


def _render_single_candidate(candidate: _Candidate) -> str:
    """Render a single candidate by building a one-item MemoryContext."""
    from ai.memory.service import MemoryService

    if candidate.section == "student_profile":
        ctx = MemoryContext(student_profile=(candidate.source_obj,))
    elif candidate.section == "teacher_preference":
        ctx = MemoryContext(teacher_preference=(candidate.source_obj,))
    else:
        ctx = MemoryContext(recent_sessions=(candidate.source_obj,))
    return MemoryService.render_memory_context(ctx)


def select_memory_context(
    context: MemoryContext,
    policy,
    *,
    now: datetime | None = None,
) -> MemorySelection:
    effective_now = now or datetime.now()

    # Flatten into candidates
    candidates: list[_Candidate] = []

    for item in context.student_profile:
        candidates.append(_Candidate(
            section="student_profile",
            section_order=_SECTION_STUDENT,
            key=item.key,
            metadata=item.metadata,
            source_obj=item,
            rendered="",
        ))

    for item in context.teacher_preference:
        candidates.append(_Candidate(
            section="teacher_preference",
            section_order=_SECTION_TEACHER,
            key=item.key,
            metadata=item.metadata,
            source_obj=item,
            rendered="",
        ))

    for session in context.recent_sessions:
        key = f"session:{session.conversation_id}"
        candidates.append(_Candidate(
            section="recent_sessions",
            section_order=_SECTION_RECENT,
            key=key,
            metadata=session.metadata,
            source_obj=session,
            rendered="",
        ))

    # Sort by (-priority, section_order, source, key) before rendering
    candidates.sort(key=lambda c: (
        -c.metadata.priority,
        c.section_order,
        c.metadata.source,
        str(c.key),
    ))

    # Iterate and decide
    decisions: list[MemoryDecision] = []
    included: list[_Candidate] = []
    used_chars = 0
    used_tokens = 0

    for c in candidates:
        # Determine pre-render filter reasons first (EXPIRED, SENSITIVITY)
        # to avoid rendering items with unknown keys that would KeyError.
        if (
            c.metadata.expires_at is not None
            and c.metadata.expires_at <= effective_now
        ):
            # Assign zero cost for non-rendered items
            decisions.append(MemoryDecision(
                source=c.metadata.source,
                key=str(c.key),
                included=False,
                reason=MemoryFilterReason.EXPIRED,
                rendered_chars=0,
                estimated_tokens=0,
                priority=c.metadata.priority,
            ))
            continue

        if c.metadata.sensitivity not in policy.allowed_sensitivities:
            decisions.append(MemoryDecision(
                source=c.metadata.source,
                key=str(c.key),
                included=False,
                reason=MemoryFilterReason.SENSITIVITY,
                rendered_chars=0,
                estimated_tokens=0,
                priority=c.metadata.priority,
            ))
            continue

        # Now safe to render
        c.rendered = _render_single_candidate(c)
        chars = len(c.rendered)
        tokens = estimate_tokens(c.rendered)

        # Determine reason (EMPTY → budget → INCLUDED)
        if c.rendered.strip() == "":
            reason = MemoryFilterReason.EMPTY
        else:
            # Budget gate (only when max > 0; 0 means unlimited)
            if policy.max_memory_chars > 0 and used_chars + chars > policy.max_memory_chars:
                reason = MemoryFilterReason.CHAR_BUDGET
            elif policy.max_memory_tokens > 0 and used_tokens + tokens > policy.max_memory_tokens:
                reason = MemoryFilterReason.TOKEN_BUDGET
            else:
                reason = MemoryFilterReason.INCLUDED

        included_flag = reason is MemoryFilterReason.INCLUDED
        if included_flag:
            included.append(c)
            used_chars += chars
            used_tokens += tokens

        decisions.append(MemoryDecision(
            source=c.metadata.source,
            key=str(c.key),
            included=included_flag,
            reason=reason,
            rendered_chars=chars,
            estimated_tokens=tokens,
            priority=c.metadata.priority,
        ))

    # Rebuild MemoryContext from included candidates, preserving section order
    # We need to restore the original section order (student, teacher, recent)
    # while using the included sort order within each section
    student_items: list[MemoryItem] = []
    teacher_items: list[MemoryItem] = []
    recent_items: list[RecentSessionMemory] = []

    for c in included:
        if c.section == "student_profile":
            student_items.append(c.source_obj)
        elif c.section == "teacher_preference":
            teacher_items.append(c.source_obj)
        else:
            recent_items.append(c.source_obj)

    rebuilt = MemoryContext(
        student_profile=tuple(student_items),
        teacher_preference=tuple(teacher_items),
        recent_sessions=tuple(recent_items),
    )

    from ai.memory.service import MemoryService
    rendered = MemoryService.render_memory_context(rebuilt)

    # Build snapshot payload from included items only (exclude reason_included)
    snapshot_items = []
    for c in included:
        m = c.metadata
        snapshot_items.append({
            "source": m.source,
            "key": str(c.key),
            "value": c.source_obj.value if hasattr(c.source_obj, "value") else getattr(c.source_obj, "summary", None),
            "sensitivity": m.sensitivity.value,
            "expires_at": m.expires_at,
        })

    snapshot_hash = canonical_snapshot_hash({"items": snapshot_items})

    return MemorySelection(
        context=rebuilt,
        rendered=rendered,
        decisions=tuple(decisions),
        rendered_chars=len(rendered),
        estimated_tokens=estimate_tokens(rendered),
        snapshot_hash=snapshot_hash,
    )
