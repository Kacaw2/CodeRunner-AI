"""Architecture guards for the remote-only Agent Runtime cutover."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

REMOVED_RUNTIME_FILES = (
    "workers/chat.py",
    "workers/workflow.py",
    "app/models/_query_compat.py",
    "app/models/user.py",
    "app/models/ai_conversation.py",
    "app/models/chat_task.py",
    "app/models/workflow.py",
    "app/models/eval_run.py",
    "core/db/models/agent_trace.py",
    "core/db/models/mcp_api_key.py",
    "core/db/models/mcp_audit_log.py",
    "core/db/models/mcp_approval.py",
)

PRODUCTION_ROOTS = (
    "app",
    "core",
    "agents",
    "graph",
    "workers",
    "evals",
    "mcp_gateway",
    "agent_runtime",
    "tools",
)

FORBIDDEN_IMPORTS = re.compile(
    r"from (?:app\.models\.(?:user|ai_conversation|chat_task|workflow|eval_run)"
    r"|core\.db\.models\.(?:agent_trace|mcp_api_key|mcp_audit_log|mcp_approval)) "
    r"import "
)


def test_dispatcher_is_remote_only_without_embedded_fallback():
    source = (ROOT / "app/services/agent_runtime_dispatcher.py").read_text(
        encoding="utf-8"
    )

    assert "workers.chat" not in source
    assert "workers.workflow" not in source
    assert "_submit_embedded" not in source
    assert "_probe_remote_ready" not in source
    assert '"shadow"' not in source
    assert '"embedded"' not in source


def test_remote_is_the_configuration_and_compose_default():
    config = (ROOT / "core/config.py").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert 'os.environ.get("AGENT_RUNTIME_MODE", "remote")' in config
    assert "AGENT_RUNTIME_MODE: ${AGENT_RUNTIME_MODE:-remote}" in compose
    assert "agent_runtime:\n        condition: service_healthy" in compose
    agent_runtime_block = re.search(
        r"(?ms)^  agent_runtime:\n(?P<body>.*?)(?=^  [a-zA-Z_]+:|\Z)",
        compose,
    ).group("body")
    assert "EXECUTOR_REMOTE_URL: http://executor:8300/run" in agent_runtime_block
    assert "EXECUTOR_API_TOKEN: ${EXECUTOR_API_TOKEN:-}" in agent_runtime_block
    assert "executor:\n        condition: service_healthy" in agent_runtime_block
    assert "      - executor_network" in agent_runtime_block


def test_worker_image_contains_the_shared_domain_package():
    dockerfile = (ROOT / "docker/Dockerfile.workers").read_text(encoding="utf-8")
    assert "COPY --chown=appuser:appuser domain/ ./domain/" in dockerfile
    assert "COPY --chown=appuser:appuser ai/ ./ai/" in dockerfile


def test_completed_slice_compatibility_files_are_deleted():
    remaining = [path for path in REMOVED_RUNTIME_FILES if (ROOT / path).exists()]
    assert remaining == []


def test_production_code_has_no_completed_slice_compatibility_imports():
    violations = []
    for root_name in PRODUCTION_ROOTS:
        for path in (ROOT / root_name).rglob("*.py"):
            match = FORBIDDEN_IMPORTS.search(path.read_text(encoding="utf-8"))
            if match:
                violations.append(
                    f"{path.relative_to(ROOT).as_posix()}: {match.group(0).strip()}"
                )

    assert violations == []
