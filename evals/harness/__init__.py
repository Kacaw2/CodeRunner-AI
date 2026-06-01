"""Unified agent execution harness (Phase 4, Task 3).

Owns a single logical trace per chat task / handoff chain and drives one or
more agents (single-agent path plus handoff loop) as execution units that write
spans into the harness-owned ambient trace.
"""

from evals.harness.agent_harness import AgentHarness, AgentResult

__all__ = ["AgentHarness", "AgentResult"]
