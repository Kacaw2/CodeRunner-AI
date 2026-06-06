"""Architecture guard: keep Phase 1 cleanup from regressing.

Phase 1 (commit f1f0a9f) deleted the old FastAPI Agent Host, the
``ai_proxy`` HTTP shim, the ``agent_client`` SDK, and the standalone
``workers`` task runner / compose service. These tests scan live runtime
source + config (NOT docs, NOT git history) and fail if any of that
machinery reappears as real code or configuration.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# Forbidden tokens are split so this guard file does not match itself when the
# token scan happens to include the tests directory. (The scan also explicitly
# excludes the tests dir, so this is belt-and-suspenders.)
FORBIDDEN = (
    "app.api.v1" + ".agents",
    "app.services." + "agent_client",
    "app.api.v1." + "ai_proxy",
    "USE_AGENT" + "_HOST_PROXY",
    "workers." + "task_runner",
)

# Runtime code/config roots to scan. Docs and git history are intentionally
# excluded.
SCAN_ROOTS = (
    "app",
    "core",
    "agents",
    "graph",
    "workers",
    "evals",
    "mcp_gateway",
    "agent_runtime",  # may not exist yet; skipped if absent
)

# Only scan real source/config text files.
TEXT_SUFFIXES = {
    ".py",
    ".yaml",
    ".yml",
    ".toml",
    ".cfg",
    ".ini",
}

# File names (not suffix-based) that should also be scanned.
TEXT_NAME_PREFIXES = (
    ".env",
    "Dockerfile",
)

# Directory names to skip anywhere in the tree.
SKIP_DIR_NAMES = {
    "__pycache__",
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".pytest_cache",
    "docs",
}

# These guard test files contain the FORBIDDEN substrings as data; never scan
# them as if they were production source.
GUARD_TEST_FILES = {
    Path(__file__).resolve(),
}


def _is_scannable(path: Path) -> bool:
    """Return True if ``path`` is a real source/config text file we should scan."""
    if path.resolve() in GUARD_TEST_FILES:
        return False
    for part in path.parts:
        if part in SKIP_DIR_NAMES:
            return False
    if path.suffix in TEXT_SUFFIXES:
        return True
    name = path.name
    return any(name.startswith(prefix) for prefix in TEXT_NAME_PREFIXES)


def _iter_scan_files():
    for root_name in SCAN_ROOTS:
        root = REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and _is_scannable(path):
                yield path
    compose = REPO_ROOT / "compose.yaml"
    if compose.exists():
        yield compose


def test_forbidden_tokens_absent_from_runtime_source():
    offenders: list[str] = []
    for path in _iter_scan_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for token in FORBIDDEN:
            if token in text:
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel}: {token}")
    assert not offenders, (
        "Phase 1 forbidden tokens reappeared in live source/config:\n"
        + "\n".join(offenders)
    )


def test_old_agents_package_has_no_source():
    # Stale compiled .pyc may linger under __pycache__; absence is judged by
    # real .py SOURCE files only.
    agents_dir = REPO_ROOT / "app" / "api" / "v1" / "agents"
    if not agents_dir.exists():
        return
    py_sources = [p for p in agents_dir.rglob("*.py")]
    rels = [p.relative_to(REPO_ROOT).as_posix() for p in py_sources]
    assert not py_sources, (
        "app/api/v1/agents/ still contains Python source files: " + ", ".join(rels)
    )


def test_old_source_files_removed():
    removed = (
        "app/services/agent_client.py",
        "app/api/v1/ai_proxy.py",
        "workers/task_runner.py",
        "workers/__main__.py",
    )
    still_present = [rel for rel in removed if (REPO_ROOT / rel).exists()]
    assert not still_present, (
        "Phase 1 source files should be deleted but still exist: "
        + ", ".join(still_present)
    )


def test_compose_has_no_workers_service():
    compose = REPO_ROOT / "compose.yaml"
    assert compose.exists(), "compose.yaml not found at repo root"
    data = yaml.safe_load(compose.read_text(encoding="utf-8"))
    services = (data or {}).get("services", {}) or {}
    assert "workers" not in services, (
        "compose.yaml still defines a top-level 'workers' service; "
        f"current services: {sorted(services)}"
    )
