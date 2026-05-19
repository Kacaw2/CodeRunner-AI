# app/api/public/quizzes.py
"""Public Quiz API - for dashboard filter"""
from flask_smorest import Blueprint
from app.models.quiz import Quiz
from app.core.extensions import db
from sqlalchemy import select

public_quiz_blp = Blueprint(
    "quizzes_public",
    __name__,
    description="Public Quiz APIs",
    url_prefix="/api/public"
)


@public_quiz_blp.get("/quizzes")
def get_public_quizzes():
    """
    Get list of all quizzes (for filter dropdown)
    
    Returns basic quiz information without sensitive details
    """
    try:
        # Query all quizzes
        quizzes = db.session.execute(
            select(Quiz).order_by(Quiz.id.desc())
        ).scalars().all()
        
        # Return simplified quiz list
        items = [
            {
                "id": quiz.id,
                "title": quiz.title,
                "created_at": quiz.created_at.isoformat() if quiz.created_at else None
            }
            for quiz in quizzes
        ]
        
        return {
            "items": items,
            "total": len(items)
        }, 200
        
    except Exception as e:
        return {
            "error": "Failed to load quizzes",
            "message": str(e)
        }, 500


