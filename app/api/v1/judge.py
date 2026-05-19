# app/api/v1/judge.py
"""
Judge (Code Evaluation) API Endpoints
"""
import os

from flask import Blueprint, request, jsonify
from flask_smorest import abort

from app.services.executor_service import ExecutorService
from app.schemas.judge_schema import CodeRunInputSchema

bp = Blueprint(
    "judge",
    __name__,
    url_prefix="/api/v1/judge"
)


@bp.route("/run", methods=["POST"])
def run_code():
    """
    Run code and return results
    
    Request Body:
        {
            "code": "#include <stdio.h>\\nint main(){...}",
            "language": "c",  # optional, default "c"
            "input": "test input",  # optional
            "expected_output": "expected output",
            "time_limit_sec": 2.0  # optional, default 2.0
        }
    
    Returns:
        200: Execution result
            {
                "status": "AC|WA|CE|RE|TLE|SYSTEM_ERROR",
                "passed": true|false|null,
                "compiled": true|false,
                "stdout": "program output",
                "stderr": "error messages",
                "time_ms": 123,
                "compile_log": "compilation output",
                "expected": "expected output",
                "expected_match": true|false|null,
                "error_message": "error details"
            }
        400: Invalid request parameters
        500: System error
    
    Status Codes:
        - AC: Accepted (Correct) - 
        - WA: Wrong Answer 
        - CE: Compilation Error -
        - RE: Runtime Error - 
        - TLE: Time Limit Exceeded
        - SYSTEM_ERROR: System error
    """
    data = request.get_json(silent=True) or {}
    
    # Validate input
    schema = CodeRunInputSchema()
    try:
        validated_data = schema.load(data)
    except Exception as e:
        return jsonify({"error": str(e), "status": "INVALID_INPUT"}), 400
    
    code = validated_data["code"]
    language = validated_data.get("language", "c")
    stdin_text = validated_data.get("input", "")
    expected_output = validated_data.get("expected_output")  
    time_limit = validated_data.get("time_limit_sec", 2.0)
    
    # Check if code is empty
    if not code.strip():
        return jsonify({"error": "code is required", "status": "INVALID_INPUT"}), 400
    
    # Execute code
    try:
        result = ExecutorService.run_code(
            code=code,
            language=language,
            stdin_text=stdin_text,
            expected_output=expected_output, 
            time_limit_sec=time_limit
        )
        
        # Add executor type for debugging
        result["executor"] = (
            "remote" if os.getenv("EXECUTOR_REMOTE_URL") else "local"
        )
        
        return jsonify(result), 200
        
    except FileNotFoundError as e:
        return jsonify({
            "status": "SYSTEM_ERROR",
            "error": f"Docker not found: {e}",
            "compiled": False,
            "passed": False,
            "stdout": "",
            "stderr": "Docker is not available"
        }), 500
        
    except Exception as e:
        import traceback
        return jsonify({
            "status": "SYSTEM_ERROR",
            "error": str(e),
            "compiled": False,
            "passed": False,
            "stdout": "",
            "stderr": traceback.format_exc()
        }), 500


@bp.route("/health", methods=["GET"])
def health_check():
    """
    Check judge service health status
    
    Returns:
        200: Service is healthy
            {
                "status": "healthy|degraded",
                "message": "...",
                "docker_available": true|false,
                "docker_version": "Docker version ..."
            }
        503: Service is unhealthy
    """
    try:
        # Simple health check - test if Docker is available
        import subprocess
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            return jsonify({
                "status": "healthy",
                "message": "Judge service is running",
                "docker_available": True,
                "docker_version": result.stdout.strip()
            }), 200
        else:
            return jsonify({
                "status": "degraded",
                "message": "Judge service running but Docker unavailable",
                "docker_available": False
            }), 200
            
    except FileNotFoundError:
        return jsonify({
            "status": "degraded",
            "message": "Docker not found, using fallback executor",
            "docker_available": False
        }), 200
        
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "message": str(e),
            "docker_available": False
        }), 503
