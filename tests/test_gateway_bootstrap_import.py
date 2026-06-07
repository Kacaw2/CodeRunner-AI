"""Regression guards for the mcp_gateway process import path.

The gateway process imports the ToolRuntime bootstrap *before* any Flask app
exists. If importing a model (or anything under ``app.*``) instantiates the
Flask app at import time, a circular import crashes gateway startup:

    bootstrap._register_approval_handlers
      -> domain.models.mcp
      -> shared DomainBase without constructing a Flask application

These tests fail fast at the source level so we don't only discover it in a
Docker rebuild.
"""

import subprocess
import sys


def test_app_package_import_has_no_module_level_flask_app():
    import app as app_pkg

    assert not hasattr(app_pkg, "app"), (
        "app/__init__.py must not call create_app() at import time. The web "
        "process uses 'run:app'; a module-level app triggers a circular import "
        "when core.db.models is imported first (e.g. in the mcp_gateway "
        "process)."
    )


def test_domain_approval_model_imports_in_a_clean_interpreter():
    """Importing the approval model first must not crash on a circular import."""
    result = subprocess.run(
        [sys.executable, "-c",
         "import domain.models.mcp as m; "
         "assert m.McpToolApproval is not None; print('ok')"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"clean-interpreter import failed:\n{result.stderr}"
    )
    assert "ok" in result.stdout
