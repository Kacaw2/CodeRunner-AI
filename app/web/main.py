# app/web/main.py
from flask import Blueprint, render_template,jsonify
#import jsonify
main_bp = Blueprint('main', __name__)

@main_bp.get('/')
def home():
    return render_template('public/home.html', page='home')

@main_bp.get('/dashboard')
def dashboard():
    return render_template('dashboard.html', page='dashboard')

@main_bp.get('/healthz')
def healthz():
    return jsonify({"ok": True})
