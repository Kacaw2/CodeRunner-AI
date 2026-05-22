# app/models/__init__.py
"""
Database Model Module

All models are imported here for convenient use by other modules
"""

from .user import User, UserRole
from .classroom import Classroom, Enrollment
from .problem import Problem
from .quiz import Quiz, QuizProblem, ClassroomQuiz, QuizAttempt
from .question import Question, TestCase
from .submission import Submission, TestResult
from .agent_task import AgentTask
from .agent_trace import AgentRun, AgentRunStep
from .ai_audit_log import AIAuditLog
from .generated_question_draft import GeneratedQuestionDraft
from .student_profile import StudentProfile, TeacherPreference
from .eval_run import EvalRun

QuizQuestion = QuizProblem

__all__ = [
    # User models
    'User',
    'UserRole',

    # Classroom models
    'Classroom',
    'Enrollment',

    # Quiz models
    'Quiz',
    'QuizProblem',
    'ClassroomQuiz',
    'QuizAttempt',

    # Problem models
    'Problem',

    # Question models
    'Question',
    'TestCase',

    # Submission models
    'Submission',
    'TestResult',

    # Agent models (Phase 1)
    'AgentTask',
    'AgentRun',
    'AgentRunStep',
    'AIAuditLog',

    # Phase 2
    'GeneratedQuestionDraft',

    # Phase 3
    'StudentProfile',
    'TeacherPreference',
    'EvalRun',
]
