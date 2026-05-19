# app/api/v1/questions.py
from flask import request, jsonify, g
from flask_smorest import Blueprint, abort

from sqlalchemy import select, func

from app.auth import require_auth, optional_auth
from app.core.extensions import db

from app.schemas.questions_schema import (
    QuestionIn, QuestionOut, QuestionListResponse,
    QuestionPublicOut, QuestionPublicListResponse,
    TestCaseIn, TestCaseOut,QuestionUpdateIn,
    QuizListResponse, IdOut,
    QuestionDetailOut,
)

from app.services.question_service import QuestionService, TestCaseService

from app.models.question import Question, TestCase
from app.models.quiz import Quiz, QuizQuestion
from app.models.submission import Submission

# Private API Blueprint (requires authentication)
blp = Blueprint(
    "questions",
    __name__,
    description="Teacher Question APIs",
    url_prefix="/api/v1"
)

# Public API Blueprint
public_blp = Blueprint(
    "questions_public",
    __name__,
    description="Public Question APIs",
    url_prefix="/api/public"
)


# ========== Public Endpoints ==========
@public_blp.get("/questions")
@public_blp.response(200, QuestionPublicListResponse)
def get_public_questions():
    """
    Get list of public questions
    
    Query Parameters:
    - limit: Number of questions to return (default: 12)
    - offset: Offset for pagination (default: 0)
    - language: Filter by programming language (optional)
    - quiz_id: Filter by quiz ID (optional)
    """
    limit = request.args.get('limit', 12, type=int)
    offset = request.args.get('offset', 0, type=int)
    language = request.args.get('language', type=str)
    quiz_id = request.args.get('quiz_id', type=int)
    
    # 构建基础查询
    query = select(Question).where(Question.is_public == True)
    
    # 添加语言筛选
    if language:
        query = query.where(Question.programming_language == language)
    
    # 添加 quiz 筛选
    if quiz_id:
        # Join with QuizQuestion to filter by quiz
        from app.models.quiz import QuizQuestion
        query = query.join(
            QuizQuestion,
            Question.id == QuizQuestion.question_id
        ).where(
            QuizQuestion.quiz_id == quiz_id
        )
    
    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total = db.session.execute(count_query).scalar()
    
    # 应用分页
    query = query.offset(offset).limit(limit)
    
    # 执行查询
    questions = db.session.execute(query).scalars().all()
    
    # 转换为字典
    items = [
        {
            "id": q.id,
            "title": q.title,
            "description": q.description,
            "programming_language": q.programming_language,
            "difficulty": q.difficulty,
            "created_at": q.created_at.isoformat() if q.created_at else None
        }
        for q in questions
    ]
    
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@public_blp.get("/questions/<int:question_id>")
@public_blp.response(200, QuestionDetailOut)
@optional_auth 
def get_question_detail(question_id):
    """
    Get question details
    
    If the user is logged in and has submission records for this question,
    the solution will be returned. Otherwise, the solution is locked.
    
    Returns:
    - Complete question information
    - solution (if user has submission records)
    - test_cases (non-hidden test cases)
    """
    try:
        
        # Try to get current user (might be unauthenticated)
        current_user = getattr(g, 'current_user', None)
        user_id = current_user.id if current_user else None
        
        # Query question
        question = db.session.execute(
            select(Question).where(Question.id == question_id)
        ).scalar_one_or_none()
        
        if not question:
            abort(404, message="Question not found")
        
        # Query non-hidden test cases
        test_cases = db.session.execute(
            select(TestCase)
            .where(
                TestCase.question_id == question_id,
                TestCase.is_hidden == False
            )
            .order_by(TestCase.id)
        ).scalars().all()
        
        # Build base response
        result = {
            "id": question.id,
            "title": question.title,
            "description": question.description,
            "programming_language": question.programming_language,
            "starter_code": question.starter_code,
            "order": question.order,
            "created_at": question.created_at.isoformat() if hasattr(question, 'created_at') and question.created_at else None,
            "difficulty": getattr(question, 'difficulty', None),
            "solution": None,  # Default: locked
            "solution_explanation": None,
            "test_cases": [
                {
                    "id": tc.id,
                    "input": tc.input,
                    "expected_output": tc.expected_output,
                    "weight": tc.weight
                }
                for tc in test_cases
            ]
        }
        
        # If user is logged in, check for submission records
        if user_id:
            submission_count = db.session.execute(
                select(func.count(Submission.id))
                .where(
                    Submission.student_id == user_id,
                    Submission.question_id == question_id
                )
            ).scalar()
            
            # If there are submissions, unlock the solution
            if submission_count > 0:
                result["solution"] = question.solution
                result["solution_explanation"] = question.solution_explanation
        
        return result
        
    except Exception as e:
        # Log the error for debugging
        import traceback
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error in get_question_detail: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Return generic error to client
        abort(500, message="Failed to retrieve question details")


# ========== Private Endpoints ==========

@blp.get("/quizzes/mine")
@blp.response(200, QuizListResponse)
@require_auth
def my_quizzes():
    """
    Get all quizzes owned by the current teacher
    Used for dropdown menus and similar scenarios
    """
    current_user = g.current_user
    items = QuestionService.get_teacher_quizzes(current_user.id)
    return {"items": items}


@blp.get("/teacher/questions")
@blp.response(200, QuestionListResponse)
@require_auth
def get_teacher_questions():
    """
    Get questions for teacher workspace
    
    Three modes:
    1. With quiz_id: Returns ALL questions in that quiz (regardless of creator)
    2. With created_by_me=true: Returns only questions created by current teacher
    3. Without filters: Returns ALL questions (from all creators)
    
    Query Parameters:
    - quiz_id: Optional quiz ID to filter questions
    - created_by_me: Optional boolean to filter by creator (true/false)
    
    Returns:
    - List of questions with creator information
    - quiz_ids array for multi-quiz questions
    """
    current_user = g.current_user
    quiz_id = request.args.get('quiz_id', type=int)
    created_by_me = request.args.get('created_by_me', '').lower() == 'true'
    
    # Helper function to get creator info
    def get_creator_info(question):
        """Get creator information for a question"""
        creator = None
        if question.created_by:
            from app.models.user import User
            creator_user = db.session.execute(
                select(User).where(User.id == question.created_by)
            ).scalar_one_or_none()
            if creator_user:
                creator = {
                    "id": creator_user.id,
                    "name": creator_user.username or creator_user.email.split('@')[0] or "User"
                }
        
        # If no creator info, mark as legacy
        if not creator:
            creator = {
                "id": None,
                "name": "Legacy Question"
            }
        
        return creator
    
    if quiz_id:
        # Mode 1: Show ALL questions in this quiz (regardless of creator)
        quiz = db.session.execute(
            select(Quiz).where(Quiz.id == quiz_id)
        ).scalar_one_or_none()
        
        if not quiz:
            abort(404, message="Quiz not found")
        
        # Get all question IDs in this quiz
        question_ids = db.session.execute(
            select(QuizQuestion.question_id)
            .where(QuizQuestion.quiz_id == quiz_id)
        ).scalars().all()
        
        if not question_ids:
            return {"items": [], "total": 0}
        
        query = select(Question).where(Question.id.in_(question_ids))
    
    elif created_by_me:
        # Mode 2: Show only teacher's own questions
        query = select(Question).where(Question.created_by == current_user.id)
    
    else:
        # Mode 3: Show ALL questions (no filter)
        query = select(Question)
    
    # Execute query
    questions = db.session.execute(
        query.order_by(Question.order, Question.id)
    ).scalars().all()
    
    # Build response with creator and quiz_ids
    result_items = []
    for question in questions:
        # Get creator information
        creator = get_creator_info(question)
        # Get all quiz associations
        quiz_associations = db.session.execute(
            select(QuizQuestion.quiz_id)
            .where(QuizQuestion.question_id == question.id)
        ).scalars().all()
        
        result_items.append({
            "id": question.id,
            "title": question.title,
            "description": question.description,
            "programming_language": question.programming_language,
            "order": question.order,
            "starter_code": question.starter_code,
            "quiz_ids": list(quiz_associations),
            "creator": creator,  # Creator information
            "test_case_count": len(question.test_cases) if hasattr(question, 'test_cases') else 0
        })
    return {
        "items": result_items,
        "total": len(result_items)
    }


@blp.post("/questions")
@blp.arguments(QuestionIn)
@blp.response(201, QuestionOut)
@require_auth
def create_question(payload):
    """
    Create a new question
    
    Request Body:
    - quiz_id: ID of the quiz this question belongs to
    - title: Question title
    - description: Question description
    - programming_language: Programming language
    - order: Display order
    - starter_code: Initial code template
    """
    current_user = g.current_user
    result = QuestionService.create_question(current_user.id, payload)
    return result


@blp.delete("/questions/<int:question_id>")
@blp.response(200, IdOut)
@require_auth
def delete_question(question_id):
    """
    Delete the specified question
    """
    current_user = g.current_user
    deleted_id = QuestionService.delete_question(current_user.id, question_id)
    return {"id": deleted_id}


@blp.post("/questions/<int:question_id>/test-cases")
@blp.arguments(TestCaseIn)
@blp.response(201, TestCaseOut)
@require_auth
def add_test_case(payload, question_id):
    """
    Add a test case to a question
    
    Request Body:
    - input: Input data
    - expected: Expected output (JSON uses 'expected', database uses 'expected_output')
    - is_hidden: Whether the test case is hidden (optional, default: false)
    - weight: Weight of this test case (optional, default: 1.0)
    """
    current_user = g.current_user
    
    try:
        result = TestCaseService.add_test_case(current_user.id, question_id, payload)
        return result
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error in add_test_case endpoint: {str(e)}")
        raise

@blp.patch("/questions/<int:question_id>")
@blp.arguments(QuestionUpdateIn)
@blp.response(200, QuestionOut)
@require_auth
def update_question(payload, question_id):
    """
    Update the specified question
    
    Request Body:
    - title: Question title (optional)
    - description: Question description (optional)
    - programming_language: Programming language (optional)
    - order: Display order (optional)
    - starter_code: Initial code template (optional)
    - solution: Solution code (optional)
    - solution_explanation: Solution explanation (optional)
    """
    current_user = g.current_user
    result = QuestionService.update_question(current_user.id, question_id, payload)
    return result


@blp.delete("/test-cases/<int:tc_id>")
@blp.response(200, IdOut)
@require_auth
def delete_test_case(tc_id):
    """
    Delete the specified test case
    """
    current_user = g.current_user
    deleted_id = TestCaseService.delete_test_case(current_user.id, tc_id)
    return {"id": deleted_id}


@blp.get("/questions/mine")
@blp.response(200, QuestionListResponse)
@require_auth
def get_my_questions():
    """
    Get all questions created by the current teacher
    
    Retrieves questions created by this teacher with optional limit
    
    Query Parameters:
    - limit: Optional limit on number of questions (default: no limit)
    """    
    current_user = g.current_user
    limit = request.args.get('limit', type=int)
    
    # Query questions created by this teacher
    query = select(Question).where(Question.created_by == current_user.id)
    
    # Apply limit if provided
    if limit:
        query = query.limit(limit)
    
    questions = db.session.execute(
        query.order_by(Question.created_at.desc())
    ).scalars().all()
    
    if not questions:
        return {"items": [], "total": 0}
    
    # Build response
    result_items = []
    for question in questions:
        # Get the first quiz associated with this question
        quiz_question = db.session.execute(
            select(QuizQuestion)
            .where(QuizQuestion.question_id == question.id)
            .limit(1)
        ).scalar_one_or_none()
        
        result_items.append({
            "id": question.id,
            "quiz_id": quiz_question.quiz_id if quiz_question else None,
            "title": question.title,
            "description": question.description,
            "programming_language": question.programming_language,
            "order": question.order,
            "difficulty": getattr(question, 'difficulty', None),
            "test_case_count": len(question.test_cases) if hasattr(question, 'test_cases') else 0
        })
    
    return {
        "items": result_items,
        "total": len(result_items)
    }


@blp.get("/questions/<int:question_id>/detail")
@blp.response(200, QuestionDetailOut)
@require_auth
def get_question_for_teacher(question_id):
    """
    Get question details for teacher management
    
    Returns complete question information including all test cases
    (both hidden and public) for the question management page.
    
    Only accessible by the teacher who owns the question.
    """
    
    current_user = g.current_user
    
    # Verify ownership
    QuestionService.verify_teacher_owns_question(current_user.id, question_id)
    
    # Query question
    question = db.session.execute(
        select(Question).where(Question.id == question_id)
    ).scalar_one_or_none()
    
    if not question:
        abort(404, message="Question not found")
    
    # Query all test cases (including hidden ones for teachers)
    test_cases = db.session.execute(
        select(TestCase)
        .where(TestCase.question_id == question_id)
        .order_by(TestCase.id)
    ).scalars().all()
    
    # Get quiz information
    quiz_question = db.session.execute(
        select(QuizQuestion, Quiz)
        .join(Quiz, QuizQuestion.quiz_id == Quiz.id)
        .where(QuizQuestion.question_id == question_id)
        .limit(1)
    ).first()
    
    quiz_info = None
    if quiz_question:
        qq, quiz = quiz_question
        quiz_info = {
            "id": quiz.id,
            "title": quiz.title
        }
    
    # Build response
    result = {
        "id": question.id,
        "title": question.title,
        "description": question.description,
        "programming_language": question.programming_language,
        "starter_code": question.starter_code,
        "order": question.order,
        "created_at": question.created_at.isoformat() if hasattr(question, 'created_at') and question.created_at else None,
        "difficulty": getattr(question, 'difficulty', None),
        "solution": question.solution,
        "solution_explanation": question.solution_explanation,
        "quiz": quiz_info,
        "test_cases": [
            {
                "id": tc.id,
                "input": tc.input,
                "expected_output": tc.expected_output,
                "weight": tc.weight,
                "is_hidden": tc.is_hidden
            }
            for tc in test_cases
        ]
    }
    
    return result
