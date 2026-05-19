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
                logger.error(f"Remote executor error, fallback to local: {e}", exc_info=True)

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
            logger.warning(f"Core executor not available, using fallback: {e}")
            return ExecutorService._fallback_run_c(
                code, stdin_text, expected_output, time_limit_sec
            )
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
    
    @staticmethod
    def _fallback_run_c(
        code: str,
        stdin_text: str = "",
        expected_output: Optional[str] = None,
        time_limit_sec: float = 2.0
    ) -> Dict[str, Any]:
        """
        Fallback C code executor (local execution, not Docker)
        Only used for development and testing
        """
        import subprocess
        import tempfile
        import os
        import time
        
        with tempfile.TemporaryDirectory() as tmpdir:
            
            source_file = os.path.join(tmpdir, "main.c")
            with open(source_file, 'w') as f:
                f.write(code)
            
            output_file = os.path.join(tmpdir, "main")
            
            # compile
            try:
                compile_result = subprocess.run(
                    ["gcc", "-o", output_file, source_file, "-std=c11", "-Wall"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if compile_result.returncode != 0:
                    return {
                        "status": "CE",
                        "compiled": False,
                        "stdout": "",
                        "stderr": compile_result.stderr,
                        "time_ms": 0,
                        "passed": False,
                        "expected": expected_output,
                        "expected_match": None,
                        "compile_log": compile_result.stderr
                    }
            except subprocess.TimeoutExpired:
                return {
                    "status": "CE",
                    "compiled": False,
                    "stdout": "",
                    "stderr": "Compilation timeout",
                    "time_ms": 0,
                    "passed": False,
                    "expected": expected_output,
                    "expected_match": None
                }
            except FileNotFoundError:
                return {
                    "status": "SYSTEM_ERROR",
                    "compiled": False,
                    "stdout": "",
                    "stderr": "gcc not found - Docker is recommended",
                    "time_ms": 0,
                    "passed": False,
                    "error": "gcc compiler not found. Please use Docker executor.",
                    "expected": expected_output,
                    "expected_match": None
                }
            
            # run state
            try:
                start_time = time.time()
                
                run_result = subprocess.run(
                    [output_file],
                    input=stdin_text,
                    capture_output=True,
                    text=True,
                    timeout=time_limit_sec
                )
                
                elapsed_ms = int((time.time() - start_time) * 1000)
                
                stdout = ExecutorService.normalize_output(run_result.stdout)
                stderr = ExecutorService.normalize_output(run_result.stderr)
                
                # judge
                passed = False
                expected_match = None
                
                if expected_output is not None:
                    expected_normalized = ExecutorService.normalize_output(expected_output)
                    expected_match = (stdout == expected_normalized)
                    passed = expected_match and run_result.returncode == 0
                else:
                    passed = run_result.returncode == 0
                
                # status
                if run_result.returncode != 0:
                    status = "RE"
                elif expected_match is False:
                    status = "WA"
                else:
                    status = "AC"
                
                return {
                    "status": status,
                    "compiled": True,
                    "stdout": stdout,
                    "stderr": stderr,
                    "time_ms": elapsed_ms,
                    "passed": passed,
                    "expected": expected_output,
                    "expected_match": expected_match
                }
                
            except subprocess.TimeoutExpired:
                return {
                    "status": "TLE",
                    "compiled": True,
                    "stdout": "",
                    "stderr": "Time limit exceeded",
                    "time_ms": int(time_limit_sec * 1000),
                    "passed": False,
                    "expected": expected_output,
                    "expected_match": None
                }
