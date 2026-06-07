"""Phase 5 / Task 7: grader protocol + deterministic graders.

Deterministic graders wrap the existing judge functions and emit a uniform
``GraderResult``. ``run_grader`` dispatches by the ``<family>.<name>`` type
prefix so the harness has one entry point.
"""


def test_deterministic_grader_passes_clean_response():
    from ai.evals.graders.base import GraderResult
    from ai.evals.graders.deterministic import run_deterministic_grader

    result = run_deterministic_grader(
        "deterministic.answer_leak",
        "Here is a small hint to get you started.",
        {"solution_keywords": ["def twoSum"]},
    )

    assert isinstance(result, GraderResult)
    assert result.passed is True
    assert result.grader_type == "deterministic"
    assert result.grader_name == "answer_leak"
    assert result.score == 1.0
    assert result.latency_ms >= 0


def test_deterministic_grader_detects_answer_leak():
    from ai.evals.graders.deterministic import run_deterministic_grader

    leaked = "```python\ndef twoSum(nums, target):\n    seen = {}\n    for i, n in enumerate(nums):\n        if target - n in seen:\n            return [seen[target - n], i]\n        seen[n] = i\n```"
    result = run_deterministic_grader(
        "deterministic.answer_leak",
        leaked,
        {"solution_keywords": ["def twoSum"]},
    )

    assert result.passed is False
    assert result.score == 0.0
    assert result.reason


def test_unknown_deterministic_grader_is_error_result():
    from ai.evals.graders.deterministic import run_deterministic_grader

    result = run_deterministic_grader("deterministic.does_not_exist", "x", {})

    assert result.passed is False
    assert result.grader_name == "does_not_exist"


def test_run_grader_dispatches_by_family_prefix():
    from ai.evals.graders.base import run_grader

    result = run_grader(
        {"type": "deterministic.regex_absent", "pattern": "TOP_SECRET"},
        "a perfectly clean response",
        trace_id="trace-1",
    )

    assert result.passed is True
    assert result.grader_type == "deterministic"
    assert result.trace_id == "trace-1"


def test_run_grader_rejects_unknown_family():
    from ai.evals.graders.base import run_grader

    result = run_grader({"type": "telepathy.vibes"}, "response")

    assert result.passed is False
    assert result.grader_type == "telepathy"


# ── Phase 6 / Task 7: non-deterministic grader families ──────────


def test_static_checks_python_parse_passes_on_valid_code():
    from ai.evals.graders.base import run_grader

    code = "```python\ndef f(x):\n    return x + 1\n```"
    result = run_grader({"type": "static_checks.python_parses"}, code)

    assert result.grader_type == "static_checks"
    assert result.passed is True


def test_static_checks_python_parse_fails_on_syntax_error():
    from ai.evals.graders.base import run_grader

    code = "```python\ndef f(x):\n    return x +\n```"
    result = run_grader({"type": "static_checks.python_parses"}, code)

    assert result.passed is False
    assert result.reason


def test_static_checks_flags_dangerous_imports():
    from ai.evals.graders.base import run_grader

    code = "```python\nimport os\nos.system('rm -rf /')\n```"
    result = run_grader({"type": "static_checks.no_dangerous_imports"}, code)

    assert result.passed is False
    assert "os" in result.reason


def test_unit_tests_grader_skips_without_sandbox():
    from ai.evals.graders.base import run_grader

    result = run_grader(
        {"type": "unit_tests.run", "tests": "assert f(1) == 2"},
        "```python\ndef f(x):\n    return x + 1\n```",
    )

    assert result.grader_type == "unit_tests"
    assert result.metadata.get("skipped") is True


def test_llm_judge_skips_without_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from ai.evals.graders.base import run_grader

    result = run_grader(
        {"type": "llm_judge.quality", "rubric": "Is the answer helpful?"},
        "A genuinely helpful and clear response.",
    )

    assert result.grader_type == "llm_judge"
    assert result.metadata.get("skipped") is True
