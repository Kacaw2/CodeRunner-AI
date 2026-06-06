"""Alembic target metadata.

Every mapped class lives on the single ``DomainBase`` registry, so the target
metadata is just ``DomainBase.metadata`` once all model modules are imported.
There is no longer a second metadata to merge.
"""

import importlib
import pkgutil

from sqlalchemy import MetaData

from domain.base import DomainBase


def _import_all_submodules(package_name: str) -> None:
    """Import package submodules so mapped tables register on metadata."""
    package = importlib.import_module(package_name)
    if not hasattr(package, "__path__"):
        return
    for mod in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{package_name}.{mod.name}")


def build_target_metadata() -> MetaData:
    # Importing the model modules registers every table on the single
    # DomainBase metadata (shared by Flask's db.Model and the core Base alias).
    _import_all_submodules("app.models")
    _import_all_submodules("core.db.models")

    return DomainBase.metadata
