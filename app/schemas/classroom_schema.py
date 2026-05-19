# app/schemas/classroom_schema.py

"""
Data validation schemas related to users Classroom 
"""
from marshmallow import Schema, fields, validate


class ClassroomCreateSchema(Schema):
    """create Classroom input schema"""
    name = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    description = fields.Str(load_default="")


class ClassroomUpdateSchema(Schema):
    """update Classroom input schema"""
    name = fields.Str(validate=validate.Length(min=1, max=200))
    description = fields.Str()


class ClassroomSchema(Schema):
    """Classroom output schema"""
    id = fields.Int()
    name = fields.Str()
    code = fields.Str()
    description = fields.Str()
    teacher_id = fields.Int()
    created_at = fields.DateTime()


class ClassroomListSchema(Schema):
    """Classroom list output schema"""
    items = fields.List(fields.Nested(ClassroomSchema))
