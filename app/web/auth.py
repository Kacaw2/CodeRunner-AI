# app/web/auth.py
from flask import Blueprint, render_template, request, url_for

auth_bp = Blueprint('web_auth', __name__, url_prefix='/auth')

@auth_bp.get('/login')
def login_page():
    next_path = request.args.get('next', '/')
    return render_template('auth/login.html', next_path=next_path)

@auth_bp.get('/signup')
def signup_page():
    next_path = request.args.get('next', '/')
    return render_template('auth/signup.html', next_path=next_path)

@auth_bp.get('/logout')
def logout_page():
    return render_template('auth/logout.html', redirect_to=url_for('main.home'))
