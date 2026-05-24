# app/schemas/quiz_schema.py
"""Quiz evaluation schema"""
from marshmallow import Schema, fields, validate, validates, ValidationError
from app.core.timezone import now_china
from app.schemas.questions_schema import QuestionOut as QuestionSchema


class QuizQuestionSchema(Schema):
    """Quiz Question schema in quiz"""
    id = fields.Int(dump_only=True)
    quiz_id = fields.Int(dump_only=True)
    question_id = fields.Int(required=True)
    order = fields.Int(required=False, load_default=0)
    points = fields.Int(required=False, load_default=10, validate=validate.Range(min=0))
    added_at = fields.DateTime(dump_only=True)
    question_id = fields.Int()
    question_title = fields.Str(attribute='question.title')
    question_language = fields.Str(attribute='question.programming_language')
   
    question = fields.Nested(QuestionSchema, dump_only=True)


class QuizCreateSchema(Schema):
    """create Quiz schema"""
    title = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    description = fields.Str(required=False, allow_none=True)
    duration_minutes = fields.Int(required=False, allow_none=True, validate=validate.Range(min=1))
    is_published = fields.Bool(required=False, load_default=False)


class QuizUpdateSchema(Schema):
    """update Quiz schema"""
    title = fields.Str(required=False, validate=validate.Length(min=1, max=200))
    description = fields.Str(required=False, allow_none=True)
    duration_minutes = fields.Int(required=False, allow_none=True, validate=validate.Range(min=1))
    is_published = fields.Bool(required=False)


class QuizSchema(Schema):
    """Quiz full info schema"""
    id = fields.Int(dump_only=True)
    title = fields.Str()
    description = fields.Str(allow_none=True)
    created_by = fields.Int()
    duration_minutes = fields.Int(allow_none=True)
    is_published = fields.Bool()
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
    
    question_count = fields.Int(dump_only=True)
    total_points = fields.Int(dump_only=True)
    
    # relation
    creator = fields.Nested('UserSchema', dump_only=True, only=('id', 'username'))
    quiz_questions = fields.List(fields.Nested(QuizQuestionSchema), dump_only=True)


class QuizListSchema(Schema):
    """Quiz list schema"""
    id = fields.Int()
    title = fields.Str()
    description = fields.Str(allow_none=True)
    created_by = fields.Int()
    duration_minutes = fields.Int(allow_none=True)
    is_published = fields.Bool()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()
    
    question_count = fields.Int()
    total_points = fields.Int()
    
    # creator info
    creator = fields.Nested('UserSchema', only=('id', 'username'))


class ClassroomQuizCreateSchema(Schema):
    """assign Quiz to Classroom schema"""
    classroom_id = fields.Int(required=True)
    quiz_id = fields.Int(required=True)
    due_date = fields.DateTime(required=False, allow_none=True)
    allow_late_submission = fields.Bool(required=False, load_default=False)
    
    @validates('due_date')
    def validate_due_date(self, value):
        if value and value < now_china():
            raise ValidationError('Due date must be in the future')


class ClassroomQuizSchema(Schema):
    """Classroom-Quiz schema"""
    id = fields.Int(dump_only=True)
    classroom_id = fields.Int()
    quiz_id = fields.Int()
    assigned_at = fields.DateTime(dump_only=True)
    due_date = fields.DateTime(allow_none=True)
    allow_late_submission = fields.Bool()
    assigned_by = fields.Int(dump_only=True)
    
    # 计算字段
    is_overdue = fields.Bool(dump_only=True)
    
    # 关系
    classroom = fields.Nested('ClassroomSchema', dump_only=True, only=('id', 'name', 'code'))
    quiz = fields.Nested(QuizListSchema, dump_only=True)
    assigner = fields.Nested('UserSchema', dump_only=True, only=('id', 'username'))


class QuizAttemptCreateSchema(Schema):
    """Quiz attempt schema"""
    quiz_id = fields.Int(required=True)
    classroom_quiz_id = fields.Int(required=False, allow_none=True)


class QuizAttemptSchema(Schema):
    """Quiz attempt schema"""
    id = fields.Int(dump_only=True)
    quiz_id = fields.Int()
    student_id = fields.Int()
    classroom_quiz_id = fields.Int(allow_none=True)
    started_at = fields.DateTime(dump_only=True)
    completed_at = fields.DateTime(allow_none=True)
    status = fields.Str()
    score = fields.Float(allow_none=True)
    max_score = fields.Float(allow_none=True)
    
    # 计算字段
    percentage = fields.Float(dump_only=True)
    duration_minutes = fields.Float(dump_only=True, allow_none=True)
    
    # 关系
    quiz = fields.Nested(QuizListSchema, dump_only=True)
    student = fields.Nested('UserSchema', dump_only=True, only=('id', 'username'))


class AddQuestionToQuizSchema(Schema):
    """添加Question到Quiz的schema"""
    question_id = fields.Int(required=True)
    order = fields.Int(required=False, load_default=0)
    points = fields.Int(required=False, load_default=10, validate=validate.Range(min=0))


class UpdateQuizQuestionSchema(Schema):
    """更新Quiz中Question的schema"""
    order = fields.Int(required=False)
    points = fields.Int(required=False, validate=validate.Range(min=0))
