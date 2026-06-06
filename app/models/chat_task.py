# app/models/chat_task.py
"""Compatibility re-export.

The single ``ChatTask`` mapping now lives in ``domain.models.chat`` (pure
SQLAlchemy 2.0 on the shared ``DomainBase`` registry). This module only
re-exports the symbol and re-enables the legacy ``.query`` property so
not-yet-migrated Flask call sites keep working.
"""

from domain.models.chat import ChatTask
from app.models._query_compat import enable_legacy_query

enable_legacy_query(ChatTask)

__all__ = ["ChatTask"]
