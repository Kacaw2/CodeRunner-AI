from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ai.memory.context import MemoryContext, MemoryItem, MemoryMetadata, RecentSessionMemory
from core.definitions import MemoryPolicy


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


class _Section(str, Enum):
    STUDENT_PROFILE = "student_profile"
    TEACHER_PREFERENCE = "teacher_preference"
    RECENT_SESSIONS = "recent_sessions"


# Section order constants — must stay in sync with _Section values
_SECTION_ORDER: dict[_Section, int] = {
    _Section.STUDENT_PROFILE: 0,
    _Section.TEACHER_PREFERENCE: 1,
    _Section.RECENT_SESSIONS: 2,
}


@dataclass
class _Candidate:
    section: _Section
    section_order: int
    key: str
    metadata: MemoryMetadata
    source_obj: MemoryItem | RecentSessionMemory
    rendered: str


def _render_context(ctx: MemoryContext) -> str:
    """Render a MemoryContext via MemoryService (lazy import to avoid circular deps)."""
    from ai.memory.service import MemoryService

    return MemoryService.render_memory_context(ctx)


def _render_single_candidate(candidate: _Candidate) -> str:
    """Render a single candidate by building a one-item MemoryContext."""
    if candidate.section is _Section.STUDENT_PROFILE:
        ctx = MemoryContext(student_profile=(candidate.source_obj,))
    elif candidate.section is _Section.TEACHER_PREFERENCE:
        ctx = MemoryContext(teacher_preference=(candidate.source_obj,))
    else:
        ctx = MemoryContext(recent_sessions=(candidate.source_obj,))
    return _render_context(ctx)


def select_memory_context(
    context: MemoryContext,
    policy: MemoryPolicy,
    *,
    now: datetime | None = None,
) -> MemorySelection:
    effective_now = now or datetime.now()

    # Flatten into candidates
    candidates: list[_Candidate] = []

    for item in context.student_profile:
        candidates.append(_Candidate(
            section=_Section.STUDENT_PROFILE,
            section_order=_SECTION_ORDER[_Section.STUDENT_PROFILE],
            key=item.key,
            metadata=item.metadata,
            source_obj=item,
            rendered="",
        ))

    for item in context.teacher_preference:
        candidates.append(_Candidate(
            section=_Section.TEACHER_PREFERENCE,
            section_order=_SECTION_ORDER[_Section.TEACHER_PREFERENCE],
            key=item.key,
            metadata=item.metadata,
            source_obj=item,
            rendered="",
        ))

    for session in context.recent_sessions:
        key = f"session:{session.conversation_id}"
        candidates.append(_Candidate(
            section=_Section.RECENT_SESSIONS,
            section_order=_SECTION_ORDER[_Section.RECENT_SESSIONS],
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
            # Budget gate. A non-positive max DISABLES memory (0 means "no
            # budget", never "unlimited"), so every non-empty candidate is
            # rejected with the corresponding budget reason. Comparison uses
            # ``>`` so an item that fits the budget exactly is still included.
            if policy.max_memory_chars <= 0 or used_chars + chars > policy.max_memory_chars:
                reason = MemoryFilterReason.CHAR_BUDGET
            elif policy.max_memory_tokens <= 0 or used_tokens + tokens > policy.max_memory_tokens:
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
        if c.section is _Section.STUDENT_PROFILE:
            student_items.append(c.source_obj)
        elif c.section is _Section.TEACHER_PREFERENCE:
            teacher_items.append(c.source_obj)
        else:
            recent_items.append(c.source_obj)

    rebuilt = MemoryContext(
        student_profile=tuple(student_items),
        teacher_preference=tuple(teacher_items),
        recent_sessions=tuple(recent_items),
    )

    rendered = _render_context(rebuilt)

    # Build snapshot payload from included items only (exclude reason_included)
    snapshot_items = []
    for c in included:
        m = c.metadata
        if isinstance(c.source_obj, MemoryItem):
            value = c.source_obj.value
        else:
            value = c.source_obj.summary
        snapshot_items.append({
            "source": m.source,
            "key": str(c.key),
            "value": value,
            "sensitivity": m.sensitivity.value,
            # Canonicalize to ISO 8601 so the hash is stable regardless of the
            # datetime object's tzinfo state (this hash is the Phase 5 replay
            # anchor); never rely on json default=str for the expiry.
            "expires_at": m.expires_at.isoformat() if m.expires_at else None,
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


