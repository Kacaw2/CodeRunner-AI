"""
Structured planner — decomposes a user goal into a sequence of workflow steps.

Uses LLM to generate a structured plan, or provides pre-built plan templates
for known workflow types (e.g., problem generation).
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from ai.agents.config import AIConfig
from ai.graph.state import WorkflowPlan, WorkflowStepDef

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """You are a workflow planner for a coding education platform.
Given a user goal, decompose it into a sequence of steps that agents can execute.

Available step types:
- agent_call: Dispatch to a specialist agent (tutor, reviewer, generator, analytics)
- tool_call: Execute a single tool (search_similar_problems, execute_code, etc.)
- validation: Run quality/correctness validation on a previous step's output
- llm_call: Standalone LLM reasoning (analysis, summarization, etc.)
- human_gate: Pause for human approval before proceeding

Available agents:
- tutor: Helps students understand concepts, provides hints
- reviewer: Reviews code quality, provides feedback
- generator: Creates new coding problems with test cases
- analytics: Queries learning data, generates reports

Risk levels:
- low: Read-only, no side effects
- medium: Computation or generation, reversible
- high: Writes to database, publishes content, irreversible

Rules:
1. Keep plans concise (3-8 steps max).
2. Mark high-risk steps with requires_approval: true.
3. Include validation steps after generation/computation.
4. Steps execute sequentially by default; use depends_on only for non-linear flows.
5. The user_role determines what agents/tools are available.

Output ONLY valid JSON matching this schema:
{
  "goal": "...",
  "workflow_type": "general|generation|review|analysis|tutoring",
  "steps": [
    {
      "step_index": 0,
      "step_type": "agent_call|tool_call|validation|llm_call|human_gate",
      "agent_type": "tutor|reviewer|generator|analytics" (for agent_call),
      "instruction": "What this step should do",
      "risk_level": "low|medium|high",
      "requires_approval": false
    }
  ]
}"""

GENERATION_TEMPLATE: list[WorkflowStepDef] = [
    {
        "step_index": 0,
        "step_type": "generate_problem",
        "agent_type": "generator",
        "instruction": "Generate a coding problem based on the requirements",
        "risk_level": "medium",
        "requires_approval": False,
    },
    {
        "step_index": 1,
        "step_type": "validate_solution",
        "agent_type": "generator",
        "instruction": "Run the reference solution against test cases to verify correctness",
        "risk_level": "medium",
        "requires_approval": False,
        "depends_on": [0],
    },
    {
        "step_index": 2,
        "step_type": "dedup_check",
        "agent_type": "generator",
        "instruction": "Search knowledge base for similar existing problems",
        "risk_level": "low",
        "requires_approval": False,
        "depends_on": [0],
    },
    {
        "step_index": 3,
        "step_type": "quality_review",
        "agent_type": "reviewer",
        "instruction": "Review problem quality: clarity, constraints, examples, difficulty",
        "risk_level": "low",
        "requires_approval": False,
        "depends_on": [0],
    },
    {
        "step_index": 4,
        "step_type": "human_gate",
        "agent_type": "publisher",
        "instruction": "Save as draft and await teacher approval",
        "risk_level": "high",
        "requires_approval": True,
    },
]

REVIEW_TEMPLATE: list[WorkflowStepDef] = [
    {
        "step_index": 0,
        "step_type": "agent_call",
        "agent_type": "reviewer",
        "instruction": "Perform code review and identify issues",
        "risk_level": "low",
        "requires_approval": False,
    },
    {
        "step_index": 1,
        "step_type": "agent_call",
        "agent_type": "reviewer",
        "instruction": "Execute the code to verify it runs and report failures",
        "risk_level": "medium",
        "requires_approval": False,
    },
    {
        "step_index": 2,
        "step_type": "validation",
        "agent_type": "reviewer",
        "instruction": "Validate review completeness and scoring",
        "validates_step": 0,
        "risk_level": "low",
        "requires_approval": False,
    },
]

GENERAL_TEMPLATE: list[WorkflowStepDef] = [
    {
        "step_index": 0,
        "step_type": "llm_call",
        "instruction": "Analyze the user goal and produce a direct, actionable response",
        "risk_level": "low",
        "requires_approval": False,
    },
]

TEMPLATES: dict[str, list[WorkflowStepDef]] = {
    "generation": GENERATION_TEMPLATE,
    "review": REVIEW_TEMPLATE,
}


def classify_workflow_type(goal: str, user_role: str) -> str:
    """Quick heuristic classification of workflow type before LLM planning."""
    goal_lower = goal.lower()

    generation_keywords = ["生成", "创建", "出题", "generate", "create problem", "new problem"]
    review_keywords = ["审查", "review", "critique", "评审", "代码审查"]
    analysis_keywords = ["分析", "统计", "报告", "analytics", "stats", "report"]

    if user_role == "teacher" and any(k in goal_lower for k in generation_keywords):
        return "generation"
    if any(k in goal_lower for k in review_keywords):
        return "review"
    if any(k in goal_lower for k in analysis_keywords):
        return "analysis"
    return "general"


def plan_from_template(workflow_type: str, goal: str, context: dict = None) -> WorkflowPlan:
    """Use a pre-built template for known workflow types."""
    steps = TEMPLATES.get(workflow_type, [])
    if not steps:
        return None

    plan: WorkflowPlan = {
        "goal": goal,
        "workflow_type": workflow_type,
        "steps": [dict(s) for s in steps],
        "context": context or {},
    }
    return plan


def plan_general_fallback(goal: str, context: dict = None) -> WorkflowPlan:
    """Minimal single-step plan used when LLM planning is unavailable."""
    return {
        "goal": goal,
        "workflow_type": "general",
        "steps": [dict(s) for s in GENERAL_TEMPLATE],
        "context": context or {},
    }


def plan_with_llm(goal: str, user_role: str, context: dict = None) -> WorkflowPlan:
    """Use LLM to generate a structured plan for arbitrary goals."""
    llm = AIConfig.get_llm()

    user_prompt = f"User role: {user_role}\nGoal: {goal}"
    if context:
        user_prompt += f"\nAdditional context: {json.dumps(context, ensure_ascii=False)}"

    messages = [
        SystemMessage(content=PLANNER_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    try:
        response = llm.invoke(messages)
        content = response.content or ""
        start = content.find("{")
        end = content.rfind("}") + 1
        if start < 0 or end <= start:
            logger.error("Planner LLM did not return JSON: %s", content[:200])
            return None

        plan_data = json.loads(content[start:end])

        if "steps" not in plan_data or not plan_data["steps"]:
            logger.error("Planner returned empty steps")
            return None

        for i, step in enumerate(plan_data["steps"]):
            step.setdefault("step_index", i)
            step.setdefault("step_type", "llm_call")
            step.setdefault("risk_level", "low")
            step.setdefault("requires_approval", False)

        plan: WorkflowPlan = {
            "goal": plan_data.get("goal", goal),
            "workflow_type": plan_data.get("workflow_type", "general"),
            "steps": plan_data["steps"],
            "context": context or {},
        }
        return plan
    except json.JSONDecodeError as e:
        logger.error("Planner LLM output not valid JSON: %s", e)
        return None
    except Exception as e:
        logger.error("Planner failed: %s", e)
        return None


def create_plan(goal: str, user_role: str, context: dict = None) -> WorkflowPlan:
    """Main entry point: try template first, fall back to LLM planning."""
    workflow_type = classify_workflow_type(goal, user_role)

    if workflow_type in TEMPLATES:
        plan = plan_from_template(workflow_type, goal, context)
        if plan:
            logger.info("Using template plan for workflow_type=%s", workflow_type)
            return plan

    logger.info("Using LLM planner for goal: %.80s", goal)
    plan = plan_with_llm(goal, user_role, context)
    if plan:
        return plan

    logger.warning("LLM planner returned no plan; falling back to general template")
    return plan_general_fallback(goal, context)
