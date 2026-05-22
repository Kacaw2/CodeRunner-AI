# app/schemas/submissions_schema.py
from marshmallow import Schema, fields, validate

class SubmitIn(Schema):
    """submit code input"""
    code = fields.Str(required=True, validate=validate.Length(min=1))
    time_limit_sec = fields.Float(load_default=2.0, validate=validate.Range(min=0.1, max=10.0))


class CaseResultOut(Schema):
    """testcase result outpout"""
    index = fields.Int()
    test_case_id = fields.Int()
    status = fields.Str()  # AC, WA, TLE, RE, etc.
    passed = fields.Bool()
    time_ms = fields.Int(allow_none=True)
    input = fields.Str(allow_none=True)      # return when no hidden
    expected = fields.Str(allow_none=True)   # return when no hidden
    output = fields.Str()
    stderr = fields.Str()
    hidden = fields.Bool()
    weight = fields.Float()


class SubmitOut(Schema):
    """submit result output"""
    id = fields.Int()
    problem_id = fields.Int()
    question_id = fields.Int()
    language = fields.Str()
    status = fields.Str()
    score = fields.Float()
    cases = fields.List(fields.Nested(CaseResultOut))


class SubmissionListItem(Schema):
    """submission list"""
    id = fields.Int()
    question_id = fields.Int()
    question_title = fields.Str(allow_none=True)
    status = fields.Str()
    score = fields.Float(allow_none=True)
    submitted_at = fields.Str(allow_none=True)


class MySubmissionsOut(Schema):
    """my submission list"""
    items = fields.List(fields.Nested(SubmissionListItem))
    total = fields.Int()


class SubmissionDetailOut(Schema):
    """submit detail output"""
    id = fields.Int()
    question_id = fields.Int()
    question_title = fields.Str(allow_none=True)
    code = fields.Str()
    status = fields.Str()
    score = fields.Float(allow_none=True)
    submitted_at = fields.Str(allow_none=True)
    cases = fields.List(fields.Nested(CaseResultOut))
