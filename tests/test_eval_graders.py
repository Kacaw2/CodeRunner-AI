"""Phase 5 / Task 7: grader protocol + deterministic graders.

Deterministic graders wrap the existing judge functions and emit a uniform
``GraderResult``. ``run_grader`` dispatches by the ``<family>.<name>`` type
prefix so the harness has one entry point.
"""


def test_deterministic_grader_passes_clean_response():
    from evals.graders.base import GraderResult
    from evals.graders.deterministic import run_deterministic_grader

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
    from evals.graders.deterministic import run_deterministic_grader

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
    from evals.graders.deterministic import run_deterministic_grader

    result = run_deterministic_grader("deterministic.does_not_exist", "x", {})

    assert result.passed is False
    assert result.grader_name == "does_not_exist"


def test_run_grader_dispatches_by_family_prefix():
    from evals.graders.base import run_grader

    result = run_grader(
        {"type": "deterministic.regex_absent", "pattern": "TOP_SECRET"},
        "a perfectly clean response",
        trace_id="trace-1",
    )

    assert result.passed is True
    assert result.grader_type == "deterministic"
    assert result.trace_id == "trace-1"


def test_run_grader_rejects_unknown_family():
    from evals.graders.base import run_grader

    result = run_grader({"type": "telepathy.vibes"}, "response")

    assert result.passed is False
    assert result.grader_type == "telepathy"
