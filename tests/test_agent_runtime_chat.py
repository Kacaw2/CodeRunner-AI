"""Async chat runner: persisted outcome + Redis/SSE parity with the worker.

Uses an in-memory sqlite+aiosqlite database built from DomainBase.metadata and a
fake Redis (a plain object recording the key/buffer writes), with the agent
kernel stubbed so no real LLM call happens.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# app.models registers the Flask db.Model classes (Classroom, Enrollment, ...)
# that domain.models.user's string-based relationships resolve against, so the
# DomainBase mappers configure even when this module runs in isolation.
import app.models  # noqa: F401
import domain.models.chat  # noqa: F401
import domain.models.user  # noqa: F401
from ai.agent_runtime.services.chat_runner import AsyncChatRunner
from domain.base import DomainBase
from domain.models.user import User, UserRole
from domain.repositories.chat import AsyncChatRepository


class FakeRedis:
    """Minimal Redis stand-in mirroring the keys/format workers/chat.py uses."""

    def __init__(self):
        self.kv = {}
        self.lists = {}

    def set(self, key, value, ex=None):
        self.kv[key] = value

    def get(self, key):
        return self.kv.get(key)

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def expire(self, key, ttl):
        pass

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        if end == -1:
            return items[start:]
        return items[start:end + 1]


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture()
def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(DomainBase.metadata.create_all)

    _run(_setup())
    return async_sessionmaker(bind=engine, expire_on_commit=False)


def _seed_task(session_factory, *, agent_type="tutor", routed_agent="tutor"):
    """Create user, conversation, user message, and a pending task."""

    async def _seed():
        async with session_factory() as session:
            user = User(username="u", password="p", email="u@t.com",
                        role=UserRole.STUDENT)
            session.add(user)
            await session.flush()

            repo = AsyncChatRepository(session)
            conv = repo.create_conversation(user_id=user.id, agent_type=agent_type)
            await session.flush()
            user_msg = repo.add_message(conv.id, role="user", content="hello there")
            await session.flush()
            task = repo.create_task(
                conversation_id=conv.id,
                user_id=user.id,
                user_message_id=user_msg.id,
                agent_type=agent_type,
                routed_agent=routed_agent,
                status="pending",
            )
            await session.flush()
            await session.commit()
            return task.id, conv.id

    return _run(_seed())


def _stub_agent_stream(monkeypatch, tokens=("Hi", " there")):
    """Patch the agent registry so .stream yields fixed tokens, no LLM call."""

    # Initialize graph.runner's process-wide agent cache before patching the
    # registry factory used only by the remote runner. Otherwise this stub can
    # leak into later tests that exercise the synchronous orchestrator.
    import ai.graph.runner  # noqa: F401

    class _StubAgent:
        def stream(self, state):
            for tok in tokens:
                yield {"type": "token", "content": tok}
            state["final_response"] = "".join(tokens)

    import ai.agent_runtime.services.chat_runner as runner_mod

    # _run_agent_stream imports get_agent_instance from ai.agents.registry locally.
    monkeypatch.setattr(
        "ai.agents.registry.get_agent_instance", lambda *a, **k: _StubAgent()
    )
    monkeypatch.setattr(runner_mod, "filter_output", None, raising=False)


def test_runner_completes_task_and_persists_outcome(session_factory, monkeypatch):
    task_id, conv_id = _seed_task(session_factory)
    _stub_agent_stream(monkeypatch)
    # filter_output is imported locally inside run(); patch it there.
    monkeypatch.setattr("core.security.filter_output",
                        lambda text, agent, role: text)

    redis = FakeRedis()

    async def _go():
        async with session_factory() as session:
            runner = AsyncChatRunner(session, redis_client=redis)
            return await runner.run(task_id)

    result = _run(_go())

    assert result["claimed"] is True
    assert result["status"] == "completed"
    assert result["result_message_id"] is not None

    # Persisted: task completed, assistant message saved, conversation titled.
    async def _check():
        async with session_factory() as session:
            repo = AsyncChatRepository(session)
            task = await repo.get_task(task_id)
            msg = await repo.get_message(task.result_message_id)
            conv = await repo.get_conversation(conv_id)
            return task.status, msg.role, msg.content, conv.title

    status, role, content, title = _run(_check())
    assert status == "completed"
    assert role == "assistant"
    assert content == "Hi there"
    assert title == "hello there"


def test_runner_writes_sse_contract_to_redis(session_factory, monkeypatch):
    task_id, conv_id = _seed_task(session_factory)
    _stub_agent_stream(monkeypatch)
    monkeypatch.setattr("core.security.filter_output",
                        lambda text, agent, role: text)

    redis = FakeRedis()

    async def _go():
        async with session_factory() as session:
            await AsyncChatRunner(session, redis_client=redis).run(task_id)

    _run(_go())

    # Status key written with the same layout as the embedded worker.
    assert redis.kv[f"chat_task:{task_id}:status"] == "completed"
    assert redis.kv[f"chat_task:{task_id}:agent"] == "tutor"

    buffer = [json.loads(e) for e in redis.lists[f"chat_task:{task_id}:buffer"]]
    types = [e["type"] for e in buffer]
    assert types[0] == "start"
    assert "token" in types
    assert types[-1] == "done"
    assert buffer[-1]["message_id"] == buffer[-1]["message_id"]  # done has message_id
    assert "message_id" in buffer[-1]


def test_runner_does_not_double_execute_claimed_task(session_factory, monkeypatch):
    task_id, _ = _seed_task(session_factory)
    _stub_agent_stream(monkeypatch)
    monkeypatch.setattr("core.security.filter_output",
                        lambda text, agent, role: text)

    redis = FakeRedis()

    async def _first():
        async with session_factory() as session:
            return await AsyncChatRunner(session, redis_client=redis).run(task_id)

    async def _second():
        async with session_factory() as session:
            return await AsyncChatRunner(session, redis_client=redis).run(task_id)

    first = _run(_first())
    second = _run(_second())

    assert first["claimed"] is True
    # Task already completed -> CAS pending->processing fails, no re-run.
    assert second["claimed"] is False


def test_runner_marks_failed_on_agent_error(session_factory, monkeypatch):
    task_id, _ = _seed_task(session_factory)

    class _BoomAgent:
        def stream(self, state):
            raise RuntimeError("kernel boom")
            yield  # pragma: no cover

    monkeypatch.setattr(
        "ai.agents.registry.get_agent_instance", lambda *a, **k: _BoomAgent()
    )
    monkeypatch.setattr("core.security.filter_output",
                        lambda text, agent, role: text)

    redis = FakeRedis()

    async def _go():
        async with session_factory() as session:
            return await AsyncChatRunner(session, redis_client=redis).run(task_id)

    result = _run(_go())
    assert result["status"] == "failed"

    async def _check():
        async with session_factory() as session:
            return (await AsyncChatRepository(session).get_task(task_id)).status

    assert _run(_check()) == "failed"
    # Error event surfaced on the SSE buffer.
    buffer = [json.loads(e) for e in redis.lists[f"chat_task:{task_id}:buffer"]]
    assert buffer[-1]["type"] == "error"
