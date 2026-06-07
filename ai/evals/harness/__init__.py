"""Unified agent execution harness (Phase 4, Task 3).

Owns a single logical trace per chat task / handoff chain and drives one or
more agents (single-agent path plus handoff loop) as execution units that write
spans into the harness-owned ambient trace.
"""

from ai.evals.harness.agent_harness import AgentHarness, AgentResult
from ai.evals.harness.eval_harness import (
    EvalHarness,
    EvalRunReport,
    EvalCaseResult,
)

__all__ = [
    "AgentHarness",
    "AgentResult",
    "EvalHarness",
    "EvalRunReport",
    "EvalCaseResult",
]
