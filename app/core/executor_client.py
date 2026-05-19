import os
import requests

EXECUTOR_URL = os.getenv("EXECUTOR_REMOTE_URL")
EXECUTOR_TOKEN = os.getenv("EXECUTOR_API_TOKEN")

def run_code_remote(code, language="python", stdin=None,
                    expected_output=None, time_limit_sec=2.0):
    if not EXECUTOR_URL:
        raise RuntimeError("EXECUTOR_REMOTE_URL not set")

    payload = {
        "code": code,
        "language": language,
        "stdin": stdin,
        "expected_output": expected_output,
        "time_limit_sec": time_limit_sec,
    }
    headers = {"Content-Type": "application/json"}
    if EXECUTOR_TOKEN:
        headers["X-EXECUTOR-TOKEN"] = EXECUTOR_TOKEN

    resp = requests.post(EXECUTOR_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()
