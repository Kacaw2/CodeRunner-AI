"""Legacy ``.query`` compatibility shim for domain-migrated models.

A pure-SQLAlchemy-2.0 model defined under ``domain/`` has no Flask-SQLAlchemy
``Model.query`` property. Not-yet-migrated Flask call sites still use
``User.query...``. ``enable_legacy_query`` installs Flask-SQLAlchemy's scoped
``query_property()`` onto such a class so those call sites keep working during
the migration. It does NOT define or alter the mapped class.
"""

from app.core.extensions import db


def enable_legacy_query(model_class: type) -> type:
    """Attach ``db.session``-backed ``.query`` to a domain-mapped class.

    Idempotent: re-attaching the query property is harmless.
    """
    model_class.query = db.session.query_property()
    return model_class
