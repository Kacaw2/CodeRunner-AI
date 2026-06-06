"""3-state dispatcher: embedded (default), shadow, and remote routing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import agent_runtime_dispatcher as disp


@pytest.fixture()
def fake_app():
    return object()


def test_default_mode_is_embedded(fake_app):
    with patch.object(disp, "_mode", return_value="embedded"), \
         patch("workers.chat.submit_chat_task") as submit:
        used = disp.dispatch_chat_task("task-1", fake_app)

    assert used == "embedded"
    submit.assert_called_once_with("task-1", fake_app)


def test_embedded_calls_worker_via_module_attr(fake_app):
    """patch('workers.chat.submit_chat_task') must intercept embedded dispatch."""
    with patch.object(disp, "_mode", return_value="embedded"), \
         patch("workers.chat.submit_chat_task") as submit:
        disp.dispatch_chat_task("task-2", fake_app)
    submit.assert_called_once()


def test_shadow_runs_embedded_and_probes_remote(fake_app):
    with patch.object(disp, "_mode", return_value="shadow"), \
         patch("workers.chat.submit_chat_task") as submit, \
         patch.object(disp, "_probe_remote_ready", return_value=True) as probe, \
         patch.object(disp, "_dispatch_remote") as remote:
        used = disp.dispatch_chat_task("task-3", fake_app)

    assert used == "shadow"
    submit.assert_called_once_with("task-3", fake_app)  # embedded still executes
    probe.assert_called_once()                          # readiness verified
    remote.assert_not_called()                          # no second execution


def test_remote_sends_signed_command_and_skips_embedded(fake_app):
    with patch.object(disp, "_mode", return_value="remote"), \
         patch("workers.chat.submit_chat_task") as submit, \
         patch.object(disp, "_dispatch_remote") as remote, \
         patch.object(disp, "_mark_task_failed") as mark_failed:
        used = disp.dispatch_chat_task("task-4", fake_app)

    assert used == "remote"
    remote.assert_called_once_with("task-4")
    submit.assert_not_called()      # embedded worker NOT invoked in remote mode
    mark_failed.assert_not_called()


def test_remote_dispatch_failure_marks_task_failed_no_fallback(fake_app):
    with patch.object(disp, "_mode", return_value="remote"), \
         patch("workers.chat.submit_chat_task") as submit, \
         patch.object(disp, "_dispatch_remote", side_effect=RuntimeError("down")), \
         patch.object(disp, "_mark_task_failed") as mark_failed:
        used = disp.dispatch_chat_task("task-5", fake_app)

    assert used == "remote"
    mark_failed.assert_called_once()
    # Critical: no silent fallback to embedded execution.
    submit.assert_not_called()


def test_dispatch_remote_uses_signed_service_token():
    """The remote command carries a signed bearer token bound to the task."""
    captured = {}

    def _fake_post(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        return resp

    fake_httpx = MagicMock()
    fake_httpx.post.side_effect = _fake_post

    with patch.dict("sys.modules", {"httpx": fake_httpx}):
        disp._dispatch_remote("task-9")

    assert "task-9:start" in captured["url"]
    auth = captured["headers"]["Authorization"]
    assert auth.startswith("Bearer ")

    # The token verifies under the dedicated audience and is bound to the task.
    from core.auth.service_tokens import verify_service_token

    claims = verify_service_token(auth.split(" ", 1)[1], expected_task_id="task-9")
    assert claims["task_id"] == "task-9"


def test_mode_reads_config_default(monkeypatch):
    """With nothing patched, _mode falls back to the configured default."""
    from core.config import get_settings

    mode = (get_settings().AGENT_RUNTIME_MODE or "embedded").strip().lower()
    assert disp._mode() == mode
