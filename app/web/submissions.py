# app/web/submissions.py
"""
submission web page route
"""
from flask import Blueprint, render_template
from app.auth import web_login_required  

submissions_web_bp = Blueprint(
    'submissions_web',
    __name__, 
    url_prefix='/submissions'
)


@submissions_web_bp.route('/')
@web_login_required  # redirect to login page
def list_submissions():
    """
    submission list page
    display all students' submission history
    """
    return render_template('submissions.html')


@submissions_web_bp.route('/<int:submission_id>')
@web_login_required  
def submission_detail(submission_id):
    """
    submission detail page
    show single submission detail
    """
    return render_template('submission_detail.html', submission_id=submission_id)
