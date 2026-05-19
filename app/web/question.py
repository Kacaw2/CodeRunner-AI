# app/web/question.py
"""question run page"""
from flask import Blueprint, render_template, abort
from app.models.question import Question

question_bp = Blueprint('question', __name__, url_prefix='/question')


@question_bp.route('/<int:question_id>')
def run_question(question_id):
    """
    code run page (public)
    
    Args:
        question_id: question ID
        
    return:
        - code run page (code editor)
        - submit need login
    """
    question = Question.query.get(question_id)
    if not question:
        abort(404, description="Question not found")
    
    return render_template(
        'question_runner.html',
        question=question
    )
