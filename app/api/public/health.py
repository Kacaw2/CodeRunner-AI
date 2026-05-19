"""
Health check endpoint for monitoring and container orchestration
"""
from flask import Blueprint, jsonify
from sqlalchemy import text
from app.core.extensions import db

health_bp = Blueprint('health', __name__)

@health_bp.route('/health', methods=['GET'])
def health_check():
    """
    Check application and database connection status.
    
    Returns:
        JSON response with health status and HTTP status code
        - 200: All systems healthy
        - 503: Service unhealthy (database connection failed)
    """
    health_status = {
        'status': 'healthy',
        'service': 'coderunner',
        'checks': {}
    }
    
    # Check database connection
    try:
        # Use text() for SQLAlchemy
        db.session.execute(text('SELECT 1'))
        health_status['checks']['database'] = 'ok'
    except Exception as e:
        health_status['checks']['database'] = f'error: {str(e)}'
        health_status['status'] = 'unhealthy'
    
    # Return appropriate status code
    status_code = 200 if health_status['status'] == 'healthy' else 503
    
    return jsonify(health_status), status_code
