"""
Workflow framework for multi-agent coordination (Phase 2).

Provides a generic, structured workflow engine that:
- Decomposes user goals into step sequences via LLM planning
- Executes steps by dispatching to registered agents/tools
- Validates outputs and supports retry/human-gate patterns
- Tracks all state in WorkflowRun/WorkflowStep DB models

Usage:
    from agent_host.workflow import SupervisorAgent, WorkflowEngine

    supervisor = SupervisorAgent()
    result = supervisor.run_workflow(
        user_id=1,
        user_role="teacher",
        goal="Generate a medium-difficulty Python array problem",
    )
"""

from agent_host.workflow.supervisor import SupervisorAgent
from agent_host.workflow.engine import WorkflowEngine
from agent_host.workflow.critic import WorkflowCritic

import agent_host.workflow.handlers  # noqa: F401 — registers domain step handlers

__all__ = ["SupervisorAgent", "WorkflowEngine", "WorkflowCritic"]
