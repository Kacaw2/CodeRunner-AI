"""Governed memory item repository (sync SQLAlchemy session).

Owns the candidate -> active -> superseded/suppressed/expired lifecycle and the
value-hash dedup. ``promote()`` is the only path that supersedes a conflicting
active item; ``active_for_subject()`` lazily marks past-due items ``expired``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.hashing import canonical_json_hash
from core.timezone import now_china
from domain.models.memory import (
    ACTIVE,
    CANDIDATE,
    EXPIRED,
    REJECTED,
    SUPERSEDED,
    SUPPRESSED,
    MemoryItemRecord,
)


class SyncMemoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # -- creation -----------------------------------------------------------

    def _new_record(
        self,
        *,
        status: str,
        subject_type: str,
        subject_id: str,
        memory_kind: str,
        memory_key: str,
        value_json: dict,
        source_type: str,
        source_id: Optional[str] = None,
        source_json: Optional[dict] = None,
        reason: Optional[str] = None,
        confidence: float = 1.0,
        sensitivity: str = "internal",
        created_by_user_id: Optional[int] = None,
        expires_at: Optional[datetime] = None,
    ) -> MemoryItemRecord:
        record = MemoryItemRecord(
            subject_type=subject_type,
            subject_id=str(subject_id),
            memory_kind=memory_kind,
            memory_key=memory_key,
            value_json=value_json,
            value_hash=canonical_json_hash(value_json),
            status=status,
            confidence=confidence,
            sensitivity=sensitivity,
            source_type=source_type,
            source_id=source_id,
            source_json=source_json,
            reason=reason,
            created_by_user_id=created_by_user_id,
            expires_at=expires_at,
        )
        self.session.add(record)
        return record

    def create_candidate(self, **kwargs) -> MemoryItemRecord:
        return self._new_record(status=CANDIDATE, **kwargs)

    def create_active(self, **kwargs) -> MemoryItemRecord:
        return self._new_record(status=ACTIVE, **kwargs)

    # -- transitions --------------------------------------------------------

    def get(self, item_id: str) -> Optional[MemoryItemRecord]:
        return self.session.get(MemoryItemRecord, item_id)

    def promote(self, item_id: str) -> MemoryItemRecord:
        """Promote a candidate to active.

        Same subject/kind/key active items with a *different* value are
        superseded. A candidate whose value matches an existing active item is
        rejected as ``duplicate active value`` instead of creating a second
        active row.
        """
        item = self.session.get(MemoryItemRecord, item_id)
        if item is None:
            raise ValueError(f"memory item {item_id} not found")

        existing_active = self._active_for_key(
            item.subject_type,
            item.subject_id,
            item.memory_kind,
            item.memory_key,
        )

        for active in existing_active:
            if active.id == item.id:
                continue
            if active.value_hash == item.value_hash:
                item.status = REJECTED
                item.reason = "duplicate active value"
                self.session.flush()
                return item

        for active in existing_active:
            if active.id == item.id:
                continue
            active.status = SUPERSEDED
            active.superseded_by_id = item.id

        item.status = ACTIVE
        self.session.flush()
        return item

    def reject(self, item_id: str) -> MemoryItemRecord:
        item = self.session.get(MemoryItemRecord, item_id)
        if item is None:
            raise ValueError(f"memory item {item_id} not found")
        item.status = REJECTED
        self.session.flush()
        return item

    def suppress(self, item_id: str) -> MemoryItemRecord:
        item = self.session.get(MemoryItemRecord, item_id)
        if item is None:
            raise ValueError(f"memory item {item_id} not found")
        item.status = SUPPRESSED
        self.session.flush()
        return item

    # -- queries ------------------------------------------------------------

    def _active_for_key(
        self,
        subject_type: str,
        subject_id: str,
        memory_kind: str,
        memory_key: str,
    ) -> list[MemoryItemRecord]:
        return list(
            self.session.execute(
                select(MemoryItemRecord).where(
                    MemoryItemRecord.subject_type == subject_type,
                    MemoryItemRecord.subject_id == str(subject_id),
                    MemoryItemRecord.memory_kind == memory_kind,
                    MemoryItemRecord.memory_key == memory_key,
                    MemoryItemRecord.status == ACTIVE,
                )
            ).scalars()
        )

    def active_for_subject(
        self, subject_type: str, subject_id: str
    ) -> list[MemoryItemRecord]:
        rows = list(
            self.session.execute(
                select(MemoryItemRecord)
                .where(
                    MemoryItemRecord.subject_type == subject_type,
                    MemoryItemRecord.subject_id == str(subject_id),
                    MemoryItemRecord.status == ACTIVE,
                )
                .order_by(MemoryItemRecord.created_at)
            ).scalars()
        )
        now = now_china()
        live: list[MemoryItemRecord] = []
        expired_any = False
        for row in rows:
            if row.expires_at is not None and row.expires_at < now:
                row.status = EXPIRED
                expired_any = True
            else:
                live.append(row)
        if expired_any:
            self.session.flush()
        return live

    def has_items_for_subject(
        self, subject_type: str, subject_id: str
    ) -> bool:
        """True if any governed item (any status) exists for the subject.

        Once governance owns a subject, the read path must stop falling back to
        the legacy profile table even when zero items are currently ``active``
        (e.g. the only item was suppressed).
        """
        return (
            self.session.execute(
                select(MemoryItemRecord.id)
                .where(
                    MemoryItemRecord.subject_type == subject_type,
                    MemoryItemRecord.subject_id == str(subject_id),
                )
                .limit(1)
            ).first()
            is not None
        )

    def candidates_for_subject(
        self, subject_type: str, subject_id: str
    ) -> list[MemoryItemRecord]:
        return list(
            self.session.execute(
                select(MemoryItemRecord)
                .where(
                    MemoryItemRecord.subject_type == subject_type,
                    MemoryItemRecord.subject_id == str(subject_id),
                    MemoryItemRecord.status == CANDIDATE,
                )
                .order_by(MemoryItemRecord.created_at)
            ).scalars()
        )
