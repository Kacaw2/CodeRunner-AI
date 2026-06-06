# app/models/ai_conversation.py
"""Compatibility re-export.

The single ``AIConversation`` / ``AIMessage`` mappings now live in
``domain.models.chat`` (pure SQLAlchemy 2.0 on the shared ``DomainBase``
registry). This module only re-exports those symbols and re-enables the legacy
``.query`` property so not-yet-migrated Flask call sites keep working.
"""

from domain.models.chat import AIConversation, AIMessage
from app.models._query_compat import enable_legacy_query

enable_legacy_query(AIConversation)
enable_legacy_query(AIMessage)

__all__ = ["AIConversation", "AIMessage"]
