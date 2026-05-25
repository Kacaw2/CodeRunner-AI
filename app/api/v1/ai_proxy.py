"""Reverse proxy to Agent Host for AI chat endpoints.

Flask acts as API Gateway: transparent forwarding to Agent Host at :8100.
Controlled by USE_AGENT_HOST_PROXY env var.
"""

import os
import logging

import httpx
from flask import Response, request, stream_with_context

logger = logging.getLogger(__name__)

AGENT_HOST_URL = os.environ.get("AGENT_HOST_URL", "http://localhost:8100")
USE_AGENT_HOST_PROXY = os.environ.get("USE_AGENT_HOST_PROXY", "false").lower() == "true"


def is_proxy_enabled() -> bool:
    return USE_AGENT_HOST_PROXY


def proxy_chat_create():
    """Proxy POST /api/chat to Agent Host."""
    url = f"{AGENT_HOST_URL}/api/chat"
    headers = {
        "Authorization": request.headers.get("Authorization", ""),
        "Content-Type": "application/json",
    }
    try:
        resp = httpx.request(
            method="POST",
            url=url,
            headers=headers,
            content=request.get_data(),
            timeout=30,
        )
        return (
            resp.content,
            resp.status_code,
            {"Content-Type": resp.headers.get("Content-Type", "application/json")},
        )
    except httpx.ConnectError:
        logger.error("Agent Host unreachable at %s", AGENT_HOST_URL)
        return {"error": "Agent Host unavailable"}, 503
    except Exception as e:
        logger.exception("Proxy error: %s", e)
        return {"error": "Proxy error"}, 502


def proxy_chat_stream(task_id: str):
    """SSE proxy: GET /api/chat/task/{task_id}/stream from Agent Host."""
    url = f"{AGENT_HOST_URL}/api/chat/task/{task_id}/stream"
    last_event = request.args.get("last_event", "0")
    headers = {
        "Authorization": request.headers.get("Authorization", ""),
    }

    def generate():
        try:
            with httpx.stream(
                "GET",
                f"{url}?last_event={last_event}",
                headers=headers,
                timeout=330,
            ) as resp:
                for line in resp.iter_lines():
                    yield line + "\n"
        except httpx.ConnectError:
            yield f"data: {{\"type\": \"error\", \"message\": \"Agent Host unavailable\"}}\n\n"
        except Exception as e:
            logger.exception("SSE proxy error: %s", e)
            yield f"data: {{\"type\": \"error\", \"message\": \"Stream error\"}}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def proxy_chat_status(task_id: str):
    """Proxy GET /api/chat/task/{task_id} to Agent Host."""
    url = f"{AGENT_HOST_URL}/api/chat/task/{task_id}"
    headers = {
        "Authorization": request.headers.get("Authorization", ""),
    }
    try:
        resp = httpx.get(url, headers=headers, timeout=10)
        return (
            resp.content,
            resp.status_code,
            {"Content-Type": resp.headers.get("Content-Type", "application/json")},
        )
    except httpx.ConnectError:
        logger.error("Agent Host unreachable at %s", AGENT_HOST_URL)
        return {"error": "Agent Host unavailable"}, 503
    except Exception as e:
        logger.exception("Proxy error: %s", e)
        return {"error": "Proxy error"}, 502
