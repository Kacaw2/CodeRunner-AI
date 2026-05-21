# app/api/v1/quizzes.py
"""Quiz Management API"""
from flask import g, request
from flask_smorest import Blueprint, abort
from app.auth import require_teacher, require_auth
from app.services.quiz_service import QuizService
from app.models import Quiz, QuizQuestion
from app.models.submission import Submission
from app.core.extensions import db
from sqlalchemy.orm import joinedload
from datetime import datetime
from app.models.quiz import ClassroomQuiz
from app.models.submission import Submission
from app.models.user import User
from sqlalchemy import distinct
from app.schemas.quiz_schema import (
    QuizSchema,
    QuizListSchema,
    QuizCreateSchema,
    QuizUpdateSchema,
    AddQuestionToQuizSchema, 
    QuizQuestionSchema,
    ClassroomQuizCreateSchema,
    ClassroomQuizSchema
)
blp = Blueprint(
    "quizzes",
    __name__,
    description="Quiz Management APIs",
    url_prefix="/api/v1/quizzes"
)


@blp.get("/")
@require_auth
def get_quizzes():
    """
    Get Quiz list
    - Teacher: Get all quizzes created by themselves
    - Student: Get quizzes assigned to them (with completion progress)
    """
    current_user = g.current_user
    
    if current_user.role.value == 'student':
        # Student: Get assigned quizzes
        classroom_quizzes, quizzes = QuizService.get_student_quizzes(current_user.id)
        
        items = []
        for cq in classroom_quizzes:
            quiz = cq.quiz
            if not quiz:
                continue
            
            # Calculate completion progress
            completed_count = 0
            total_score = 0
            max_score = 0
            
            # Safely access quiz_questions
            quiz_questions = quiz.quiz_questions if hasattr(quiz, 'quiz_questions') and quiz.quiz_questions else []
            
            for qq in quiz_questions:
                if qq.question:
                    max_score += qq.points
                    submission = Submission.query.filter_by(
                        student_id=current_user.id,
                        question_id=qq.question.id,
                        status='completed'
                    ).first()
                    if submission:
                        completed_count += 1
                        # Calculate score: submission.score is a percentage (0-100)
                        if submission.score is not None:
                            total_score += (submission.score / 100.0) * qq.points
            
            total_count = len(quiz_questions)
            progress_percentage = (completed_count / total_count * 100) if total_count > 0 else 0
            
            # Check if overdue
            is_overdue = False
            if cq.due_date:
                is_overdue = cq.due_date < datetime.utcnow()
            
            # Dynamically calculate attempt status (not relying on QuizAttempt table)
            attempt = None
            if completed_count > 0:
                # If any questions are completed, create a virtual attempt object
                if completed_count == total_count:
                    status = 'completed'
                else:
                    status = 'in_progress'
                
                percentage = (total_score / max_score * 100) if max_score > 0 else 0
                
                attempt = {
                    'id': None,  # Virtual, no actual ID
                    'status': status,
                    'score': round(total_score, 1),
                    'max_score': max_score,
                    'percentage': round(percentage, 1)
                }
            
            items.append({
                'id': quiz.id,
                'title': quiz.title,
                'description': quiz.description,
                'duration_minutes': quiz.duration_minutes,
                'question_count': total_count,
                'completed_questions': completed_count,
                'progress_percentage': round(progress_percentage, 1),
                'classroom': {
                    'id': cq.classroom.id,
                    'name': cq.classroom.name
                } if cq.classroom else None,
                'due_date': cq.due_date.isoformat() if cq.due_date else None,
                'is_overdue': is_overdue,
                'attempt': attempt
            })
        
        return {
            'items': items,
            'total': len(items)
        }
    
    elif current_user.role.value == 'teacher':
        # Teacher: Get quizzes created by themselves
        quizzes = QuizService.get_teacher_quizzes(current_user.id)
        
        items = []
        for quiz in quizzes:
            assigned_count = ClassroomQuiz.query.filter_by(quiz_id=quiz.id).count()
            items.append({
                'id': quiz.id,
                'title': quiz.title,
                'description': quiz.description,
                'duration_minutes': quiz.duration_minutes,
                'is_published': quiz.is_published,
                'question_count': quiz.question_count,
                'total_points': quiz.total_points,
                'assigned_to_count': assigned_count, 
                'created_at': quiz.created_at.isoformat() if quiz.created_at else None
            })
        
        return {
            'items': items,
            'total': len(items)
        }
    
    else:
        abort(403, message="Invalid role")


@blp.post("")
@require_teacher
def create_quiz():
    """
    Create a new Quiz
    
    Request Body:
        - title: Quiz title (required)
        - description: Quiz description (optional)
        - duration_minutes: Duration in minutes (optional)
        - is_published: Whether published (optional, default: false)
    """
    current_user = g.current_user
    data = request.get_json()
    
    # Validate data
    title = data.get('title', '').strip()
    if not title:
        abort(400, message="Quiz title is required")
    
    quiz = QuizService.create_quiz(
        title=title,
        description=data.get('description', ''),
        created_by=current_user.id,
        duration_minutes=data.get('duration_minutes'),
        is_published=data.get('is_published', False)
    )
    
    return {
        'id': quiz.id,
        'title': quiz.title,
        'description': quiz.description,
        'created_by': quiz.created_by,
        'duration_minutes': quiz.duration_minutes,
        'is_published': quiz.is_published,
        'created_at': quiz.created_at.isoformat() if quiz.created_at else None,
        'question_count': 0,
        'total_points': 0
    }, 201


@blp.get("/<int:quiz_id>")
@require_auth
def get_quiz(quiz_id):
    """
    Get Quiz details (including questions and student completion status)
    """
    current_user = g.current_user
    
    quiz = QuizService.get_quiz_by_id(quiz_id)
    
    if not quiz:
        abort(404, message="Quiz not found")
    
    # Permission check
    if current_user.role.value == 'teacher':
        # Teacher can only view their own quizzes
        if quiz.created_by != current_user.id:
            abort(403, message="You can only view your own quizzes")
    else:
        # Student can only view assigned and published quizzes
        if not quiz.is_published:
            abort(403, message="This quiz is not published")
        
        # Check if assigned to student's classroom
        classroom_quizzes, _ = QuizService.get_student_quizzes(current_user.id)
        quiz_ids = [cq.quiz_id for cq in classroom_quizzes]
        
        if quiz.id not in quiz_ids:
            abort(403, message="You don't have access to this quiz")
    
    # Build return data
    result = {
        'id': quiz.id,
        'title': quiz.title,
        'description': quiz.description,
        'created_by': quiz.created_by,
        'duration_minutes': quiz.duration_minutes,
        'is_published': quiz.is_published,
        'created_at': quiz.created_at.isoformat() if quiz.created_at else None,
        'updated_at': quiz.updated_at.isoformat() if quiz.updated_at else None,
        'question_count': quiz.question_count,
        'total_points': quiz.total_points,
        'creator': {
            'id': quiz.creator.id,
            'username': quiz.creator.username
        } if quiz.creator else None,
        'questions': []
    }
    
    # If student, add classroom and due_date information
    if current_user.role.value == 'student':
        # Find the classroom_quiz assignment for this quiz
        from app.models.quiz import ClassroomQuiz
        classroom_quizzes, _ = QuizService.get_student_quizzes(current_user.id)
        for cq in classroom_quizzes:
            if cq.quiz_id == quiz.id:
                result['classroom'] = {
                    'id': cq.classroom.id,
                    'name': cq.classroom.name
                } if cq.classroom else None
                result['due_date'] = cq.due_date.isoformat() if cq.due_date else None
                result['is_overdue'] = cq.is_overdue
                break
    
    # Now quiz.quiz_questions has been pre-loaded and can be accessed normally
    completed_count = 0
    total_score = 0
    max_score = 0
    
    # Safely access quiz_questions
    quiz_questions = quiz.quiz_questions if hasattr(quiz, 'quiz_questions') and quiz.quiz_questions else []
    
    for qq in sorted(quiz_questions, key=lambda x: x.order):
        if qq.question:
            q = qq.question
            max_score += qq.points
            
            question_data = {
                'id': q.id,
                'title': q.title,
                'description': q.description,
                'programming_language': q.programming_language,
                'order': qq.order,
                'points': qq.points,
                'starter_code': q.starter_code,
                'difficulty': getattr(q, 'difficulty', None)
            }
            
            # For students, add completion status
            if current_user.role.value == 'student':
                # Query student's best submission for this question
                submission = Submission.query.filter_by(
                    student_id=current_user.id,
                    question_id=q.id,
                    status='completed'
                ).order_by(Submission.score.desc()).first()
                
                if submission:
                    completed_count += 1
                    question_score = (submission.score / 100.0) * qq.points if submission.score is not None else 0
                    total_score += question_score
                    
                    question_data['submission'] = {
                        'id': submission.id,
                        'status': submission.status,
                        'score': submission.score,
                        'question_score': round(question_score, 1),
                        'submitted_at': submission.submitted_at.isoformat() if submission.submitted_at else None
                    }
                else:
                    question_data['submission'] = None
            
            result['questions'].append(question_data)
    
    # For students, add overall progress information
    if current_user.role.value == 'student':
        total_count = len(quiz_questions)
        progress_percentage = (completed_count / total_count * 100) if total_count > 0 else 0
        percentage = (total_score / max_score * 100) if max_score > 0 else 0
        
        result['progress'] = {
            'completed_questions': completed_count,
            'total_questions': total_count,
            'progress_percentage': round(progress_percentage, 1),
            'total_score': round(total_score, 1),
            'max_score': max_score,
            'percentage': round(percentage, 1)
        }
    
    return result


@blp.put("/<int:quiz_id>")
@require_teacher
def update_quiz(quiz_id):
    """
    Update Quiz information
    
    Request Body:
        - title: New title (optional)
        - description: New description (optional)
        - duration_minutes: New duration (optional)
        - is_published: New publish status (optional)
    """
    current_user = g.current_user
    quiz = QuizService.get_quiz_by_id(quiz_id)
    
    if not quiz:
        abort(404, message="Quiz not found")
    
    if quiz.created_by != current_user.id:
        abort(403, message="You can only edit your own quizzes")
    
    data = request.get_json()
    
    update_fields = {}
    if 'title' in data:
        title = data['title'].strip()
        if not title:
            abort(400, message="Quiz title cannot be empty")
        update_fields['title'] = title
    
    if 'description' in data:
        update_fields['description'] = data['description']
    
    if 'duration_minutes' in data:
        update_fields['duration_minutes'] = data['duration_minutes']
    
    if 'is_published' in data:
        update_fields['is_published'] = data['is_published']
    
    if not update_fields:
        abort(400, message="No fields to update")
    
    updated_quiz = QuizService.update_quiz(quiz_id, **update_fields)
    
    return {
        'id': updated_quiz.id,
        'title': updated_quiz.title,
        'description': updated_quiz.description,
        'duration_minutes': updated_quiz.duration_minutes,
        'is_published': updated_quiz.is_published,
        'updated_at': updated_quiz.updated_at.isoformat() if updated_quiz.updated_at else None,
        'message': 'Quiz updated successfully'
    }


@blp.delete("/<int:quiz_id>")
@require_teacher
def delete_quiz(quiz_id):
    """
    Delete Quiz
    """
    current_user = g.current_user
    quiz = QuizService.get_quiz_by_id(quiz_id)
    
    if not quiz:
        abort(404, message="Quiz not found")
    
    if quiz.created_by != current_user.id:
        abort(403, message="You can only delete your own quizzes")
    
    success = QuizService.delete_quiz(quiz_id)
    
    if not success:
        abort(400, message="Failed to delete quiz")
    
    return {'message': 'Quiz deleted successfully'}



@blp.post("/<int:quiz_id>/questions")
@blp.arguments(AddQuestionToQuizSchema)
@blp.response(201, QuizQuestionSchema)
@require_teacher
def add_question_to_quiz(payload, quiz_id):
    """Add an existing question to a quiz"""
    current_user = g.current_user
    
    # 验证权限
    quiz = QuizService.get_quiz_by_id(quiz_id)
    if not quiz:
        abort(404, message="Quiz not found")
    
    if quiz.created_by != current_user.id:
        abort(403, message="You don't have permission to modify this quiz")
    
    # add question
    quiz_question = QuizService.add_question_to_quiz(
        quiz_id=quiz_id,
        question_id=payload.get('question_id'),
        order=payload.get('order'),
        points=payload.get('points', 10)
    )
    
    if not quiz_question:
        abort(400, message="Failed to add question. Question may already exist in quiz.")
    
    return quiz_question


@blp.put("/<int:quiz_id>/questions/<int:question_id>")
@require_teacher
def update_quiz_question(quiz_id, question_id):
    """
    Update Question configuration in Quiz
    
    Request Body:
        - order: New order
        - points: New points
    """
    current_user = g.current_user
    quiz = QuizService.get_quiz_by_id(quiz_id)
    
    if not quiz:
        abort(404, message="Quiz not found")
    
    if quiz.created_by != current_user.id:
        abort(403, message="You can only edit your own quizzes")
    
    data = request.get_json()
    
    update_fields = {}
    if 'order' in data:
        update_fields['order'] = data['order']
    if 'points' in data:
        update_fields['points'] = data['points']
    
    if not update_fields:
        abort(400, message="No fields to update")
    
    quiz_question = QuizService.update_quiz_question(quiz_id, question_id, **update_fields)
    
    if not quiz_question:
        abort(404, message="Question not found in quiz")
    
    return {
        'id': quiz_question.id,
        'order': quiz_question.order,
        'points': quiz_question.points,
        'message': 'Quiz question updated successfully'
    }


@blp.delete("<int:quiz_id>/questions/<int:question_id>")
@blp.response(200)
@require_teacher
def remove_question_from_quiz(quiz_id, question_id):
    """Remove a question from a quiz"""
    current_user = g.current_user
    
    # 验证权限
    quiz = QuizService.get_quiz_by_id(quiz_id)
    if not quiz:
        abort(404, message="Quiz not found")
    
    if quiz.created_by != current_user.id:
        abort(403, message="You don't have permission to modify this quiz")
    
    # 移除问题
    success = QuizService.remove_question_from_quiz(quiz_id, question_id)
    
    if not success:
        abort(404, message="Question not found in this quiz")
    
    return {"message": "Question removed successfully"}



@blp.post("/<int:quiz_id>/assign")
@require_teacher
def assign_quiz_to_classroom(quiz_id):
    """
    Assign Quiz to Classroom
    
    Request Body:
        - classroom_id: Classroom ID (required)
        - due_date: Due date (optional, ISO format)
        - allow_late_submission: Whether to allow late submission (optional)
    """
    current_user = g.current_user
    quiz = QuizService.get_quiz_by_id(quiz_id)
    
    if not quiz:
        abort(404, message="Quiz not found")
    
    if quiz.created_by != current_user.id:
        abort(403, message="You can only assign your own quizzes")
    
    data = request.get_json()
    classroom_id = data.get('classroom_id')
    
    if not classroom_id:
        abort(400, message="classroom_id is required")
    
    # Parse due date
    due_date = None
    if data.get('due_date'):
        try:
            due_date = datetime.fromisoformat(data['due_date'].replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            abort(400, message="Invalid due_date format. Use ISO format.")
    
    classroom_quiz = QuizService.assign_quiz_to_classroom(
        quiz_id=quiz_id,
        classroom_id=classroom_id,
        assigned_by=current_user.id,
        due_date=due_date,
        allow_late_submission=data.get('allow_late_submission', False)
    )
    
    if not classroom_quiz:
        abort(400, message="Failed to assign quiz (may already be assigned or classroom not found)")
    
    return {
        'id': classroom_quiz.id,
        'quiz_id': classroom_quiz.quiz_id,
        'classroom_id': classroom_quiz.classroom_id,
        'due_date': classroom_quiz.due_date.isoformat() if classroom_quiz.due_date else None,
        'allow_late_submission': classroom_quiz.allow_late_submission,
        'message': 'Quiz assigned to classroom successfully'
    }, 201


@blp.delete("/<int:quiz_id>/assign/<int:classroom_id>")
@require_teacher
def unassign_quiz_from_classroom(quiz_id, classroom_id):
    """
    Unassign Quiz from Classroom
    """
    current_user = g.current_user
    quiz = QuizService.get_quiz_by_id(quiz_id)
    
    if not quiz:
        abort(404, message="Quiz not found")
    
    if quiz.created_by != current_user.id:
        abort(403, message="You can only manage your own quizzes")
    
    success = QuizService.unassign_quiz_from_classroom(quiz_id, classroom_id)
    
    if not success:
        abort(404, message="Quiz is not assigned to this classroom")
    
    return {'message': 'Quiz unassigned from classroom successfully'}


@blp.get("/<int:quiz_id>/assignments")
@require_teacher
def get_quiz_assignments(quiz_id):
    """
    Get all assignments for a Quiz
    """
    current_user = g.current_user
    quiz = QuizService.get_quiz_by_id(quiz_id)
    
    if not quiz:
        abort(404, message="Quiz not found")
    
    if quiz.created_by != current_user.id:
        abort(403, message="You can only view your own quizzes")
    
    classroom_quizzes = QuizService.get_quiz_classrooms(quiz_id)
    
    items = []
    for cq in classroom_quizzes:
        if cq.classroom:
            items.append({
                'id': cq.id,
                'classroom_id': cq.classroom.id,
                'classroom_name': cq.classroom.name,
                'classroom_code': cq.classroom.code,
                'assigned_at': cq.assigned_at.isoformat() if cq.assigned_at else None,
                'due_date': cq.due_date.isoformat() if cq.due_date else None,
                'is_overdue': cq.is_overdue,
                'allow_late_submission': cq.allow_late_submission
            })
    
    return {'items': items, 'total': len(items)}



@blp.get("/<int:quiz_id>/attempts")
@require_teacher
def get_quiz_attempts(quiz_id):
    """
    Get all attempt records for a Quiz (teacher view)
    
    base on Submission record to calculate quiz attempts
    """
    current_user = g.current_user
    quiz = QuizService.get_quiz_by_id(quiz_id)
    
    if not quiz:
        abort(404, message="Quiz not found")
    
    if quiz.created_by != current_user.id:
        abort(403, message="You can only view attempts for your own quizzes")
    
    # get all questions of a quiz
    quiz_questions = quiz.quiz_questions if hasattr(quiz, 'quiz_questions') and quiz.quiz_questions else []
    
    if not quiz_questions:
        return {'items': [], 'total': 0}
    
    question_ids = [qq.question_id for qq in quiz_questions]
    
    # seach all student quiz 
    students_with_submissions = db.session.query(
        Submission.student_id,
        User.username
    ).join(
        User, Submission.student_id == User.id
    ).filter(
        Submission.question_id.in_(question_ids)
    ).distinct().all()
    
    if not students_with_submissions:
        return {'items': [], 'total': 0}
    
    items = []
    
    for student_id, student_username in students_with_submissions:
        submissions = Submission.query.filter(
            Submission.student_id == student_id,
            Submission.question_id.in_(question_ids),
            Submission.status == 'completed'
        ).all()
        
        if not submissions:
            continue
        
        completed_count = 0
        total_score = 0
        max_score = 0
        earliest_submission = None
        latest_submission = None
        
        for qq in quiz_questions:
            max_score += qq.points
            
            question_submissions = [s for s in submissions if s.question_id == qq.question_id]
            
            if question_submissions:
                best_submission = max(question_submissions, key=lambda s: s.score or 0)
                completed_count += 1
                
                # calculate score: submission.score (0-100)
                if best_submission.score is not None:
                    total_score += (best_submission.score / 100.0) * qq.points
                
                # update time range
                if not earliest_submission or best_submission.submitted_at < earliest_submission:
                    earliest_submission = best_submission.submitted_at
                if not latest_submission or best_submission.submitted_at > latest_submission:
                    latest_submission = best_submission.submitted_at
        
        if completed_count == 0:
            continue
        
        total_questions = len(quiz_questions)
        if completed_count == total_questions:
            status = 'completed'
        else:
            status = 'in_progress'
        
        percentage = (total_score / max_score * 100) if max_score > 0 else 0
        
        duration_minutes = None
        if earliest_submission and latest_submission and earliest_submission != latest_submission:
            duration = latest_submission - earliest_submission
            duration_minutes = duration.total_seconds() / 60
        
        # build attempt data
        items.append({
            'id': None, 
            'student': {
                'id': student_id,
                'username': student_username
            },
            'started_at': earliest_submission.isoformat() if earliest_submission else None,
            'completed_at': latest_submission.isoformat() if latest_submission and status == 'completed' else None,
            'status': status,
            'score': round(total_score, 1),
            'max_score': max_score,
            'percentage': round(percentage, 1),
            'duration_minutes': round(duration_minutes, 1) if duration_minutes else None
        })
    
    items.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"✓ Found {len(items)} student attempts for quiz {quiz_id}")
    
    return {'items': items, 'total': len(items)}


@blp.get("/<int:quiz_id>/questions")
@require_teacher
def get_quiz_questions(quiz_id):
    """
    Get all questions in the specified quiz (including test case count)
    
    This endpoint is used for management page to display question list
    """
    from app.services.question_service import QuestionService
    
    current_user = g.current_user
    
    # Verify teacher owns this quiz
    quiz = QuizService.get_quiz_by_id(quiz_id)
    if not quiz:
        abort(404, message="Quiz not found")
    
    if quiz.created_by != current_user.id:
        abort(403, message="You can only view questions from your own quizzes")
    
    # Get question list
    items = QuestionService.get_questions_by_quiz(quiz_id)
    
    return {
        "items": items,
        "total": len(items)
    }
