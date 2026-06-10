"""Runtime-neutral canonical hashing shared across domain and ai layers."""

from __future__ import annotations

import hashlib
import json


def canonical_json_hash(payload: object) -> str:
    """Stable sha256 over a canonical JSON encoding of ``payload``.

    Used both for memory-context snapshot hashing and for ``memory_items``
    value dedup, so equal values always produce the same hash regardless of
    key order or which layer computes it.
    """
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
