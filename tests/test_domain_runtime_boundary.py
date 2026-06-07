"""Runtime boundary guards for the shared domain package."""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_domain_package_does_not_import_app_layer():
    offenders: list[str] = []
    for path in (REPO_ROOT / "domain").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "app" or module.startswith("app."):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT).as_posix()}: from {module}"
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name == "app" or name.startswith("app."):
                        offenders.append(
                            f"{path.relative_to(REPO_ROOT).as_posix()}: import {name}"
                        )

    assert not offenders, "domain/ imports app layer:\n" + "\n".join(offenders)
