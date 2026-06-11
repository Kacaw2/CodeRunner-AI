"""Governed memory item mapping on the single shared DomainBase registry.

``memory_items`` is the item-level, candidate/active/superseded/suppressed/
expired governance object that replaces the unconditionally-overwritten
aggregate profile fields as the source of prompt-injected long-term memory.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from domain.base import DomainBase

_CHINA_TZ = timezone(timedelta(hours=8))


def _now_china() -> datetime:
    return datetime.now(_CHINA_TZ).replace(tzinfo=None)


def _uuid() -> str:
    return str(uuid.uuid4())


# Lifecycle status enum values.
ACTIVE = "active"
CANDIDATE = "candidate"
REJECTED = "rejected"
SUPERSEDED = "superseded"
SUPPRESSED = "suppressed"
EXPIRED = "expired"


class MemoryItemRecord(DomainBase):
    __tablename__ = "memory_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    subject_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    memory_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    memory_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    sensitivity: Mapped[str] = mapped_column(
        String(30), nullable=False, default="internal"
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    source_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    superseded_by_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now_china
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now_china, onupdate=_now_china
    )


__all__ = [
    "MemoryItemRecord",
    "ACTIVE",
    "CANDIDATE",
    "REJECTED",
    "SUPERSEDED",
    "SUPPRESSED",
    "EXPIRED",
]
