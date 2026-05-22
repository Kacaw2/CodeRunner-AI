# app/services/question_service.py
"""
Question business logic service
"""
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from flask_smorest import abort

from app.core.extensions import db
from app.models.question import Question, TestCase
from app.models.quiz import Quiz, QuizQuestion
from app.models.classroom import Classroom
from app.models.submission import Submission


class QuestionService:
    """Question management service"""
    
    # ========== Permission check methods ==========
    
    @staticmethod
    def teacher_owns_quiz(teacher_id: int, quiz_id: int) -> bool:
        """Check whether the teacher owns the given Quiz"""
        quiz = Quiz.query.get(quiz_id)
        if not quiz:
            return False
        
        # Quiz directly has a created_by field
        return quiz.created_by == teacher_id
    
    @staticmethod
    def teacher_owns_question(teacher_id: int, question_id: int) -> bool:
        """Check whether the teacher owns the given Question"""
        question = Question.query.get(question_id)
        if not question:
            return False
        
        if hasattr(question, 'created_by') and question.created_by:
            return question.created_by == teacher_id
        
        quiz_questions = question.quiz_associations
        if not quiz_questions:
            # If there is neither created_by nor quiz association, access is not allowed
            return False
        
        # Check whether any associated quiz belongs to this teacher
        for qq in quiz_questions:
            if qq.quiz and qq.quiz.created_by == teacher_id:
                return True
        
        return False
    
    @staticmethod
    def teacher_owns_testcase(teacher_id: int, tc_id: int) -> bool:
        """Check whether the teacher owns the given TestCase"""
        testcase = TestCase.query.get(tc_id)
        if not testcase:
            return False
        from app.services.problem_service import ProblemService

        return ProblemService.teacher_owns_problem(teacher_id, testcase.problem_id)
    
    @staticmethod
    def verify_teacher_owns_quiz(teacher_id: int, quiz_id: int) -> None:
        """Verify that the teacher owns the Quiz, otherwise raise an error"""
        if not QuestionService.teacher_owns_quiz(teacher_id, quiz_id):
            abort(403, message="You don't own this quiz")
    
    @staticmethod
    def verify_teacher_owns_question(teacher_id: int, question_id: int) -> None:
        """Verify that the teacher owns the Question, otherwise raise an error"""
        if not QuestionService.teacher_owns_question(teacher_id, question_id):
            abort(403, message="You don't own this question")
    
    @staticmethod
    def verify_teacher_owns_testcase(teacher_id: int, tc_id: int) -> None:
        """Verify that the teacher owns the TestCase, otherwise raise an error"""
        if not QuestionService.teacher_owns_testcase(teacher_id, tc_id):
            abort(403, message="You don't own this test case")
    
    # ========== Query methods ==========
    
    @staticmethod
    def get_teacher_quizzes(teacher_id: int) -> List[Dict[str, Any]]:
        """
        Get all quizzes owned by a teacher
        
        Args:
            teacher_id: Teacher ID
            
        Returns:
            List[Dict]: List of quizzes
        """
        # Quiz directly has a created_by field
        quizzes = Quiz.query.filter_by(created_by=teacher_id).all()
        
        return [{
            "id": quiz.id,
            "title": quiz.title
        } for quiz in quizzes]
    
    @staticmethod
    def get_teacher_questions(teacher_id: int, quiz_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get all questions owned by a teacher
        
        Args:
            teacher_id: Teacher ID
            quiz_id: Optional Quiz ID for filtering
            
        Returns:
            List[Dict]: List of questions
        """
        if quiz_id:
            # If quiz_id is specified, return the questions of that quiz
            return QuestionService.get_questions_by_quiz(quiz_id)
        
        # Get all questions directly created by the teacher (via created_by)
        questions = Question.query.filter_by(created_by=teacher_id).order_by(
            Question.order, Question.id
        ).all()
        
        result = []
        for question in questions:
            question_dict = QuestionService.question_to_dict(
                question, 
                quiz_id=None,
                include_test_cases=True
            )
            
            # Add associated quiz information (if any)
            if question.quiz_associations:
                quiz_ids = [qq.quiz_id for qq in question.quiz_associations]
                question_dict['quiz_ids'] = quiz_ids
            
            result.append(question_dict)
        
        return result
    
    @staticmethod
    def get_questions_by_quiz(quiz_id: int) -> List[Dict[str, Any]]:
        """
        Get all questions for a given quiz (including the number of test cases)
        
        Args:
            quiz_id: Quiz ID
            
        Returns:
            List[Dict]: List of questions
        """
        # Query through the QuizQuestion association table
        quiz_questions = QuizQuestion.query.filter_by(quiz_id=quiz_id).order_by(
            QuizQuestion.order
        ).all()
        
        result = []
        for qq in quiz_questions:
            if qq.question:
                question_dict = QuestionService.question_to_dict(
                    qq.question, 
                    quiz_id=quiz_id,
                    include_test_cases=True
                )
                # Add configuration information within this quiz
                question_dict['order'] = qq.order
                question_dict['points'] = qq.points
                result.append(question_dict)
        
        return result
    
    @staticmethod
    def get_public_questions(limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
        """
        Get the list of public questions (for frontend display)
        Does not include sensitive information such as starter_code and quiz_id
        
        Args:
            limit: Maximum number of questions to return
            offset: Offset
            
        Returns:
            dict: {"items": [...], "total": int}
        """
        # Query basic information, without sensitive fields
        query = select(
            Question.id,
            Question.title,
            Question.description,
            Question.programming_language,
            Question.order
        ).order_by(Question.order, Question.id)
        
        # Get total count
        total_query = select(func.count(Question.id))
        total = db.session.execute(total_query).scalar() or 0
        
        # Apply pagination
        if limit:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)
        
        rows = db.session.execute(query).all()
        
        items = [{
            "id": r.id,
            "title": r.title,
            "description": r.description,
            "programming_language": r.programming_language,
            "order": r.order
        } for r in rows]
        
        return {
            "items": items,
            "total": total
        }
    
    @staticmethod
    def get_question_with_solution_check(question_id: int, user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get question details and decide whether to include the solution based on the user's submission status
        
        Args:
            question_id: Question ID
            user_id: User ID (may be None, meaning not logged in)
        
        Returns:
            dict: Question details (may include solution)
        """
        # Query the question
        question = db.session.get(Question, question_id)
        if not question:
            abort(404, message="Question not found")
        
        # By default, do not include the solution
        include_solution = False
        
        # If user is logged in, check whether there is a submission record
        if user_id:
            has_submission = db.session.execute(
                select(Submission.id)
                .where(
                    Submission.student_id == user_id,
                    Submission.question_id == question_id
                )
                .limit(1)
            ).first() is not None
            
            # If there is a submission, allow viewing the solution
            include_solution = has_submission
        
        # Build response data
        result = {
            "id": question.id,
            "title": question.title,
            "description": question.description,
            "programming_language": question.programming_language,
            "starter_code": question.starter_code,
            "difficulty": getattr(question, 'difficulty', None),
            "order": question.order,
            "created_at": question.created_at.isoformat() if hasattr(question, 'created_at') and question.created_at else None,
            "updated_at": question.updated_at.isoformat() if hasattr(question, 'updated_at') and question.updated_at else None,
        }
        
        # Only include solution if there is a submission record
        if include_solution:
            result["solution"] = getattr(question, 'solution', None)
            solution_explanation = getattr(question, 'solution_explanation', None)
            if solution_explanation:
                result["solution_explanation"] = solution_explanation
        
        return result
    
    # ========== CRUD methods ==========
    
    @staticmethod
    def create_question(teacher_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new question (with permission check)
        
        Args:
            teacher_id: Teacher ID
            payload: Dictionary containing question data
            
        Returns:
            dict: Information of the created question
        """
        quiz_id = payload.get("quiz_id")
        
        # Only verify permission when quiz_id is provided
        if quiz_id:
            QuestionService.verify_teacher_owns_quiz(teacher_id, quiz_id)
        
        # Create question
        question = Question(
            title=payload["title"],
            description=payload.get("description", ""),
            programming_language=payload.get("programming_language", "c"),
            order=payload.get("order", 1),
            starter_code=payload.get("starter_code", ""),
            created_by=teacher_id,
            solution=payload.get("solution"),
            solution_explanation=payload.get("solution_explanation")
        )
        
        try:
            db.session.add(question)
            db.session.flush()  # Get question.id
        
            # Create association (if quiz_id is provided)
            if quiz_id:
                quiz_question = QuizQuestion(
                    quiz_id=quiz_id,
                    question_id=question.id,
                    order=payload.get("order", 1),
                    points=payload.get("points", 10)
                )
                db.session.add(quiz_question)
            db.session.commit()

        except IntegrityError as e:
            db.session.rollback()
            print(f"IntegrityError creating question: {e}")
            abort(400, message="Invalid fields or duplicate")
        
        return QuestionService.question_to_dict(question, quiz_id=quiz_id, include_test_cases=True)
    
    @staticmethod
    def delete_question(teacher_id: int, question_id: int) -> int:
        """
        Delete a question (with permission check)
        
        Args:
            teacher_id: Teacher ID
            question_id: Question ID
            
        Returns:
            int: ID of the deleted question
        """
        # Verify permission
        QuestionService.verify_teacher_owns_question(teacher_id, question_id)
        
        question = Question.query.get(question_id)
        if not question:
            abort(404, message="Question not found")
        
        db.session.delete(question)
        db.session.commit()
        
        return question_id

    @staticmethod
    def update_question(teacher_id: int, question_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update a question (with permission check)
        
        Args:
            teacher_id: Teacher ID
            question_id: Question ID
            payload: Dictionary containing updated data
            
        Returns:
            dict: Updated question information
        """
        # Verify permission
        QuestionService.verify_teacher_owns_question(teacher_id, question_id)
        
        question = Question.query.get(question_id)
        if not question:
            abort(404, message="Question not found")
        
        # Update fields (only fields provided in payload)
        if "title" in payload:
            question.title = payload["title"]
        if "description" in payload:
            question.description = payload["description"]
        if "programming_language" in payload:
            question.programming_language = payload["programming_language"]
        if "order" in payload:
            question.order = payload["order"]
        if "starter_code" in payload:
            question.starter_code = payload["starter_code"]
        if "solution" in payload:
            question.solution = payload["solution"]
        if "solution_explanation" in payload:
            question.solution_explanation = payload["solution_explanation"]
        
        try:
            db.session.commit()
        except IntegrityError as e:
            db.session.rollback()
            print(f"IntegrityError updating question: {e}")
            abort(400, message="Invalid fields or duplicate")
        
        # Get quiz_id (if exists)
        quiz_id = None
        if question.quiz_associations:
            quiz_id = question.quiz_associations[0].quiz_id
        
        return QuestionService.question_to_dict(question, quiz_id=quiz_id, include_test_cases=True)

    # ========== Helper methods ==========
    
    @staticmethod
    def question_to_dict(question: Question, quiz_id: Optional[int] = None, include_test_cases: bool = False) -> Dict[str, Any]:
        """
        Convert a Question object to a dictionary
        
        Args:
            question: Question object
            quiz_id: Optional Quiz ID (if in the context of a specific quiz)
            include_test_cases: Whether to include the number of test cases
            
        Returns:
            dict: Question information
        """
        result = {
            "id": question.id,
            "title": question.title,
            "description": question.description,
            "programming_language": question.programming_language,
            "starter_code": question.starter_code
        }
        
        # If quiz_id is provided, include it
        if quiz_id is not None:
            result["quiz_id"] = quiz_id
        
        if include_test_cases:
            result["test_case_count"] = len(question.test_cases)
        
        return result
    
    @staticmethod
    def testcase_to_dict(testcase: TestCase) -> Dict[str, Any]:
        """
        Convert a TestCase object to a dictionary
        
        Args:
            testcase: TestCase object
            
        Returns:
            dict: Test case information
        """
        return {
            "id": testcase.id,
            "problem_id": testcase.problem_id,
            "input": testcase.input,
            "expected": testcase.expected_output,  # Note this is mapped to 'expected'
            "is_hidden": testcase.is_hidden,
            "weight": testcase.weight
        }


class TestCaseService:
    """Test case management service"""
    
    @staticmethod
    def add_test_case(teacher_id: int, question_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add a test case for a question (with permission check)
        
        Args:
            teacher_id: Teacher ID
            question_id: Question ID
            payload: Test case data, containing:
                - input: Input data
                - expected: Expected output
                - is_hidden: Whether the test case is hidden
                - weight: Weight
            
        Returns:
            dict: Created test case information
        """
        # Verify permission
        QuestionService.verify_teacher_owns_question(teacher_id, question_id)
        
        # Verify the question exists
        question = Question.query.get(question_id)
        if not question:
            abort(404, message="Question not found")
        
        # Validate required fields
        if "input" not in payload:
            abort(400, message="'input' field is required")
        if "expected" not in payload:
            abort(400, message="'expected' field is required")
        
        # Create test case
        try:
            testcase = TestCase(
                question_id=question_id,
                input=str(payload["input"]),  # Ensure it is a string
                expected_output=str(payload["expected"]),  # In the schema this is named 'expected'
                is_hidden=bool(payload.get("is_hidden", False)),
                weight=float(payload.get("weight", 1.0))
            )
            
            db.session.add(testcase)
            db.session.commit()
            
            return QuestionService.testcase_to_dict(testcase)
            
        except (ValueError, TypeError) as e:
            db.session.rollback()
            print(f"Error creating test case: {e}")
            abort(400, message=f"Invalid data format: {str(e)}")
        except IntegrityError as e:
            db.session.rollback()
            print(f"IntegrityError creating test case: {e}")
            abort(400, message="Database integrity error")
    
    @staticmethod
    def delete_test_case(teacher_id: int, tc_id: int) -> int:
        """
        Delete a test case (with permission check)
        
        Args:
            teacher_id: Teacher ID
            tc_id: Test case ID
            
        Returns:
            int: ID of the deleted test case
        """
        # Verify permission
        QuestionService.verify_teacher_owns_testcase(teacher_id, tc_id)
        
        testcase = TestCase.query.get(tc_id)
        if not testcase:
            abort(404, message="Test case not found")
        
        db.session.delete(testcase)
        db.session.commit()
        
        return tc_id
