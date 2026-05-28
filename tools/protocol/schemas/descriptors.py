"""Canonical tool descriptors — every MCP tool must declare one."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalPolicy(str, Enum):
    NONE = "none"
    TEACHER_REQUIRED = "teacher_required"
    ADMIN_REQUIRED = "admin_required"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 0
    backoff_ms: int = 500


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    version: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    error_schema: dict[str, Any] = field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    required_scopes: list[str] = field(default_factory=list)
    approval_policy: ApprovalPolicy = ApprovalPolicy.NONE
    timeout_ms: int = 30_000
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    server: str = ""

    def to_llm_schema(self) -> dict:
        """Convert to the format expected by LLM tool-calling APIs."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "risk_level": self.risk_level.value,
            "required_scopes": self.required_scopes,
            "approval_policy": self.approval_policy.value,
            "timeout_ms": self.timeout_ms,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }
