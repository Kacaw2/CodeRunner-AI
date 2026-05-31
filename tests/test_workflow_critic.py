"""Tests for WorkflowCritic narrow routing (Option A) and generation validation."""
from graph.critic import WorkflowCritic


def _valid_problem_output():
    return {
        "problem_data": {
            "title": "Two Sum",
            "description": "Return indices of the two numbers adding to target.",
            "test_cases": [{"input": "a", "expected_output": "b"},
                           {"input": "c", "expected_output": "d"}],
            "solution": "def f(): ...",
        }
    }


class TestGenerationValidation:
    def test_valid_generation_passes(self):
        c = WorkflowCritic()
        verdict = c.validate_step("generate_problem", "", _valid_problem_output())
        assert verdict["passed"] is True

    def test_missing_test_cases_fails(self):
        c = WorkflowCritic()
        out = _valid_problem_output()
        out["problem_data"]["test_cases"] = []
        verdict = c.validate_step("generate_problem", "", out)
        assert verdict["passed"] is False
        assert any("test case" in i.lower() for i in verdict["issues"])

    def test_reads_problem_data_field_not_only_response(self):
        # Regression: validator must read problem_data, not just "response".
        c = WorkflowCritic()
        verdict = c.validate_generation_output(_valid_problem_output())
        assert verdict["passed"] is True

    def test_generator_agent_call_routed_to_generation_validator(self):
        c = WorkflowCritic()
        out = _valid_problem_output()
        out["problem_data"]["solution"] = ""  # missing reference solution
        verdict = c.validate_step("agent_call", "generator", out)
        assert verdict["passed"] is False


class TestNarrowRoutingNoFalseReject:
    """dedup_check / quality_review / plain tool_call must fall through to pass."""

    def test_dedup_check_step_not_rejected(self):
        c = WorkflowCritic()
        # dedup output has no problem_data/test_cases — must NOT be graded.
        verdict = c.validate_step("dedup_check", "", {"is_duplicate": False, "similar_problems": []})
        assert verdict["passed"] is True

    def test_quality_review_step_not_rejected(self):
        c = WorkflowCritic()
        verdict = c.validate_step("quality_review", "", {"quality_score": 4, "passed": True})
        assert verdict["passed"] is True

    def test_plain_tool_call_not_rejected(self):
        c = WorkflowCritic()
        verdict = c.validate_step("tool_call", "", {"result": "anything"})
        assert verdict["passed"] is True

    def test_reviewer_agent_call_uses_review_validator(self):
        c = WorkflowCritic()
        short = c.validate_step("agent_call", "reviewer", {"response": "too short"})
        assert short["passed"] is False
        good = c.validate_step("agent_call", "reviewer",
                               {"response": "x" * 80})
        assert good["passed"] is True
