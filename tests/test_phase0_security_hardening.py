from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_compose_routes_web_execution_to_executor_service():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "\n  executor:\n" in compose
    assert "EXECUTOR_REMOTE_URL: http://executor:8300/run" in compose
    assert "EXECUTOR_API_TOKEN: ${EXECUTOR_API_TOKEN:-}" in compose
    assert 'USE_DOCKER: "false"' not in compose
    assert "executor_network:" in compose
    assert "internal: true" in compose


def test_root_compose_web_mounts_runtime_packages_when_using_bind_mounts():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    # Runtime packages are consolidated under the shared ``ai/`` package
    # (dc5c736); the bind mount surface is now app/core/ai plus tooling dirs.
    for package in [
        "app",
        "core",
        "ai",
        "scripts",
        "tests",
    ]:
        assert f"./{package}:/app/{package}:ro" in compose


def test_fastmcp_sdk_dependency_is_declared():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "mcp>=1.20.0" in requirements
