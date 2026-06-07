"""Remote-only Agent Runtime dispatcher contracts."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import agent_runtime_dispatcher as disp


def test_chat_dispatch_sends_remote_command():
    with patch.object(disp, "_dispatch_remote") as remote, patch.object(
        disp, "_mark_task_failed"
    ) as mark_failed:
        used = disp.dispatch_chat_task("task-4")

    assert used == "remote"
    remote.assert_called_once_with("task-4")
    mark_failed.assert_not_called()


def test_chat_dispatch_failure_marks_task_failed_without_fallback():
    with patch.object(
        disp, "_dispatch_remote", side_effect=RuntimeError("down")
    ), patch.object(disp, "_mark_task_failed") as mark_failed:
        used = disp.dispatch_chat_task("task-5")

    assert used == "remote"
    mark_failed.assert_called_once()


def test_workflow_dispatch_sends_remote_command():
    with patch.object(disp, "_dispatch_remote_workflow") as remote, patch.object(
        disp, "_mark_workflow_failed"
    ) as mark_failed:
        used = disp.dispatch_workflow("workflow-1")

    assert used == "remote"
    remote.assert_called_once_with("workflow-1")
    mark_failed.assert_not_called()


def test_workflow_dispatch_failure_marks_run_failed_without_fallback():
    with patch.object(
        disp, "_dispatch_remote_workflow", side_effect=RuntimeError("down")
    ), patch.object(disp, "_mark_workflow_failed") as mark_failed:
        used = disp.dispatch_workflow("workflow-2")

    assert used == "remote"
    mark_failed.assert_called_once()


def test_dispatch_remote_uses_signed_service_token():
    captured = {}

    def _fake_post(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        response = MagicMock()
        response.raise_for_status.return_value = None
        return response

    fake_httpx = MagicMock()
    fake_httpx.post.side_effect = _fake_post

    with patch.dict("sys.modules", {"httpx": fake_httpx}), patch(
        "core.auth.service_tokens.mint_service_token",
        return_value="signed-token",
    ) as mint:
        disp._dispatch_remote("task-9")

    assert "task-9:start" in captured["url"]
    authorization = captured["headers"]["Authorization"]
    assert authorization == "Bearer signed-token"
    mint.assert_called_once_with(
        subject="coderunner-web",
        task_id="task-9",
    )


def test_mode_configuration_defaults_to_remote():
    from core.config import get_settings

    assert get_settings().AGENT_RUNTIME_MODE == "remote"
