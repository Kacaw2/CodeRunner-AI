# executor.py
"""
Code Executor for Render
Runs code directly in Render container without Docker
Optimized for single-container deployment
Fixed: Resource limits conflict with timeout command
"""
import os
import time
import tempfile
import subprocess
import pathlib
import signal
import sys
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)
EXECUTOR_TMP_DIR = os.getenv("EXECUTOR_TMP_DIR", "/tmp/executor")
os.makedirs(EXECUTOR_TMP_DIR, exist_ok=True)

# Try to import resource (Linux only)
try:
    import resource
    HAS_RESOURCE = True
except ImportError:
    HAS_RESOURCE = False
    logger.warning("'resource' module not available - resource limits disabled (macOS)")

class ExecutorConfig:
    """Executor configuration"""
    # Execution mode: 'native' for Render, 'docker' for local dev
    USE_DOCKER = os.getenv("USE_DOCKER", "false").lower() == "true"
    
    # Resource limits
    MAX_MEMORY_MB = int(os.getenv("EXECUTOR_MAX_MEMORY_MB", "256"))
    MAX_CPU_TIME_SEC = int(os.getenv("EXECUTOR_MAX_CPU_TIME", "10"))
    
    # Default timeouts
    DEFAULT_TIMEOUT = float(os.getenv("EXECUTOR_DEFAULT_TIMEOUT", "2.0"))
    
    # Output limits
    MAX_STDOUT_LENGTH = int(os.getenv("EXECUTOR_MAX_STDOUT", "10000"))
    MAX_STDERR_LENGTH = int(os.getenv("EXECUTOR_MAX_STDERR", "4000"))
    
    # Compilation options
    C_COMPILE_FLAGS = "-std=c11 -O2 -pipe -Wall"
    PYTHON_VERSION = "python3"

class CodeExecutor:
    """Code executor - runs directly on Render without Docker"""
    
    def __init__(self, config: ExecutorConfig = None):
        self.config = config or ExecutorConfig()
    
    @staticmethod
    def _normalize_input(text: str) -> str:
        """
        Normalize input text by parsing escape sequences
        - Convert \\n to actual newline characters
        - Convert \\t to actual tab characters
        
        Args:
            text: Original text with escape sequences
            
        Returns:
            str: Text with parsed escape sequences
        """
        if not text:
            return text
        return text.replace('\\n', '\n').replace('\\t', '\t')
    
    @staticmethod
    def _normalize_output(text: str) -> str:
        """
        Normalize output text for comparison
        - Remove trailing whitespace from each line
        - Remove trailing empty lines
        
        Args:
            text: Original text
            
        Returns:
            str: Normalized text
        """
        lines = [line.rstrip() for line in text.splitlines()]
        while lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines)
    
    def _set_resource_limits(self):
        """
        Set resource limits for subprocess (Linux only)
        
        IMPORTANT: Reduced RLIMIT_NPROC to prevent fork failures
        """
        if not HAS_RESOURCE:
            return
            
        try:
            # CPU time limit (in seconds)
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (self.config.MAX_CPU_TIME_SEC, self.config.MAX_CPU_TIME_SEC)
            )
            
            # Memory limit (in bytes)
            max_memory_bytes = self.config.MAX_MEMORY_MB * 1024 * 1024
            resource.setrlimit(
                resource.RLIMIT_AS,
                (max_memory_bytes, max_memory_bytes)
            )
            
            # File size limit (10MB)
            resource.setrlimit(
                resource.RLIMIT_FSIZE,
                (10 * 1024 * 1024, 10 * 1024 * 1024)
            )
            
            # NOTE: RLIMIT_NPROC removed to prevent fork failures
            # The subprocess timeout mechanism is sufficient
            
        except Exception as e:
            logger.warning(f"Could not set resource limits: {e}")
    
    def run_c_code(
        self,
        code: str,
        stdin: str = "",
        expected_output: Optional[str] = None,
        time_limit_sec: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Compile and run C code directly on Render
        
        Args:
            code: C source code
            stdin: Standard input
            expected_output: Expected output (if provided, will be compared)
            time_limit_sec: Time limit in seconds
            
        Returns:
            dict: Execution result
        """
        start_time = time.monotonic()
        time_limit = time_limit_sec or self.config.DEFAULT_TIMEOUT
        
        # Log execution request
        logger.info(f"[C Execute] stdin type: {type(stdin)}, length: {len(stdin) if stdin else 0}")
        logger.info(f"[C Execute] stdin preview: {repr(stdin[:100] if stdin else stdin)}")
        
        # Normalize stdin and expected_output to parse escape sequences
        normalized_stdin = self._normalize_input(stdin or "")
        normalized_expected = self._normalize_input(expected_output) if expected_output else None
        
        logger.info(f"[C Execute] normalized stdin: {repr(normalized_stdin[:100] if normalized_stdin else normalized_stdin)}")
        
        # Create temporary directory
        with tempfile.TemporaryDirectory(dir=EXECUTOR_TMP_DIR) as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            
            # Write source file
            try:
                (tmp_path / "main.c").write_text(code or "", encoding="utf-8")
                
            except Exception as e:
                logger.error(f"Failed to write files: {e}")
                return self._error_result("SYSTEM_ERROR", f"Failed to prepare files: {e}")
            
            # 1. Compilation phase
            compile_result = self._compile_c_native(tmp_path)
            if compile_result["status"] != "OK":
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "status": "CE",
                    "passed": False if normalized_expected is not None else None,
                    "stdout": "",
                    "stderr": "",
                    "compile_log": compile_result["compile_log"],
                    "time_ms": elapsed_ms,
                    "error_message": "Compilation failed"
                }
            
            # 2. Execution phase
            run_result = self._run_binary_native(tmp_path, normalized_stdin, time_limit)
            
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            
            # 3. Determine result status
            status = run_result["status"]
            passed = None
            
            if normalized_expected is not None and status == "OK":
                actual_normalized = self._normalize_output(run_result["stdout"])
                expected_normalized = self._normalize_output(normalized_expected)
                passed = (actual_normalized == expected_normalized)
                
                if not passed:
                    status = "WA"
                else:
                    status = "AC"
            elif normalized_expected is not None:
                passed = False
            elif status == "OK":
                status = "AC"
            
            return {
                "status": status,
                "passed": passed,
                "stdout": run_result["stdout"][:self.config.MAX_STDOUT_LENGTH],
                "stderr": run_result["stderr"][:self.config.MAX_STDERR_LENGTH],
                "compile_log": compile_result["compile_log"],
                "time_ms": elapsed_ms,
                "error_message": run_result.get("error_message", "")
            }
    
    def _compile_c_native(self, tmp_path: pathlib.Path) -> Dict[str, Any]:
        """Compile C code directly (no Docker)"""
        compile_cmd = [
            "gcc",
            "-std=c11", "-O2", "-pipe", "-Wall",
            "-o", "main",
            "main.c"
        ]
        
        logger.info(f"Compiling: {' '.join(compile_cmd)}")
        
        try:
            result = subprocess.run(
                compile_cmd,
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            compile_log = (result.stderr + result.stdout).strip()
            
            if result.returncode != 0:
                logger.warning(f"Compilation failed: {compile_log[:200]}")
                return {
                    "status": "CE",
                    "compile_log": compile_log
                }
            
            logger.info("Compilation successful")
            return {
                "status": "OK",
                "compile_log": compile_log
            }
            
        except subprocess.TimeoutExpired:
            return {
                "status": "CE",
                "compile_log": "Compilation timeout"
            }
        except FileNotFoundError:
            return {
                "status": "CE",
                "compile_log": "gcc compiler not found. Please install gcc on Render."
            }
        except Exception as e:
            logger.error(f"Compilation error: {e}")
            return {
                "status": "CE",
                "compile_log": f"System error during compilation: {e}"
            }
    
    def _run_binary_native(
        self,
        tmp_path: pathlib.Path,
        stdin_text: str,
        time_limit_sec: float
    ) -> Dict[str, Any]:
        """
        Run compiled binary directly (no Docker)
        
        FIXED: Use subprocess.run timeout instead of timeout command
        This avoids fork issues with resource limits
        """
        logger.info(f"[C Run] stdin length: {len(stdin_text)}, preview: {repr(stdin_text[:50])}")
        
        try:
            # CRITICAL: Use subprocess timeout directly, not timeout command
            # This avoids the "fork: Resource temporarily unavailable" error
            result = subprocess.run(
                ["./main"],
                cwd=tmp_path,
                input=stdin_text,
                capture_output=True,
                text=True,
                timeout=time_limit_sec,
                preexec_fn=self._set_resource_limits if HAS_RESOURCE else None
            )
            
            stdout = result.stdout
            stderr = result.stderr
            return_code = result.returncode
            
            logger.info(f"[C Run] return_code: {return_code}, stdout length: {len(stdout)}")
            
        except subprocess.TimeoutExpired:
            logger.warning("Execution timeout")
            return {
                "status": "TLE",
                "stdout": "",
                "stderr": "Time limit exceeded",
                "error_message": "Time limit exceeded"
            }
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return {
                "status": "RE",
                "stdout": "",
                "stderr": str(e),
                "error_message": str(e)
            }
        
        # Determine execution status
        if return_code != 0:
            status = "RE"
            error_message = f"Runtime error (exit code: {return_code})"
        else:
            status = "OK"
            error_message = ""
        
        return {
            "status": status,
            "stdout": stdout,
            "stderr": stderr,
            "error_message": error_message
        }
    
    def run_python_code(
        self,
        code: str,
        stdin: str = "",
        expected_output: Optional[str] = None,
        time_limit_sec: Optional[float] = None
    ) -> Dict[str, Any]:
        """Run Python code directly on Render"""
        start_time = time.monotonic()
        time_limit = time_limit_sec or self.config.DEFAULT_TIMEOUT
        
        # Log execution request
        logger.info(f"[Python Execute] stdin type: {type(stdin)}, length: {len(stdin) if stdin else 0}")
        logger.info(f"[Python Execute] stdin preview: {repr(stdin[:100] if stdin else stdin)}")
        
        # Normalize stdin and expected_output
        normalized_stdin = self._normalize_input(stdin or "")
        normalized_expected = self._normalize_input(expected_output) if expected_output else None
        
        logger.info(f"[Python Execute] normalized stdin: {repr(normalized_stdin[:100] if normalized_stdin else normalized_stdin)}")
        
        with tempfile.TemporaryDirectory(dir=EXECUTOR_TMP_DIR) as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            
            try:
                (tmp_path / "main.py").write_text(code or "", encoding="utf-8")
                
            except Exception as e:
                logger.error(f"Failed to write files: {e}")
                return self._error_result("SYSTEM_ERROR", f"Failed to prepare files: {e}")
            
            # Run Python
            run_result = self._run_python_native(tmp_path, normalized_stdin, time_limit)
            
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            
            # Determine result status
            status = run_result["status"]
            passed = None
            
            if normalized_expected is not None and status == "AC":
                actual_normalized = self._normalize_output(run_result["stdout"])
                expected_normalized = self._normalize_output(normalized_expected)
                passed = (actual_normalized == expected_normalized)
                
                if not passed:
                    status = "WA"
            elif normalized_expected is not None:
                passed = False
            
            return {
                "status": status,
                "passed": passed,
                "stdout": run_result["stdout"][:self.config.MAX_STDOUT_LENGTH],
                "stderr": run_result["stderr"][:self.config.MAX_STDERR_LENGTH],
                "compile_log": "",
                "time_ms": elapsed_ms,
                "error_message": run_result.get("error_message", "")
            }
    
    def _run_python_native(
        self,
        tmp_path: pathlib.Path,
        stdin_text: str,
        time_limit_sec: float
    ) -> Dict[str, Any]:
        """
        Run Python code directly (no Docker)
        
        FIXED: Use subprocess.run timeout instead of timeout command
        This avoids fork issues with resource limits
        """
        logger.info(f"[Python Run] stdin length: {len(stdin_text)}, preview: {repr(stdin_text[:50])}")
        
        try:
            # CRITICAL FIX: 
            # 1. Use subprocess timeout directly (not timeout command)
            # 2. Pass stdin_text via input parameter
            result = subprocess.run(
                [self.config.PYTHON_VERSION, "main.py"],
                cwd=tmp_path,
                input=stdin_text,  # ← Key fix for stdin!
                capture_output=True,
                text=True,
                timeout=time_limit_sec,
                preexec_fn=self._set_resource_limits if HAS_RESOURCE else None
            )
            
            stdout = result.stdout
            stderr = result.stderr
            return_code = result.returncode
            
            logger.info(f"[Python Run] return_code: {return_code}, stdout length: {len(stdout)}")
            
        except subprocess.TimeoutExpired:
            return {
                "status": "TLE",
                "stdout": "",
                "stderr": "Time limit exceeded",
                "error_message": "Time limit exceeded"
            }
        except Exception as e:
            logger.error(f"Python execution error: {e}")
            return {
                "status": "RE",
                "stdout": "",
                "stderr": str(e),
                "error_message": str(e)
            }
        
        # Determine status
        if return_code != 0:
            status = "RE"
            error_message = f"Runtime error (exit code: {return_code})"
        else:
            status = "AC"
            error_message = ""
        
        return {
            "status": status,
            "stdout": stdout,
            "stderr": stderr,
            "error_message": error_message
        }
    
    def run_code(
        self,
        code: str,
        language: str = "c",
        stdin: str = "",
        expected_output: Optional[str] = None,
        time_limit_sec: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Run code according to language
        
        Args:
            code: Source code
            language: Programming language (c, python)
            stdin: Standard input
            expected_output: Expected output
            time_limit_sec: Time limit
            
        Returns:
            dict: Execution result
        """
        language = language.lower()
        
        if language in ['python', 'py', 'python3']:
            return self.run_python_code(code, stdin, expected_output, time_limit_sec)
        elif language in ['c']:
            return self.run_c_code(code, stdin, expected_output, time_limit_sec)
        else:
            return self._error_result("UNSUPPORTED", f"Language {language} not yet supported")
    
    @staticmethod
    def _error_result(status: str, message: str) -> Dict[str, Any]:
        """Build an error result"""
        return {
            "status": status,
            "passed": False,
            "stdout": "",
            "stderr": "",
            "compile_log": "",
            "time_ms": 0,
            "error_message": message
        }


# Backward compatibility functions
_default_executor = CodeExecutor()


def _native_allowed() -> bool:
    """Native (in-process subprocess) execution is fail-closed by default.

    P0 sandbox hardening: untrusted student code must run in the isolated
    executor microservice (EXECUTOR_REMOTE_URL), never inside the web
    container. These backward-compat entry points therefore refuse to run
    code natively unless EXECUTOR_ALLOW_NATIVE is explicitly enabled — which
    is only appropriate inside the sandbox executor container itself or for
    deliberate local development.
    """
    return os.getenv("EXECUTOR_ALLOW_NATIVE", "false").lower() in ("true", "1", "yes")


def _executor_unavailable_result(expected_output: Optional[str] = None) -> Dict[str, Any]:
    """Fail-closed result returned when no sandbox is available."""
    return {
        "status": "EXECUTOR_UNAVAILABLE",
        "compiled": False,
        "passed": False,
        "stdout": "",
        "stderr": "Sandbox executor unavailable",
        "compile_log": "",
        "time_ms": 0,
        "expected": expected_output,
        "expected_match": None,
        "error_message": "Sandbox executor unavailable",
    }


def run_c_in_docker(
    code: str,
    stdin: str = "",
    expected_output: Optional[str] = None,
    time_limit_sec: float = 2.0
) -> Dict[str, Any]:
    """Run C code natively — fail-closed unless native execution is allowed."""
    if not _native_allowed():
        logger.error(
            "run_c_in_docker invoked without a sandbox; native execution is "
            "disabled (set EXECUTOR_ALLOW_NATIVE=true only inside the sandbox "
            "executor). Failing closed."
        )
        return _executor_unavailable_result(expected_output)
    return _default_executor.run_c_code(
        code=code,
        stdin=stdin,
        expected_output=expected_output,
        time_limit_sec=time_limit_sec
    )

def run_code_in_docker(
    code: str,
    language: str = "c",
    stdin: str = "",
    expected_output: Optional[str] = None,
    time_limit_sec: float = 2.0
) -> Dict[str, Any]:
    """Run code natively — fail-closed unless native execution is allowed."""
    if not _native_allowed():
        logger.error(
            "run_code_in_docker invoked without a sandbox; native execution is "
            "disabled (set EXECUTOR_ALLOW_NATIVE=true only inside the sandbox "
            "executor). Failing closed."
        )
        return _executor_unavailable_result(expected_output)
    return _default_executor.run_code(
        code=code,
        language=language,
        stdin=stdin,
        expected_output=expected_output,
        time_limit_sec=time_limit_sec
    )
