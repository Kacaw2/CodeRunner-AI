# app/api/public/__init__.py
"""
Public API blueprint
Public endpoints that do not require authentication
"""
from flask import Blueprint
from app.api.public.health import health_bp

# create public API blueprint
public_bp = Blueprint('public_api', __name__, url_prefix='/api/v1')

__version__ = '1.0.0'

# Import routes (after the blueprint is created to avoid circular imports)
from app.api.public import metrics, questions
