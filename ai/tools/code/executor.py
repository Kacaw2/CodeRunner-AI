"""Core code execution logic — no framework dependency."""


def execute_code_impl(
    code: str,
    language: str = "python",
    stdin_text: str = "",
    expected_output: str = "",
) -> dict:
    from app.services.executor_service import ExecutorService

    result = ExecutorService.run_code(
        code=code,
        language=language,
        stdin_text=stdin_text,
        expected_output=expected_output or None,
    )
    return {
        "status": result.get("status"),
        "stdout": (result.get("stdout") or "")[:2000],
        "stderr": (result.get("stderr") or "")[:1000],
        "time_ms": result.get("time_ms", 0),
    }
