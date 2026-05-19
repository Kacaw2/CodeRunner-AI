# app/api/public/questions.py
"""
Public Questions API
"""
from flask import jsonify, request
from app.api.public import public_bp
from app.models import Question, Quiz, QuizQuestion

@public_bp.route('/questions', methods=['GET'])
def get_public_questions():
    """
    Get a list of public questions
    Supports pagination and filtering

    Query parameters:
    - limit: maximum number of items to return (default 12, max 100)
    - offset: offset for pagination (default 0)
    - quiz_id: optional, filter by quiz ID
    """
    try:
        # Read query params
        limit = request.args.get('limit', 12, type=int)
        offset = request.args.get('offset', 0, type=int)
        quiz_id = request.args.get('quiz_id', type=int)
        
        # Enforce an upper bound on the limit
        if limit > 100:
            limit = 100
        
        # If quiz_id is provided, filter via the association table
        query = Question.query
        
        # If quiz_id is provided, filter via the association table
        if quiz_id:
            query = query.join(QuizQuestion).filter(
                QuizQuestion.quiz_id == quiz_id
            ).order_by(QuizQuestion.order)
        else:
            query = query.order_by(Question.created_at.desc())
        
        # Pagination
        questions = query.limit(limit).offset(offset).all()
        total = query.count()
        
        # Build response payload
        items = []
        for q in questions:
            # Get the quiz this question belongs to (if any)
            quiz_association = QuizQuestion.query.filter_by(
                question_id=q.id
            ).first()
            
            quiz_info = None
            if quiz_association:
                quiz = Quiz.query.get(quiz_association.quiz_id)
                if quiz and quiz.is_published:
                    quiz_info = {
                        'id': quiz.id,
                        'title': quiz.title
                    }
            
            items.append({
                'id': q.id,
                'title': q.title,
                'description': q.description,
                'starter_code': q.starter_code,
                'points': q.points,
                'programming_language': q.programming_language,
                'quiz': quiz_info,
                'created_at': q.created_at.isoformat() if q.created_at else None
            })
        
        return jsonify({
            'items': items,
            'total': total,
            'limit': limit,
            'offset': offset
        }), 200
        
    except Exception as e:
        print(f"Error in get_public_questions: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@public_bp.route('/questions/<int:question_id>', methods=['GET'])
def get_public_question_detail(question_id):
    """
    Get details of a single question (without answers)
    """
    try:
        question = Question.query.get_or_404(question_id)
        
        # Return only non-hidden test cases and exclude expected outputs
        test_cases = []
        for tc in question.test_cases:
            if not tc.is_hidden:
                test_cases.append({
                    'id': tc.id,
                    'input': tc.input,
                    # Do not return expected_output to the client
                })
        
        # Get associated quiz info
        quiz_association = QuizQuestion.query.filter_by(
            question_id=question.id
        ).first()
        
        quiz_info = None
        if quiz_association:
            quiz = Quiz.query.get(quiz_association.quiz_id)
            if quiz and quiz.is_published:
                quiz_info = {
                    'id': quiz.id,
                    'title': quiz.title,
                    'description': quiz.description
                }
        
        return jsonify({
            'id': question.id,
            'title': question.title,
            'description': question.description,
            'starter_code': question.starter_code,
            'points': question.points,
            'programming_language': question.programming_language,
            'test_cases': test_cases,
            'quiz': quiz_info,
            'created_at': question.created_at.isoformat() if question.created_at else None
        }), 200
        
    except Exception as e:
        print(f"Error in get_public_question_detail: {e}")
        return jsonify({'error': str(e)}), 500
