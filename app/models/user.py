# app/models/user.py
"""Compatibility re-export.

The single ``User`` / ``UserRole`` mapping now lives in ``domain.models.user``
(pure SQLAlchemy 2.0 on the shared ``DomainBase`` registry). This module only
re-exports those symbols and re-enables the legacy ``.query`` property so
not-yet-migrated Flask call sites (``User.query...``) keep working.
"""

from domain.models.user import User, UserRole
from app.models._query_compat import enable_legacy_query

enable_legacy_query(User)

__all__ = ["User", "UserRole"]
