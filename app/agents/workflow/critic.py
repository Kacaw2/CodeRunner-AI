"""
Critic / Validator — validates workflow step outputs and overall results.

Provides both rule-based and LLM-based validation capabilities that can be
registered as validation step handlers or called directly.
"""

import json
import logging

from app.agents.config import AIConfig

logger = logging.getLogger(__name__)


class WorkflowCritic:
    """Validates outputs of workflow steps against expected criteria."""

    def validate_generation_output(self, output: dict) -> dict:
        """Validate that a problem generation step produced a valid problem."""
        issues = []
        problem = output.get("response", "")

        if isinstance(problem, str):
            try:
                problem = json.loads(problem)
            except (json.JSONDecodeError, TypeError):
                pass

        if isinstance(problem, dict):
            required_fields = ["title", "description", "test_cases"]
            for field in required_fields:
                if not problem.get(field):
                    issues.append(f"Missing required field: {field}")

            test_cases = problem.get("test_cases", [])
            if len(test_cases) < 2:
                issues.append("Insufficient test cases (minimum 2)")

            if not problem.get("solution"):
                issues.append("Missing reference solution")
        else:
            issues.append("Output is not a structured problem JSON")

        return {
            "passed": len(issues) == 0,
            "issues": issues,
            "score": max(1, 5 - len(issues)),
        }

    def validate_review_output(self, output: dict) -> dict:
        """Validate that a code review step produced meaningful feedback."""
        issues = []
        response = output.get("response", "")

        if not response or len(response) < 50:
            issues.append("Review output too short to be meaningful")

        return {
            "passed": len(issues) == 0,
            "issues": issues,
            "score": 5 if not issues else 3,
        }

    def validate_dedup_output(self, output: dict) -> dict:
        """Validate deduplication check results."""
        result = output.get("result", {})
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                result = {}

        similar = result.get("similar_problems", [])
        is_duplicate = any(
            p.get("similarity", 0) > 0.8 for p in similar
        ) if isinstance(similar, list) else False

        return {
            "passed": not is_duplicate,
            "is_duplicate": is_duplicate,
            "similar_count": len(similar) if isinstance(similar, list) else 0,
            "issues": ["High similarity with existing problem detected"] if is_duplicate else [],
        }

    def validate_with_llm(self, output: dict, criteria: str) -> dict:
        """Use LLM to perform flexible quality validation."""
        from langchain_core.messages import HumanMessage

        output_str = json.dumps(output, ensure_ascii=False, default=str)[:2000]
        prompt = (
            f"Evaluate this output against the given criteria.\n\n"
            f"Criteria: {criteria}\n\n"
            f"Output:\n{output_str}\n\n"
            f"Respond with JSON: "
            f'{{"passed": true/false, "score": 1-5, "issues": [...], "suggestions": [...]}}'
        )

        try:
            llm = AIConfig.get_llm()
            response = llm.invoke([HumanMessage(content=prompt)])
            content = response.content or ""
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(content[start:end])
                result.setdefault("passed", result.get("score", 3) >= 3)
                return result
            return {"passed": True, "score": 3, "issues": ["Could not parse validator response"]}
        except Exception as e:
            logger.warning("LLM validation failed: %s", e)
            return {"passed": True, "score": 3, "issues": [f"Validation skipped: {e}"]}

    def validate_step(self, step_type: str, agent_type: str, output: dict, criteria: str = "") -> dict:
        """Route to the appropriate validator based on step context."""
        if step_type == "agent_call" and agent_type == "generator":
            return self.validate_generation_output(output)
        if step_type == "agent_call" and agent_type == "reviewer":
            return self.validate_review_output(output)
        if step_type == "tool_call" and "dedup" in (criteria or "").lower():
            return self.validate_dedup_output(output)
        if criteria:
            return self.validate_with_llm(output, criteria)
        return {"passed": True, "score": 5, "issues": []}
