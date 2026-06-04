"""Single combined MetaData for Alembic autogenerate across both ORM layers.

Some tables are mapped in BOTH the Flask-SQLAlchemy registry (app/models) and
the runtime SQLAlchemy registry (core/db/models). To give Alembic one
non-colliding view, the Flask definition is authoritative for any shared table
name; only core-exclusive tables are copied in on top.

This is a transitional bridge, not a merge of the two ORMs — see
docs/plans/active/2026-06-04-dual-orm-single-schema-source-plan.md.
"""

import importlib
import pkgutil

from sqlalchemy import MetaData


def _import_all_submodules(package_name: str) -> None:
    """Import every submodule of a package so its mapped tables register on the
    metadata. The core.db.models package __init__ does not import its modules,
    so the runtime Base.metadata stays empty until each module is imported."""
    package = importlib.import_module(package_name)
    if not hasattr(package, "__path__"):
        return
    for mod in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{package_name}.{mod.name}")


def build_target_metadata() -> MetaData:
    _import_all_submodules("app.models")  # populates db.metadata
    _import_all_submodules("core.db.models")  # populates Base.metadata

    from app.core.extensions import db
    from core.db.session import Base

    combined = MetaData()
    for table in db.metadata.tables.values():
        table.to_metadata(combined)
    for name, table in Base.metadata.tables.items():
        if name not in combined.tables:  # Flask definition wins on shared names
            table.to_metadata(combined)
    return combined
