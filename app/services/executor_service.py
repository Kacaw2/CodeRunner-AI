# app/services/executor_service.py
"""
Code execution service
Used to safely execute user code in Docker containers
"""
import os
from typing import Dict, Any, Optional

import logging

logger = logging.getLogger(__name__)


class ExecutorService:
    """Code execution service"""
    @staticmethod
    def normalize_output(text: str) -> str:
        """
        Normalize output text
        - Normalize line endings to \n
        - Strip trailing newlines

        Args:
            text: Original text

        Returns:
            str: Normalized text
        """
        return (text or "").replace("\r\n", "\n").rstrip("\n")
    
    @staticmethod
    def run_code(
        code: str,
        language: str = "c",
        stdin_text: str = "",
        expected_output: Optional[str] = None,
        time_limit_sec: float = 2.0
    ) -> Dict[str, Any]:
        """
        Run code (multi-language support)

        Args:
            code: Source code
            language: Programming language (c, python)
            stdin_text: Standard input
            expected_output: Expected output
            time_limit_sec: Time limit in seconds
        """
        remote_url = os.getenv("EXECUTOR_REMOTE_URL")
        if remote_url:
            try:
                from app.core.executor_client import run_code_remote
                result = run_code_remote(
                    code=code,
                    language=language,
                    stdin=stdin_text,
                    expected_output=expected_output,
                    time_limit_sec=time_limit_sec,
                )
                return {
                    "status": result.get("status", "UNKNOWN"),
                    "compiled": result.get("status") != "CE",
                    "passed": result.get("passed"),
                    "stdout": result.get("stdout", ""),
                    "stderr": result.get("stderr", ""),
                    "time_ms": result.get("time_ms", 0),
                    "compile_log": result.get("compile_log", ""),
                    "expected": expected_output,
                    "expected_match": result.get("expected_match"),
                    "error_message": result.get("error_message", ""),
                }
            except Exception as e:
                # Fail-closed: do NOT silently fall back to native in-container
                # execution when the sandbox executor is unreachable.
                logger.error(f"Remote executor error: {e}", exc_info=True)
                return {
                    "status": "EXECUTOR_UNAVAILABLE",
                    "compiled": False,
                    "passed": False,
                    "stdout": "",
                    "stderr": "Sandbox executor unavailable",
                    "time_ms": 0,
                    "compile_log": "",
                    "expected": expected_output,
                    "expected_match": None,
                    "error_message": "Sandbox executor unavailable",
                }

        try:
            from app.core.executor import run_code_in_docker
            result = run_code_in_docker(
                code=code,
                language=language,
                stdin=stdin_text,
                expected_output=expected_output,
                time_limit_sec=time_limit_sec
            )
            
            return {
                "status": result.get("status", "UNKNOWN"),
                "compiled": result.get("status") != "CE",
                "passed": result.get("passed"),
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
                "time_ms": result.get("time_ms", 0),
                "compile_log": result.get("compile_log", ""),
                "expected": expected_output,
                "expected_match": result.get("passed") if expected_output else None,
                "error_message": result.get("error_message", "")
            }
            
        except Exception as e:
            logger.error(f"Executor error: {e}", exc_info=True)
            return {
                "status": "SYSTEM_ERROR",
                "compiled": False,
                "passed": False,
                "stdout": "",
                "stderr": str(e),
                "time_ms": 0,
                "compile_log": "",
                "expected": expected_output,
                "expected_match": None,
                "error_message": str(e)
            }


    @staticmethod
    def run_c_in_docker(
        code: str,
        stdin_text: str = "",
        expected_output: Optional[str] = None,
        time_limit_sec: float = 2.0
    ) -> Dict[str, Any]:
        """
        Run C code in a Docker container
        
        Args:
            code: C source code
            stdin_text: Standard input content
            expected_output: Expected output (optional)
            time_limit_sec: Time limit (seconds)
            
        Returns:
            dict: Execution result
        """
        try:
            # core.executor 
            from app.core.executor import run_c_in_docker as core_runner
            
            result = core_runner(
                code=code,
                stdin=stdin_text,
                expected_output=expected_output,
                time_limit_sec=time_limit_sec
            )
            
            return {
                "status": result.get("status", "UNKNOWN"),
                "compiled": result.get("status") != "CE",
                "passed": result.get("passed"),
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
                "time_ms": result.get("time_ms", 0),
                "compile_log": result.get("compile_log", ""),
                "expected": expected_output,
                "expected_match": result.get("passed") if expected_output else None,
                "error_message": result.get("error_message", "")
            }
            
        except ImportError as e:
            # Fail-closed: the native subprocess fallback has been removed.
            # Untrusted code must run in the sandbox executor microservice.
            logger.error(f"Core executor unavailable (no sandbox): {e}")
            return {
                "status": "EXECUTOR_UNAVAILABLE",
                "compiled": False,
                "passed": False,
                "stdout": "",
                "stderr": "Sandbox executor unavailable",
                "time_ms": 0,
                "expected": expected_output,
                "expected_match": None,
                "error_message": "Sandbox executor unavailable",
            }
        except Exception as e:
            logger.error(f"Executor error: {e}")
            return {
                "status": "SYSTEM_ERROR",
                "compiled": False,
                "passed": False,
                "stdout": "",
                "stderr": "",
                "time_ms": 0,
                "error": str(e),
                "expected": expected_output,
                "expected_match": None
            }
