"""
Health check endpoint for monitoring and container orchestration
"""
from flask import Blueprint, Response, jsonify
from sqlalchemy import text
from app.core.extensions import db

health_bp = Blueprint('health', __name__)


@health_bp.route('/live', methods=['GET'])
def liveness():
    """Liveness probe — process is up, no dependency checks (always 200)."""
    return jsonify({'status': 'alive', 'service': 'coderunner'}), 200


@health_bp.route('/metrics', methods=['GET'])
def metrics():
    """Prometheus metrics for the Flask web process (F2)."""
    from core.observability.metrics import metrics_response
    body, status_code, content_type = metrics_response()
    return Response(body, status=status_code, content_type=content_type)

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

    # Check knowledge base (F6). Non-critical: a degraded KB is reported but
    # does NOT flip the service to unhealthy / 503 — RAG searches degrade to
    # empty results, so the platform stays in the load balancer.
    try:
        from ai.knowledge.store import kb_health
        kb = kb_health()
        if kb.get('status') == 'ok':
            health_status['checks']['knowledge_base'] = 'ok'
        else:
            health_status['checks']['knowledge_base'] = f"degraded: {kb.get('error', '')}"
    except Exception as e:
        health_status['checks']['knowledge_base'] = f'degraded: {str(e)}'

    # Return appropriate status code (only the database gates liveness)
    status_code = 200 if health_status['status'] == 'healthy' else 503

    return jsonify(health_status), status_code
