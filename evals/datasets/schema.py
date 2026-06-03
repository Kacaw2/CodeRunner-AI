"""Eval dataset case schema (Phase 5, Task 5).

Canonical typed representation of an eval case. Cases are stored as JSON under
``evals/datasets/<case_type>/<suite>.json`` and parsed into these dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CASE_TYPES = ("golden", "hidden", "regression", "production_failure")

# Maps the on-disk directory name to its canonical case_type. The directory is
# pluralized for production failures; the case_type stays singular.
DIR_TO_CASE_TYPE = {
    "golden": "golden",
    "hidden": "hidden",
    "regression": "regression",
    "production_failures": "production_failure",
}
CASE_TYPE_TO_DIR = {v: k for k, v in DIR_TO_CASE_TYPE.items()}

DEFAULT_BUDGET: dict[str, Any] = {
    "max_tokens": 2048,
    "max_tool_calls": 5,
    "timeout_seconds": 90,
    "max_cost_cny": 0.25,
}


@dataclass
class EvalCaseInput:
    message: str
    user_id: int = 1
    user_role: str = "student"
    agent_type: str = "tutor"
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict, *, agent_type: str = "tutor") -> "EvalCaseInput":
        return cls(
            message=data.get("message", ""),
            user_id=data.get("user_id", 1),
            user_role=data.get("user_role", "student"),
            agent_type=data.get("agent_type", agent_type),
            context=dict(data.get("context") or {}),
        )

    def to_dict(self) -> dict:
        return {
            "message": self.message,
            "user_id": self.user_id,
            "user_role": self.user_role,
            "agent_type": self.agent_type,
            "context": self.context,
        }


@dataclass
class GraderSpec:
    type: str
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "GraderSpec":
        params = {k: v for k, v in data.items() if k != "type"}
        return cls(type=data.get("type", ""), params=params)

    def to_dict(self) -> dict:
        return {"type": self.type, **self.params}


@dataclass
class EvalCase:
    id: str
    case_type: str
    suite: str
    agent_type: str
    input: EvalCaseInput
    category: str = ""
    budget: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_BUDGET))
    graders: list[GraderSpec] = field(default_factory=list)
    expected_behavior: str = ""
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict, *, case_type: str, suite: str) -> "EvalCase":
        agent_type = data.get("agent_type") or (data.get("input") or {}).get("agent_type", "tutor")
        return cls(
            id=data["id"],
            case_type=data.get("case_type", case_type),
            suite=data.get("suite", suite),
            agent_type=agent_type,
            input=EvalCaseInput.from_dict(data.get("input") or {}, agent_type=agent_type),
            category=data.get("category", ""),
            budget=dict(data.get("budget") or DEFAULT_BUDGET),
            graders=[GraderSpec.from_dict(g) for g in (data.get("graders") or [])],
            expected_behavior=data.get("expected_behavior", ""),
            description=data.get("description", ""),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "case_type": self.case_type,
            "suite": self.suite,
            "category": self.category,
            "agent_type": self.agent_type,
            "input": self.input.to_dict(),
            "budget": self.budget,
            "graders": [g.to_dict() for g in self.graders],
            "expected_behavior": self.expected_behavior,
            "description": self.description,
        }
