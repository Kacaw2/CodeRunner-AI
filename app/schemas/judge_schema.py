# app/schemas/judge_schema.py
"""
Judge code evaluation data validation schemas
"""
from marshmallow import Schema, fields, validate

class CodeRunOutputSchema(Schema):
    """Code run output schema"""
    status = fields.Str()
    passed = fields.Bool()
    compiled = fields.Bool()
    stdout = fields.Str()
    stderr = fields.Str()
    time_ms = fields.Int(allow_none=True)
    exit_code = fields.Int(allow_none=True)
    expected = fields.Str(allow_none=True)
    expected_match = fields.Bool(allow_none=True)
    error = fields.Str(allow_none=True)


class HealthCheckSchema(Schema):
    """Health check response schema"""
    status = fields.Str()
    message = fields.Str()
    docker_available = fields.Bool()
    docker_version = fields.Str(allow_none=True)

class CodeRunInputSchema(Schema):
    """code run input Schema"""
    code = fields.Str(required=True, validate=validate.Length(min=1))
    language = fields.Str(load_default="c", validate=validate.OneOf(["c", "python", "cpp", "java"]))
    input = fields.Str(load_default="", allow_none=True)
    expected_output = fields.Str(load_default=None, allow_none=True)
    time_limit_sec = fields.Float(
        load_default=2.0,
        validate=validate.Range(min=0.1, max=10.0)
    )
