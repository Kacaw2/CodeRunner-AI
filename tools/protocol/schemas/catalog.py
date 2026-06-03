"""Canonical tool descriptor catalog — every tool in the system."""

from .descriptors import ToolDescriptor, RiskLevel, ApprovalPolicy, RetryPolicy

TOOL_CATALOG: dict[str, ToolDescriptor] = {}


def _reg(d: ToolDescriptor) -> ToolDescriptor:
    TOOL_CATALOG[d.name] = d
    return d


# ── DB Server tools ──────────────────────────────────────────────

_reg(ToolDescriptor(
    name="coderunner.problem.get_detail",
    version="1.0.0",
    description="Get the full detail of a problem including test cases.",
    server="db",
    risk_level=RiskLevel.LOW,
    required_scopes=["problem:read"],
    input_schema={
        "type": "object",
        "properties": {
            "problem_id": {"type": "integer", "minimum": 1},
        },
        "required": ["problem_id"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "problem_id": {"type": "integer"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "difficulty": {"type": "string"},
            "languages": {"type": "array", "items": {"type": "string"}},
            "test_cases": {"type": "array"},
        },
    },
))

_reg(ToolDescriptor(
    name="coderunner.submission.list_for_student",
    version="1.0.0",
    description="Get recent submissions for a student, optionally filtered by question.",
    server="db",
    risk_level=RiskLevel.LOW,
    required_scopes=["submission:read"],
    input_schema={
        "type": "object",
        "properties": {
            "student_id": {"type": "integer", "minimum": 1},
            "question_id": {"type": "integer", "minimum": 0, "default": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
        },
        "required": ["student_id"],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
))

_reg(ToolDescriptor(
    name="coderunner.submission.get_detail",
    version="1.0.0",
    description="Get full detail of a single submission including test results.",
    server="db",
    risk_level=RiskLevel.LOW,
    required_scopes=["submission:read"],
    input_schema={
        "type": "object",
        "properties": {
            "submission_id": {"type": "integer", "minimum": 1},
            "user_id": {"type": "integer", "minimum": 1},
            "user_role": {"type": "string", "enum": ["student", "teacher", "admin"], "default": "student"},
        },
        "required": ["submission_id"],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
))

_reg(ToolDescriptor(
    name="coderunner.student.get_summary",
    version="1.0.0",
    description="Get a student's profile and overall stats.",
    server="db",
    risk_level=RiskLevel.MEDIUM,
    required_scopes=["student:read"],
    input_schema={
        "type": "object",
        "properties": {
            "student_id": {"type": "integer", "minimum": 1},
        },
        "required": ["student_id"],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
))

_reg(ToolDescriptor(
    name="coderunner.problem.save_generated",
    version="1.0.0",
    description="Save a generated problem as a draft pending teacher review.",
    server="db",
    risk_level=RiskLevel.HIGH,
    required_scopes=["problem:write"],
    approval_policy=ApprovalPolicy.TEACHER_REQUIRED,
    retry_policy=RetryPolicy(max_attempts=0),
    input_schema={
        "type": "object",
        "properties": {
            "question_data": {"type": "object", "minProperties": 1},
            "teacher_id": {"type": "integer", "minimum": 1},
        },
        "required": ["question_data", "teacher_id"],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
))

# ── Code Server tools ────────────────────────────────────────────

_reg(ToolDescriptor(
    name="coderunner.code.execute",
    version="1.0.0",
    description="Execute code in a sandboxed environment.",
    server="code",
    risk_level=RiskLevel.HIGH,
    required_scopes=["code:execute"],
    approval_policy=ApprovalPolicy.TEACHER_REQUIRED,
    timeout_ms=10_000,
    retry_policy=RetryPolicy(max_attempts=0),
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "minLength": 1, "maxLength": 10000},
            "language": {"type": "string", "enum": ["python", "c"]},
            "stdin_text": {"type": "string", "maxLength": 10000, "default": ""},
            "expected_output": {"type": "string", "maxLength": 100000, "default": ""},
        },
        "required": ["code", "language"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "time_ms": {"type": "integer"},
        },
        "required": ["status"],
    },
))

_reg(ToolDescriptor(
    name="coderunner.code.execute_internal",
    version="1.0.0",
    description="Execute trusted agent-authored code for self-validation (internal only).",
    server="code",
    risk_level=RiskLevel.MEDIUM,
    required_scopes=["code:execute_internal"],
    approval_policy=ApprovalPolicy.NONE,
    internal_only=True,
    timeout_ms=10_000,
    retry_policy=RetryPolicy(max_attempts=0),
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "minLength": 1, "maxLength": 10000},
            "language": {"type": "string", "enum": ["python", "c"]},
            "stdin_text": {"type": "string", "maxLength": 10000, "default": ""},
            "expected_output": {"type": "string", "maxLength": 100000, "default": ""},
        },
        "required": ["code", "language"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "time_ms": {"type": "integer"},
        },
        "required": ["status"],
    },
))

# ── Knowledge Server tools ───────────────────────────────────────

_reg(ToolDescriptor(
    name="coderunner.knowledge.search",
    version="1.0.0",
    description="Search the knowledge base for relevant learning materials.",
    server="knowledge",
    risk_level=RiskLevel.LOW,
    required_scopes=["knowledge:read"],
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 2000},
            "owner_id": {"type": ["integer", "null"], "minimum": 1, "default": None},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
))

_reg(ToolDescriptor(
    name="coderunner.knowledge.search_similar_problems",
    version="1.0.0",
    description="Find problems similar to the query from the knowledge base.",
    server="knowledge",
    risk_level=RiskLevel.LOW,
    required_scopes=["knowledge:read"],
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 2000},
            "language": {"type": "string", "default": "python"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 5},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
))

_reg(ToolDescriptor(
    name="coderunner.knowledge.search_error_patterns",
    version="1.0.0",
    description="Search for common error patterns matching the query.",
    server="knowledge",
    risk_level=RiskLevel.LOW,
    required_scopes=["knowledge:read"],
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 2000},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
))

# ── Analytics Server tools ───────────────────────────────────────

_reg(ToolDescriptor(
    name="coderunner.analytics.student_activity",
    version="1.0.0",
    description="Get a student's submission activity timeline.",
    server="analytics",
    risk_level=RiskLevel.LOW,
    required_scopes=["analytics:read"],
    input_schema={
        "type": "object",
        "properties": {
            "student_id": {"type": "integer", "minimum": 1},
            "days": {"type": "integer", "minimum": 1, "maximum": 365, "default": 30},
        },
        "required": ["student_id"],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
))

_reg(ToolDescriptor(
    name="coderunner.analytics.student_stats",
    version="1.0.0",
    description="Get aggregated statistics for a teacher's classrooms.",
    server="analytics",
    risk_level=RiskLevel.LOW,
    required_scopes=["analytics:read"],
    input_schema={
        "type": "object",
        "properties": {
            "teacher_id": {"type": "integer", "minimum": 1},
        },
        "required": ["teacher_id"],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
))

_reg(ToolDescriptor(
    name="coderunner.analytics.class_statistics",
    version="1.0.0",
    description="Get per-classroom statistics for a teacher.",
    server="analytics",
    risk_level=RiskLevel.LOW,
    required_scopes=["analytics:read"],
    input_schema={
        "type": "object",
        "properties": {
            "teacher_id": {"type": "integer", "minimum": 1},
        },
        "required": ["teacher_id"],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
))

_reg(ToolDescriptor(
    name="coderunner.analytics.problem_difficulty",
    version="1.0.0",
    description="Get difficulty statistics for a specific problem.",
    server="analytics",
    risk_level=RiskLevel.LOW,
    required_scopes=["analytics:read"],
    input_schema={
        "type": "object",
        "properties": {
            "problem_id": {"type": "integer", "minimum": 1},
        },
        "required": ["problem_id"],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
))

_reg(ToolDescriptor(
    name="coderunner.trace.get_agent_trace",
    version="1.0.0",
    description="Retrieve the trace of a past agent run.",
    server="analytics",
    risk_level=RiskLevel.MEDIUM,
    required_scopes=["trace:read"],
    input_schema={
        "type": "object",
        "properties": {
            "run_id": {"type": "string", "minLength": 1, "maxLength": 64},
        },
        "required": ["run_id"],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
))

# ── Approval Server tools ────────────────────────────────────────

# No required_scopes: this is the post-approval polling loop, callable by
# whoever initiated the gated call. Gating it on a scope not in the canonical
# vocabulary (§4.1) would break external clients until scope migration lands.
_reg(ToolDescriptor(
    name="coderunner.approval.check",
    version="1.0.0",
    description="Check the status of a pending tool approval and retrieve the result if approved.",
    server="db",
    risk_level=RiskLevel.LOW,
    input_schema={
        "type": "object",
        "properties": {
            "approval_id": {"type": "string", "minLength": 1, "maxLength": 64},
        },
        "required": ["approval_id"],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
))
