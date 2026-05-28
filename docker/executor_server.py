"""Standalone sandbox executor HTTP service (Phase 0 — Option A).

Runs inside an isolated, non-root, network-restricted container. The web
container reaches it over HTTP via ``app/core/executor_client.run_code_remote``
(POST {code, language, stdin, expected_output, time_limit_sec}).

It loads the ``CodeExecutor`` implementation from ``executor.py`` *by file path*
so that importing it does NOT pull in the heavy ``app`` Flask package — no DB,
no ``create_app()`` side effects, and no SECRET_KEY startup gate. The only
runtime dependency beyond the standard library is Flask.

Native code execution inside this container is intentional and safe: container
isolation (``--network=none``, read-only rootfs, non-root user, mem/PID limits)
is what provides the sandbox. ``EXECUTOR_ALLOW_NATIVE=true`` is therefore set
for this process so the loaded executor actually runs code.
"""

import importlib.util
import logging
import os

from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("executor_server")

# Path to the CodeExecutor implementation, copied into the image.
_EXECUTOR_IMPL_PATH = os.getenv("EXECUTOR_IMPL_PATH", "/opt/executor/executor.py")
# Optional shared secret; when set the web side sends it as X-EXECUTOR-TOKEN.
_TOKEN = os.getenv("EXECUTOR_API_TOKEN")

# This process *is* the sandbox, so native execution is permitted here.
os.environ.setdefault("EXECUTOR_ALLOW_NATIVE", "true")


def _load_executor():
    spec = importlib.util.spec_from_file_location("executor_impl", _EXECUTOR_IMPL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load executor implementation at {_EXECUTOR_IMPL_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CodeExecutor()


_executor = _load_executor()
app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/run")
def run():
    if _TOKEN and request.headers.get("X-EXECUTOR-TOKEN") != _TOKEN:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    code = data.get("code", "") or ""
    language = data.get("language", "c") or "c"
    stdin = data.get("stdin") or ""
    expected_output = data.get("expected_output")
    time_limit_sec = data.get("time_limit_sec", 2.0) or 2.0

    try:
        result = _executor.run_code(
            code=code,
            language=language,
            stdin=stdin,
            expected_output=expected_output,
            time_limit_sec=time_limit_sec,
        )
    except Exception as e:  # never leak a stack trace to the caller
        logger.error("Execution failed: %s", e, exc_info=True)
        return jsonify({
            "status": "SYSTEM_ERROR",
            "passed": False,
            "stdout": "",
            "stderr": "",
            "compile_log": "",
            "time_ms": 0,
            "expected_match": None,
            "error_message": "Execution failed",
        }), 200

    # The remote client maps result["expected_match"]; CodeExecutor returns
    # "passed" but not always expected_match, so derive it for compatibility.
    if "expected_match" not in result:
        result["expected_match"] = (
            result.get("passed") if expected_output is not None else None
        )
    return jsonify(result)


if __name__ == "__main__":
    port = int(os.getenv("EXECUTOR_PORT", "8300"))
    app.run(host="0.0.0.0", port=port)
