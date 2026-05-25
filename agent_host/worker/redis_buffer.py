"""Redis buffer for streaming SSE events.

Uses the same key schema as app/agents/chat_worker.py so both Flask and
FastAPI can read/write the same buffers during the migration period.

Key schema:
  chat_task:{task_id}:status  -> "pending" | "processing" | "completed" | "failed"
  chat_task:{task_id}:buffer  -> List[JSON str]  (ordered SSE events)
  chat_task:{task_id}:agent   -> routed agent type

  workflow:{run_id}:status    -> workflow status string
  workflow:{run_id}:buffer    -> List[JSON str]  (ordered SSE events)
"""

import json
import logging

import redis

from agent_host.core.config import get_settings

logger = logging.getLogger(__name__)

_client: redis.Redis | None = None


def get_redis() -> redis.Redis | None:
    global _client
    if _client is None:
        settings = get_settings()
        try:
            _client = redis.from_url(settings.REDIS_URL, decode_responses=True)
            _client.ping()
        except Exception as e:
            logger.warning("Redis connection failed: %s", e)
            _client = None
    return _client


# ── Chat task keys ──────────────────────────────────────────────

_CT_STATUS = "chat_task:{task_id}:status"
_CT_BUFFER = "chat_task:{task_id}:buffer"
_CT_AGENT = "chat_task:{task_id}:agent"

# ── Workflow keys ───────────────────────────────────────────────

_WF_STATUS = "workflow:{run_id}:status"
_WF_BUFFER = "workflow:{run_id}:buffer"


def _ttl() -> int:
    return get_settings().TASK_BUFFER_TTL


# ── Generic helpers ─────────────────────────────────────────────

def _set_key(key: str, value: str, ttl: int | None = None):
    r = get_redis()
    if not r:
        return
    try:
        r.set(key, value, ex=ttl or _ttl())
    except Exception as e:
        logger.warning("Redis SET failed (%s): %s", key, e)


def _get_key(key: str) -> str | None:
    r = get_redis()
    if not r:
        return None
    try:
        return r.get(key)
    except Exception:
        return None


def _push(key: str, event: dict):
    r = get_redis()
    if not r:
        return
    try:
        r.rpush(key, json.dumps(event, ensure_ascii=False))
        r.expire(key, _ttl())
    except Exception as e:
        logger.warning("Redis RPUSH failed (%s): %s", key, e)


def _read_list(key: str, start: int = 0) -> list[dict]:
    r = get_redis()
    if not r:
        return []
    try:
        raw = r.lrange(key, start, -1)
        return [json.loads(item) for item in raw]
    except Exception as e:
        logger.warning("Redis LRANGE failed (%s): %s", key, e)
        return []


def _list_len(key: str) -> int:
    r = get_redis()
    if not r:
        return 0
    try:
        return r.llen(key) or 0
    except Exception:
        return 0


# ── Chat task operations ───────────────────────────────────────

def ct_set_status(task_id: str, status: str, agent: str | None = None):
    _set_key(_CT_STATUS.format(task_id=task_id), status)
    if agent:
        _set_key(_CT_AGENT.format(task_id=task_id), agent)


def ct_push_event(task_id: str, event: dict):
    _push(_CT_BUFFER.format(task_id=task_id), event)


def ct_get_events(task_id: str, start: int = 0) -> list[dict]:
    return _read_list(_CT_BUFFER.format(task_id=task_id), start)


def ct_get_event_count(task_id: str) -> int:
    return _list_len(_CT_BUFFER.format(task_id=task_id))


def ct_get_status(task_id: str) -> dict:
    return {
        "status": _get_key(_CT_STATUS.format(task_id=task_id)),
        "agent": _get_key(_CT_AGENT.format(task_id=task_id)),
    }


# ── Workflow operations ────────────────────────────────────────

def wf_set_status(run_id: str, status: str):
    _set_key(_WF_STATUS.format(run_id=run_id), status)


def wf_push_event(run_id: str, event: dict):
    _push(_WF_BUFFER.format(run_id=run_id), event)


def wf_get_events(run_id: str, start: int = 0) -> list[dict]:
    return _read_list(_WF_BUFFER.format(run_id=run_id), start)


def wf_get_event_count(run_id: str) -> int:
    return _list_len(_WF_BUFFER.format(run_id=run_id))


def wf_get_status(run_id: str) -> str | None:
    return _get_key(_WF_STATUS.format(run_id=run_id))
