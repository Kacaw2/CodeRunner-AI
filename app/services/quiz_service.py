# app/services/quiz_service.py
"""Quiz business logic service"""
from app.core.extensions import db
from app.models.quiz import Quiz, QuizProblem, ClassroomQuiz, QuizAttempt
from app.models.problem import Problem
from app.models.question import Question
from app.models.classroom import Classroom, Enrollment
from domain.models.user import User
from app.core.timezone import now_china
from sqlalchemy import and_
from sqlalchemy.orm import joinedload


class QuizService:
    """Quiz service class"""
    
    @staticmethod
    def create_quiz(title, description, created_by, duration_minutes=None, is_published=False):
        """
        Create a new quiz
        
        Args:
            title: Quiz title
            description: Quiz description
            created_by: Creator ID (teacher)
            duration_minutes: Duration (minutes)
            is_published: Whether the quiz is published
            
        Returns:
            Quiz object
        """
        quiz = Quiz(
            title=title,
            description=description,
            created_by=created_by,
            duration_minutes=duration_minutes,
            is_published=is_published
        )
        
        db.session.add(quiz)
        db.session.commit()
        
        return quiz
    
    @staticmethod
    def get_quiz_by_id(quiz_id):
        """Get quiz by ID"""
        return db.session.query(Quiz)\
            .options(
                joinedload(Quiz.quiz_problems).joinedload(QuizProblem.problem),
                joinedload(Quiz.creator)
            )\
            .filter_by(id=quiz_id)\
            .first()
        
    @staticmethod
    def get_teacher_quizzes(teacher_id, include_unpublished=True):
        """
        Get all quizzes for a teacher
        
        Args:
            teacher_id: Teacher ID
            include_unpublished: Whether to include unpublished quizzes
            
        Returns:
            List of Quiz objects
        """
        query = Quiz.query.filter_by(created_by=teacher_id)
        
        if not include_unpublished:
            query = query.filter_by(is_published=True)
        
        return query.order_by(Quiz.created_at.desc()).all()
    
    @staticmethod
    def get_student_quizzes(student_id):
        """
        Get quizzes visible to a student (assigned via classrooms)
        
        Args:
            student_id: Student ID
            
        Returns:
            (list of ClassroomQuiz, list of Quiz)
        """
        # Get all classrooms the student is enrolled in
        enrollments = Enrollment.query.filter_by(student_id=student_id).all()
        classroom_ids = [e.classroom_id for e in enrollments]
        
        if not classroom_ids:
            return [], []
        
        # Get quizzes assigned to these classrooms
        classroom_quizzes = ClassroomQuiz.query.filter(
            ClassroomQuiz.classroom_id.in_(classroom_ids)
        ).all()
        
        # Only return published quizzes
        published_classroom_quizzes = [
            cq for cq in classroom_quizzes 
            if cq.quiz and cq.quiz.is_published
        ]
        
        return published_classroom_quizzes, [cq.quiz for cq in published_classroom_quizzes]
    
    @staticmethod
    def update_quiz(quiz_id, **kwargs):
        """
        Update quiz information
        
        Args:
            quiz_id: Quiz ID
            **kwargs: Fields to update
            
        Returns:
            Updated Quiz object
        """
        quiz = Quiz.query.get(quiz_id)
        if not quiz:
            return None
        
        for key, value in kwargs.items():
            if hasattr(quiz, key):
                setattr(quiz, key, value)
        
        quiz.updated_at = now_china()
        db.session.commit()
        
        return quiz
    
    @staticmethod
    def delete_quiz(quiz_id):
        """
        Delete a quiz
        
        Args:
            quiz_id: Quiz ID
            
        Returns:
            bool: Whether deletion succeeded
        """
        quiz = Quiz.query.get(quiz_id)
        if not quiz:
            return False
        
        db.session.delete(quiz)
        db.session.commit()
        
        return True
    
    @staticmethod
    def add_problem_to_quiz(quiz_id, problem_id, order=None, points=10):
        """
        Add a question to a quiz
        
        Args:
            quiz_id: Quiz ID
            problem_id: Problem ID
            order: Order
            points: Points
            
        Returns:
            QuizProblem object or None
        """
        quiz = Quiz.query.get(quiz_id)
        problem = Problem.query.get(problem_id)
        
        if not quiz or not problem:
            return None
        
        # Check if the association already exists
        existing = QuizProblem.query.filter_by(
            quiz_id=quiz_id,
            problem_id=problem_id
        ).first()
        
        if existing:
            return None
        
        # If order is not specified, use current max order + 1
        if order is None:
            max_order = db.session.query(
                db.func.max(QuizProblem.order)
            ).filter_by(quiz_id=quiz_id).scalar()
            order = (max_order or 0) + 1
        
        quiz_problem = QuizProblem(
            quiz_id=quiz_id,
            problem_id=problem_id,
            order=order,
            points=points
        )
        
        db.session.add(quiz_problem)
        db.session.commit()
        
        return quiz_problem
    
    @staticmethod
    def remove_problem_from_quiz(quiz_id, problem_id):
        """
        Remove a question from a quiz
        
        Args:
            quiz_id: Quiz ID
            problem_id: Problem ID
            
        Returns:
            bool: Whether removal succeeded
        """
        quiz_problem = QuizProblem.query.filter_by(
            quiz_id=quiz_id,
            problem_id=problem_id
        ).first()
        
        if not quiz_problem:
            return False
        
        db.session.delete(quiz_problem)
        db.session.commit()
        
        # Reorder remaining problems
        remaining = QuizProblem.query.filter_by(quiz_id=quiz_id).order_by(QuizProblem.order).all()
        for i, qq in enumerate(remaining):
            qq.order = i + 1
        
        db.session.commit()
        
        return True
    
    @staticmethod
    def update_quiz_problem(quiz_id, problem_id, order=None, points=None):
        """
        Update configuration of a question within a quiz
        
        Args:
            quiz_id: Quiz ID
            problem_id: Problem ID
            order: New order
            points: New points
            
        Returns:
            QuizProblem object or None
        """
        quiz_problem = QuizProblem.query.filter_by(
            quiz_id=quiz_id,
            problem_id=problem_id
        ).first()
        
        if not quiz_problem:
            return None
        
        if order is not None:
            quiz_problem.order = order
        
        if points is not None:
            quiz_problem.points = points
        
        db.session.commit()
        
        return quiz_problem

    add_question_to_quiz = add_problem_to_quiz
    remove_question_from_quiz = remove_problem_from_quiz
    update_quiz_question = update_quiz_problem
    
    @staticmethod
    def assign_quiz_to_classroom(quiz_id, classroom_id, assigned_by, due_date=None, allow_late_submission=False):
        """
        Assign a quiz to a classroom
        
        Args:
            quiz_id: Quiz ID
            classroom_id: Classroom ID
            assigned_by: Assigner ID
            due_date: Due date
            allow_late_submission: Whether late submissions are allowed
            
        Returns:
            ClassroomQuiz object or None
        """
        quiz = Quiz.query.get(quiz_id)
        classroom = Classroom.query.get(classroom_id)
        
        if not quiz or not classroom:
            return None
        
        # Check if already assigned
        existing = ClassroomQuiz.query.filter_by(
            quiz_id=quiz_id,
            classroom_id=classroom_id
        ).first()
        
        if existing:
            return None
        
        classroom_quiz = ClassroomQuiz(
            quiz_id=quiz_id,
            classroom_id=classroom_id,
            assigned_by=assigned_by,
            due_date=due_date,
            allow_late_submission=allow_late_submission
        )
        
        db.session.add(classroom_quiz)
        db.session.commit()
        
        return classroom_quiz
    
    @staticmethod
    def unassign_quiz_from_classroom(quiz_id, classroom_id):
        """
        Unassign a quiz from a classroom
        
        Args:
            quiz_id: Quiz ID
            classroom_id: Classroom ID
            
        Returns:
            bool: Whether unassignment succeeded
        """
        classroom_quiz = ClassroomQuiz.query.filter_by(
            quiz_id=quiz_id,
            classroom_id=classroom_id
        ).first()
        
        if not classroom_quiz:
            return False
        
        db.session.delete(classroom_quiz)
        db.session.commit()
        
        return True
    
    @staticmethod
    def get_quiz_classrooms(quiz_id):
        """
        Get all classrooms a quiz is assigned to
        
        Args:
            quiz_id: Quiz ID
            
        Returns:
            List of ClassroomQuiz
        """
        return ClassroomQuiz.query.filter_by(quiz_id=quiz_id).all()
    
    @staticmethod
    def get_classroom_quizzes(classroom_id):
        """
        Get all quizzes for a classroom
        
        Args:
            classroom_id: Classroom ID
            
        Returns:
            List of ClassroomQuiz
        """
        return ClassroomQuiz.query.filter_by(classroom_id=classroom_id).all()
    
    @staticmethod
    def start_quiz_attempt(quiz_id, student_id, classroom_quiz_id=None):
        """
        Start a quiz attempt
        
        Args:
            quiz_id: Quiz ID
            student_id: Student ID
            classroom_quiz_id: ClassroomQuiz ID (optional)
            
        Returns:
            QuizAttempt object
        """
        quiz = Quiz.query.get(quiz_id)
        if not quiz:
            return None
        
        attempt = QuizAttempt(
            quiz_id=quiz_id,
            student_id=student_id,
            classroom_quiz_id=classroom_quiz_id,
            status='in_progress',
            max_score=quiz.total_points
        )
        
        db.session.add(attempt)
        db.session.commit()
        
        return attempt
    
    @staticmethod
    def complete_quiz_attempt(attempt_id, score):
        """
        Complete a quiz attempt
        
        Args:
            attempt_id: QuizAttempt ID
            score: Score
            
        Returns:
            QuizAttempt object or None
        """
        attempt = QuizAttempt.query.get(attempt_id)
        if not attempt:
            return None
        
        attempt.completed_at = now_china()
        attempt.status = 'completed'
        attempt.score = score
        
        db.session.commit()
        
        return attempt
    
    @staticmethod
    def get_student_quiz_attempts(student_id, quiz_id=None):
        """
        Get quiz attempts for a student
        
        Args:
            student_id: Student ID
            quiz_id: Quiz ID (optional, if provided only attempts for this quiz are returned)
            
        Returns:
            List of QuizAttempt
        """
        query = QuizAttempt.query.filter_by(student_id=student_id)
        
        if quiz_id:
            query = query.filter_by(quiz_id=quiz_id)
        
        return query.order_by(QuizAttempt.started_at.desc()).all()
    
    @staticmethod
    def get_quiz_attempts(quiz_id):
        """
        Get all attempts for a quiz
        
        Args:
            quiz_id: Quiz ID
            
        Returns:
            List of QuizAttempt
        """
        return QuizAttempt.query.filter_by(quiz_id=quiz_id).order_by(QuizAttempt.started_at.desc()).all()
