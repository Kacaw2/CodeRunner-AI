# app/api/public/metrics.py
"""
Public metrics API
Provides global statistics without requiring authentication
"""
from datetime import datetime, timedelta
from flask import jsonify
from sqlalchemy import func, distinct
from app.api.public import public_bp
from app.models import User, Quiz, Problem, Question, Submission

@public_bp.route('/metrics/overview', methods=['GET'])
def get_overview():
    """
    Get global statistics

    Returns:
    - users: total number of users
    - quizzes: total number of quizzes
    - questions: total number of questions
    - submissions_24h: number of submissions in the last 24 hours
    - active_users: number of active users (users who submitted within the last 7 days)
    """
    try:
        # Totals
        total_users = User.query.count()
        # only published quizzes
        total_quizzes = Quiz.query.filter_by(is_published=True).count()  
        total_questions = Problem.query.count()
        
        #  Submissions in the past 24 hours 
        now = datetime.now()
        yesterday = now - timedelta(days=1)
        submissions_24h = Submission.query.filter(
            Submission.submitted_at >= yesterday
        ).count()
        
        # Active users (submitted within the last 7 days)
        week_ago = now - timedelta(days=7)
        # Use func.count(distinct(...)) count unique users
        active_users = Submission.query\
            .filter(Submission.submitted_at >= week_ago)\
            .with_entities(func.count(distinct(Submission.student_id)))\
            .scalar() or 0
        
        return jsonify({
            'global': {
                'users': total_users,
                'quizzes': total_quizzes,
                'questions': total_questions,
                'submissions_24h': submissions_24h,
                'active_users': active_users
            }
        }), 200
        
    except Exception as e:
        print(f"Error in get_overview: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'global': {
                'users': 0,
                'quizzes': 0,
                'questions': 0,
                'submissions_24h': 0,
                'active_users': 0
            }
        }), 500


@public_bp.route('/metrics/latest_submissions', methods=['GET'])
def get_latest_submissions():
    """
    Get the latest submission records

    Returns the latest 10 submissions, including username and question title
    """
    try:
        # Fetch the latest 10 submissions
        submissions = Submission.query\
            .order_by(Submission.submitted_at.desc())\
            .limit(10)\
            .all()
        
        items = []
        for sub in submissions:
            # Fetch username and question title
            user = User.query.get(sub.student_id) if sub.student_id else None
            question = Question.query.get(sub.question_id) if sub.question_id else None
            
            items.append({
                'id': sub.id,
                'user_name': user.username if user else 'Unknown',
                'question_id': sub.question_id,
                'question_title': question.title if question else f'Question #{sub.question_id}',
                'status': sub.status,
                'score': sub.score,
                'submitted_at': sub.submitted_at.strftime('%Y-%m-%d %H:%M') if sub.submitted_at else None
            })
        
        return jsonify({
            'items': items,
            'total': len(items)
        }), 200
        
    except Exception as e:
        print(f"Error in get_latest_submissions: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'items': []
        }), 500


@public_bp.route('/metrics/submissions_7d', methods=['GET'])
def get_submissions_7d():
    """
    Get submission stats for the last 7 days (for charts)

    Returns the number of submissions per day to draw a trend chart
    """
    try:
        labels = []
        counts = []
        
        # Count submissions per day over the last 7 days
        for i in range(6, -1, -1):
            date = datetime.utcnow().date() - timedelta(days=i)
            start_time = datetime.combine(date, datetime.min.time())
            end_time = datetime.combine(date, datetime.max.time())
            
            count = Submission.query.filter(
                Submission.submitted_at >= start_time,
                Submission.submitted_at <= end_time
            ).count()
            
            labels.append(date.strftime('%m/%d'))
            counts.append(count)
        
        return jsonify({
            'labels': labels,
            'counts': counts
        }), 200
        
    except Exception as e:
        print(f"Error in get_submissions_7d: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'labels': [],
            'counts': []
        }), 500
