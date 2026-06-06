"""Combined MetaData for Alembic autogenerate during ORM collapse.

Flask-SQLAlchemy now owns the former shared tables. The runtime-neutral core
registry contributes only the remaining trace/eval case tables until Phase 2
ports those models into Flask as well.
"""

import importlib
import pkgutil

from sqlalchemy import MetaData


def _import_all_submodules(package_name: str) -> None:
    """Import package submodules so mapped tables register on metadata."""
    package = importlib.import_module(package_name)
    if not hasattr(package, "__path__"):
        return
    for mod in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{package_name}.{mod.name}")


def build_target_metadata() -> MetaData:
    _import_all_submodules("app.models")
    _import_all_submodules("core.db.models")

    from app.core.extensions import db
    from core.db.session import Base

    combined = MetaData()
    for table in db.metadata.tables.values():
        table.to_metadata(combined)
    for name, table in Base.metadata.tables.items():
        if name not in combined.tables:
            table.to_metadata(combined)
    return combined
