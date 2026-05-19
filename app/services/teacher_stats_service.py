# app/services/teacher_stats_service.py
"""
Teacher Statistics Service
"""
from typing import Dict, Any
from sqlalchemy import select, func, distinct

from app.core.extensions import db
from app.models.question import Question
from app.models.quiz import Quiz, QuizQuestion
from app.models.classroom import Classroom, Enrollment
from app.models.submission import Submission
from app.models.user import User


class TeacherStatsService:
    """Teacher Statistics Service"""
    
    @staticmethod
    def get_teacher_stats(teacher_id: int) -> Dict[str, Any]:
        """
        get all Teacher Statistics Service
        
        Args:
            teacher_id: teacher ID
            
        Returns:
            dict: {
                "questions_count": int,      
                "classrooms_count": int,    
                "students_count": int,       
                "submissions_count": int    
            }
        """
        return {
            "questions_count": TeacherStatsService.get_questions_count(teacher_id),
            "classrooms_count": TeacherStatsService.get_classrooms_count(teacher_id),
            "students_count": TeacherStatsService.get_students_count(teacher_id),
            "submissions_count": TeacherStatsService.get_submissions_count(teacher_id)
        }
    
    @staticmethod
    def get_questions_count(teacher_id: int) -> int:
        """
        Get the number of questions published by the teacher.
        
        Count questions through quizzes created by the teacher (via the QuizQuestion association table).
        """
        # Method 1: Count via quizzes
        # Get all quizzes created by the teacher
        teacher_quiz_ids = db.session.execute(
            select(Quiz.id).where(Quiz.created_by == teacher_id)
        ).scalars().all()
        
        if not teacher_quiz_ids:
            return 0
        
        # Count distinct questions in these quizzes
        question_count = db.session.execute(
            select(func.count(distinct(QuizQuestion.question_id)))
            .where(QuizQuestion.quiz_id.in_(teacher_quiz_ids))
        ).scalar() or 0
        
        return question_count
    
    @staticmethod
    def get_classrooms_count(teacher_id: int) -> int:
        """
        Get the number of classrooms owned by the teacher.
        
        Only count active classrooms (is_active=True).
        """
        count = db.session.execute(
            select(func.count(Classroom.id))
            .where(
                Classroom.teacher_id == teacher_id,
            )
        ).scalar() or 0
        
        return count
    
    @staticmethod
    def get_students_count(teacher_id: int) -> int:
        """
        Get the total number of students for the teacher (deduplicated).
        
        Count distinct students across all classrooms owned by the teacher.
        """
        # Get all classroom IDs for this teacher
        teacher_classroom_ids = db.session.execute(
            select(Classroom.id).where(Classroom.teacher_id == teacher_id)
        ).scalars().all()
        
        if not teacher_classroom_ids:
            return 0
        
        # Count distinct students in these classrooms
        student_count = db.session.execute(
            select(func.count(distinct(Enrollment.student_id)))
            .where(Enrollment.classroom_id.in_(teacher_classroom_ids))
        ).scalar() or 0
        
        return student_count
    
    @staticmethod
    def get_submissions_count(teacher_id: int) -> int:
        """
        Get the total number of submissions for the teacher's questions.
        
        Count all submissions received for questions belonging to the teacher.
        """
        # Get all quiz IDs created by this teacher
        teacher_quiz_ids = db.session.execute(
            select(Quiz.id).where(Quiz.created_by == teacher_id)
        ).scalars().all()
        
        if not teacher_quiz_ids:
            return 0
        
        # Get all question IDs in those quizzes
        question_ids = db.session.execute(
            select(QuizQuestion.question_id)
            .where(QuizQuestion.quiz_id.in_(teacher_quiz_ids))
        ).scalars().all()
        
        if not question_ids:
            return 0
        
        # Count submissions for these questions
        submission_count = db.session.execute(
            select(func.count(Submission.id))
            .where(Submission.question_id.in_(question_ids))
        ).scalar() or 0
        
        return submission_count
    
    @staticmethod
    def get_recent_submissions(teacher_id: int, limit: int = 10) -> list:
        """
        Get recent submission records for the teacher's questions.
        
        Args:
            teacher_id: Teacher ID
            limit: Maximum number of records to return
            
        Returns:
            list: List of submission records
        """
        # Get all quiz IDs created by this teacher
        teacher_quiz_ids = db.session.execute(
            select(Quiz.id).where(Quiz.created_by == teacher_id)
        ).scalars().all()
        
        if not teacher_quiz_ids:
            return []
        
        # Get all question IDs in those quizzes
        question_ids = db.session.execute(
            select(QuizQuestion.question_id)
            .where(QuizQuestion.quiz_id.in_(teacher_quiz_ids))
        ).scalars().all()
        
        if not question_ids:
            return []
        
        # Query recent submissions
        submissions = db.session.execute(
            select(Submission, User, Question)
            .join(User, Submission.student_id == User.id)
            .join(Question, Submission.question_id == Question.id)
            .where(Submission.question_id.in_(question_ids))
            .order_by(Submission.submitted_at.desc())
            .limit(limit)
        ).all()
        
        result = []
        for submission, user, question in submissions:
            result.append({
                "id": submission.id,
                "student_name": user.username,
                "student_id": user.id,
                "question_title": question.title,
                "question_id": question.id,
                "status": submission.status,
                "score": submission.score,
                "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else None
            })
        
        return result
    
    @staticmethod
    def get_students_list(teacher_id: int, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """
        Get a list of students for the teacher.
        
        Args:
            teacher_id: Teacher ID
            limit: Maximum number of records to return
            offset: Offset for pagination
            
        Returns:
            dict: {"items": [...], "total": int}
        """
        # Get all classroom IDs for this teacher
        teacher_classroom_ids = db.session.execute(
            select(Classroom.id).where(Classroom.teacher_id == teacher_id)
        ).scalars().all()
        
        if not teacher_classroom_ids:
            return {"items": [], "total": 0}
        
        # Get distinct student IDs
        student_ids_query = select(distinct(Enrollment.student_id)).where(
            Enrollment.classroom_id.in_(teacher_classroom_ids)
        )
        
        # Get total count
        total = len(db.session.execute(student_ids_query).scalars().all())
        
        # Get paginated student IDs
        student_ids = db.session.execute(
            student_ids_query.limit(limit).offset(offset)
        ).scalars().all()
        
        if not student_ids:
            return {"items": [], "total": total}
        
        # Query student details
        students = db.session.execute(
            select(User)
            .where(User.id.in_(student_ids))
            .order_by(User.username)
        ).scalars().all()
        
        items = []
        for student in students:
            # Count how many of the teacher's classrooms this student is enrolled in
            classroom_count = db.session.execute(
                select(func.count(Enrollment.classroom_id))
                .where(
                    Enrollment.student_id == student.id,
                    Enrollment.classroom_id.in_(teacher_classroom_ids)
                )
            ).scalar() or 0
            
            items.append({
                "id": student.id,
                "username": student.username,
                "email": student.email,
                "classroom_count": classroom_count
            })
        
        return {
            "items": items,
            "total": total
        }
