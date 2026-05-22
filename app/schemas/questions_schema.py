# app/schemas/questions_schema.py
from marshmallow import Schema, fields, validate

# ---------- Question Schemas ----------
class CreatorInfo(Schema):
    """Creator information (for nesting)"""
    id = fields.Int(allow_none=True)
    name = fields.Str()

class QuestionIn(Schema):
    """Input data for creating a question"""
    quiz_id = fields.Int(required=False, allow_none=True, load_default=None)
    title = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    description = fields.Str(load_default="")
    programming_language = fields.Str(load_default="c")
    order = fields.Int(load_default=1)
    starter_code = fields.Str(load_default="")
    solution = fields.Str(allow_none=True, load_default=None)
    solution_explanation = fields.Str(allow_none=True, load_default=None)


class QuestionUpdateIn(Schema):
    """All fields optional"""
    title = fields.Str()
    description = fields.Str()
    programming_language = fields.Str()
    order = fields.Int()
    starter_code = fields.Str()
    

class QuestionOut(Schema):
    """Full question response data"""
    id = fields.Int()
    quiz_id = fields.Int(allow_none=True)
    title = fields.Str()
    description = fields.Str()
    programming_language = fields.Str()
    order = fields.Int()
    starter_code = fields.Str()
    test_case_count = fields.Int()
    creator = fields.Nested(CreatorInfo, allow_none=True)  # ← newly added line
    quiz_ids = fields.List(fields.Int())


class TestCaseDetailOut(Schema):
    """Test case detail output (for nesting)"""
    id = fields.Int()
    input = fields.Str()
    expected_output = fields.Str()
    weight = fields.Float()
    is_hidden = fields.Bool()


class QuizInfo(Schema):
    """Quiz information (for nesting)"""
    id = fields.Int()
    title = fields.Str()


class QuestionDetailOut(Schema):
    """Question detail output (including solution)"""
    id = fields.Int(required=True)
    title = fields.Str(required=True)
    description = fields.Str(required=True)
    programming_language = fields.Str(required=True)
    starter_code = fields.Str(allow_none=True)
    difficulty = fields.Str(allow_none=True)
    order = fields.Int(allow_none=True)
    created_at = fields.Str(allow_none=True)
    updated_at = fields.Str(allow_none=True)
    
    solution = fields.Str(allow_none=True, dump_default=None)
    solution_explanation = fields.Str(allow_none=True, dump_default=None)
    quiz = fields.Dict(allow_none=True, dump_default=None)
    
    test_cases = fields.List(fields.Nested(TestCaseDetailOut), dump_default=[])


class QuestionPublicOut(Schema):
    """Public question data (for frontend lists)"""
    id = fields.Int()
    title = fields.Str()
    description = fields.Str()
    programming_language = fields.Str()
    order = fields.Int()
    


class QuestionListResponse(Schema):
    """Question list response"""
    items = fields.List(fields.Nested(QuestionOut))
    total = fields.Int()


class QuestionPublicListResponse(Schema):
    """Public question list response"""
    items = fields.List(fields.Nested(QuestionPublicOut))
    total = fields.Int()


# ---------- Problem Schemas ----------
class ProblemVariantOut(Schema):
    question_id = fields.Int(required=True)
    language = fields.Str(required=True)
    starter_code = fields.Str(allow_none=True)


class ProblemListItemOut(Schema):
    id = fields.Int(required=True)
    slug = fields.Str()
    title = fields.Str(required=True)
    description = fields.Str()
    difficulty = fields.Str(allow_none=True)
    points = fields.Int()
    order = fields.Int()
    default_language = fields.Str()
    completed = fields.Bool(load_default=False)
    variants = fields.List(fields.Nested(ProblemVariantOut))


class ProblemListResponse(Schema):
    items = fields.List(fields.Nested(ProblemListItemOut))
    total = fields.Int()
    limit = fields.Int()
    offset = fields.Int()


class ProblemCreateIn(Schema):
    quiz_id = fields.Int(required=False, allow_none=True, load_default=None)
    title = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    description = fields.Str(required=True)
    difficulty = fields.Str(load_default="easy", validate=validate.OneOf(["easy", "medium", "hard"]))
    points = fields.Int(load_default=10)
    order = fields.Int(load_default=1)
    python_starter_code = fields.Str(load_default="")
    python_solution = fields.Str(load_default="")
    python_solution_explanation = fields.Str(load_default="")
    c_starter_code = fields.Str(load_default="")
    c_solution = fields.Str(load_default="")
    c_solution_explanation = fields.Str(load_default="")


class ProblemSubmitIn(Schema):
    language = fields.Str(load_default="python", validate=validate.OneOf(["python", "c"]))
    code = fields.Str(required=True)
    time_limit_sec = fields.Float(load_default=2.0, validate=validate.Range(min=0.1, max=10.0))


# ---------- TestCase Schemas ----------
class TestCaseIn(Schema):
    """Input data for creating a test case"""
    input = fields.Str(required=True, allow_none=False)
    expected = fields.Str(required=True, allow_none=False)
    is_hidden = fields.Bool(load_default=False)
    weight = fields.Float(load_default=1.0)


class TestCaseOut(Schema):
    """Full test case response data"""
    id = fields.Int()
    problem_id = fields.Int()
    input = fields.Str()
    expected = fields.Str(attribute="expected_output")
    is_hidden = fields.Bool()
    weight = fields.Float()


# ---------- Quiz Schemas ----------
class QuizListItem(Schema):
    """Quiz list item"""
    id = fields.Int()
    title = fields.Str()


class QuizListResponse(Schema):
    """Quiz list response"""
    items = fields.List(fields.Nested(QuizListItem))


# ---------- Common Schemas ----------
class IdOut(Schema):
    """Response containing an ID"""
    id = fields.Int()


class MessageOut(Schema):
    """Response containing a message"""
    message = fields.Str()
