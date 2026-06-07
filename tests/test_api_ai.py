"""Tests for AI API endpoints."""
import json
from unittest.mock import patch, MagicMock

import pytest
from domain.models.chat import AIConversation, AIMessage


class TestRateLimiting:
    def test_check_rate_limit_allows_first_request(self, app):
        with app.app_context():
            from app.api.v1.ai import _check_rate_limit

            mock_redis = MagicMock()
            mock_redis.incr.return_value = 1
            mock_redis.expire.return_value = True
            mock_redis.ttl.return_value = 60

            with patch("app.api.v1.ai.redis_client", mock_redis):
                info = _check_rate_limit(1, "tutor")

            assert info["allowed"] is True
            assert info["remaining"] == 19  # limit 20 - 1

    def test_check_rate_limit_blocks_over_limit(self, app):
        with app.app_context():
            from app.api.v1.ai import _check_rate_limit

            mock_redis = MagicMock()
            mock_redis.incr.return_value = 21
            mock_redis.ttl.return_value = 45

            with patch("app.api.v1.ai.redis_client", mock_redis):
                info = _check_rate_limit(1, "tutor")

            assert info["allowed"] is False
            assert info["remaining"] == 0
            assert info["retry_after"] == 45

    def test_per_agent_limits(self, app):
        with app.app_context():
            from app.api.v1.ai import _check_rate_limit

            mock_redis = MagicMock()
            mock_redis.incr.return_value = 6
            mock_redis.ttl.return_value = 30

            with patch("app.api.v1.ai.redis_client", mock_redis):
                tutor_info = _check_rate_limit(1, "tutor")
                generator_info = _check_rate_limit(1, "generator")

            assert tutor_info["allowed"] is True    # limit 20, count 6
            assert generator_info["allowed"] is False  # limit 5, count 6

    def test_rate_limit_without_redis(self, app):
        with app.app_context():
            from app.api.v1.ai import _check_rate_limit

            with patch("app.api.v1.ai.redis_client", None):
                info = _check_rate_limit(1, "tutor")

            assert info["allowed"] is True

    def test_rate_limit_headers(self, app):
        with app.app_context():
            from app.api.v1.ai import _rate_limit_headers

            headers = _rate_limit_headers({"limit": 20, "remaining": 15, "retry_after": 0})
            assert headers["X-RateLimit-Limit"] == "20"
            assert headers["X-RateLimit-Remaining"] == "15"
            assert "Retry-After" not in headers

            headers_limited = _rate_limit_headers({"limit": 5, "remaining": 0, "retry_after": 30})
            assert headers_limited["Retry-After"] == "30"


class TestAutoRoutingPerAgentLimit:
    """Phase 3: the 'auto' lane must not bypass the resolved agent's real limit."""

    def test_auto_routed_request_enforces_resolved_agent_limit(self, client, mock_auth_student):
        # The 'auto' guard (limit 20) stays under budget, but the request
        # resolves to generator (limit 5) which is already exhausted.
        def incr_side(key):
            return 6 if key.endswith(":generator") else 1

        mock_redis = MagicMock()
        mock_redis.incr.side_effect = incr_side
        mock_redis.ttl.return_value = 30

        with patch("app.api.v1.ai.redis_client", mock_redis), \
             patch("app.api.v1.ai._classify_for_routing", return_value="generator"):
            resp = client.post("/api/v1/ai/chat", json={"message": "Generate a hard problem"})

        # Under the old behaviour (limit checked on 'auto'=20) count 6 would pass.
        # Now the generator limit (5) binds → 429.
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert any(c.args[0].endswith(":generator") for c in mock_redis.incr.call_args_list)

    def test_auto_routed_headers_reflect_resolved_agent_limit(self, client, mock_auth_student, db_session):
        mock_redis = MagicMock()
        mock_redis.incr.return_value = 3  # under both limits
        mock_redis.ttl.return_value = 60

        canned = {
            "agent_type": "generator",
            "final_response": "Here is a problem.",
            "messages": [],
            "context": {},
        }

        with patch("app.api.v1.ai.redis_client", mock_redis), \
             patch("app.api.v1.ai._classify_for_routing", return_value="generator"), \
             patch("ai.graph.runner.AgentOrchestrator.run", return_value=canned):
            resp = client.post("/api/v1/ai/chat", json={"message": "Generate a problem"})

        assert resp.status_code == 200
        assert resp.get_json()["agent_type"] == "generator"
        # Header reflects the generator limit (5), not the auto guard (20).
        assert resp.headers["X-RateLimit-Limit"] == "5"

    @patch("app.services.agent_runtime_dispatcher._dispatch_remote")
    def test_chat_async_persists_resolved_agent(self, mock_submit, client, mock_auth_student, db_session):
        mock_redis = MagicMock()
        mock_redis.incr.return_value = 1
        mock_redis.ttl.return_value = 60

        with patch("app.api.v1.ai.redis_client", mock_redis), \
             patch("app.api.v1.ai._classify_for_routing", return_value="generator"):
            resp = client.post("/api/v1/ai/chat/async", json={"message": "Generate a problem"})

        assert resp.status_code == 202
        task_id = resp.get_json()["task_id"]

        from domain.models.chat import ChatTask
        task = db_session.get(ChatTask, task_id)
        assert task.agent_type == "auto"         # original lane preserved
        assert task.routed_agent == "generator"  # resolved at submission so the worker reuses it

    def test_chat_async_blocks_when_resolved_agent_over_limit(self, client, mock_auth_student):
        def incr_side(key):
            return 6 if key.endswith(":generator") else 1

        mock_redis = MagicMock()
        mock_redis.incr.side_effect = incr_side
        mock_redis.ttl.return_value = 30

        with patch("app.api.v1.ai.redis_client", mock_redis), \
             patch("app.api.v1.ai._classify_for_routing", return_value="generator"):
            resp = client.post("/api/v1/ai/chat/async", json={"message": "Generate a problem"})

        assert resp.status_code == 429
        assert "Retry-After" in resp.headers


class TestChatEndpoint:
    @patch("ai.agents.runtime.AIConfig")
    def test_chat_requires_message(self, mock_config, client, mock_auth_student, mock_redis):
        resp = client.post("/api/v1/ai/chat", json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "invalid_request"

    @patch("ai.agents.runtime.AIConfig")
    def test_chat_returns_response(self, mock_config, client, mock_auth_student, mock_redis, db_session):
        from langchain_core.messages import AIMessage as LCAIMessage

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        ai_msg = LCAIMessage(content="Here is a hint.")
        mock_llm.invoke.return_value = ai_msg
        mock_config.get_llm.return_value = mock_llm
        mock_config.validate.return_value = None

        resp = client.post("/api/v1/ai/chat", json={
            "message": "Help me with my code",
            "agent_type": "tutor",
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert "conversation_id" in data
        assert data["response"] == "Here is a hint."
        assert "X-RateLimit-Limit" in resp.headers

    def test_chat_rate_limited(self, client, mock_auth_student):
        mock_redis = MagicMock()
        mock_redis.incr.return_value = 100
        mock_redis.ttl.return_value = 45

        with patch("app.api.v1.ai.redis_client", mock_redis):
            resp = client.post("/api/v1/ai/chat", json={
                "message": "help",
                "agent_type": "tutor",
            })

        assert resp.status_code == 429
        assert "Retry-After" in resp.headers


class TestConversationsEndpoint:
    def test_list_conversations(self, client, mock_auth_student, db_session, student_user):
        conv = AIConversation(user_id=student_user.id, agent_type="tutor", title="Test conv")
        db_session.add(conv)
        db_session.flush()

        resp = client.get("/api/v1/ai/conversations")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] >= 1

    def test_list_conversations_filter_by_type(self, client, mock_auth_student, db_session, student_user):
        conv1 = AIConversation(user_id=student_user.id, agent_type="tutor", title="Tutor")
        conv2 = AIConversation(user_id=student_user.id, agent_type="reviewer", title="Review")
        db_session.add_all([conv1, conv2])
        db_session.flush()

        resp = client.get("/api/v1/ai/conversations?agent_type=tutor")
        data = resp.get_json()
        assert all(c["agent_type"] == "tutor" for c in data["items"])

    def test_get_conversation_not_found(self, client, mock_auth_student):
        resp = client.get("/api/v1/ai/conversations/99999")
        assert resp.status_code == 404

    def test_get_conversation_with_messages(self, client, mock_auth_student, db_session, student_user):
        conv = AIConversation(user_id=student_user.id, agent_type="tutor", title="Test")
        db_session.add(conv)
        db_session.flush()

        msg = AIMessage(conversation_id=conv.id, role="user", content="Hello")
        db_session.add(msg)
        db_session.flush()

        resp = client.get(f"/api/v1/ai/conversations/{conv.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["messages"]) == 1

    def test_delete_conversation(self, client, mock_auth_student, db_session, student_user):
        conv = AIConversation(user_id=student_user.id, agent_type="tutor", title="Delete me")
        db_session.add(conv)
        db_session.flush()
        conv_id = conv.id

        resp = client.delete(f"/api/v1/ai/conversations/{conv_id}")
        assert resp.status_code == 204

    def test_delete_conversation_not_found(self, client, mock_auth_student):
        resp = client.delete("/api/v1/ai/conversations/99999")
        assert resp.status_code == 404


class TestReviewEndpoint:
    def test_review_requires_code(self, client, mock_auth_student, mock_redis):
        resp = client.post("/api/v1/ai/review", json={})
        assert resp.status_code == 400

    @patch("ai.agents.runtime.AIConfig")
    def test_review_returns_structured_result(self, mock_config, client, mock_auth_student, mock_redis, db_session):
        review = '```json\n{"overall_score": "A", "summary": "Great", "issues": [], "strengths": ["Clean"]}\n```'
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_resp = MagicMock()
        mock_resp.content = review
        mock_resp.tool_calls = []
        mock_llm.invoke.return_value = mock_resp
        mock_config.get_llm.return_value = mock_llm
        mock_config.validate.return_value = None

        resp = client.post("/api/v1/ai/review", json={
            "code": "int main(){return 0;}",
            "language": "c",
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert "conversation_id" in data
        assert isinstance(data["review"], dict)
        assert data["review"]["overall_score"] == "A"


class TestGenerateEndpoint:
    def test_generate_requires_teacher(self, client, mock_auth_student, mock_redis):
        resp = client.post("/api/v1/ai/generate", json={"prompt": "Create a problem"})
        assert resp.status_code == 403

    def test_generate_requires_prompt(self, client, mock_auth_teacher, mock_redis):
        resp = client.post("/api/v1/ai/generate", json={})
        assert resp.status_code == 400

    @patch("ai.agents.generator.agent._validate_solution")
    @patch("ai.agents.config.AIConfig.validate")
    @patch("ai.agents.config.AIConfig.get_llm")
    def test_generate_returns_question(self, mock_get_llm, mock_validate, mock_val,
                                       client, mock_auth_teacher, mock_redis, db_session):
        q_json = '''```json
{
  "title": "Sum", "description": "Add two numbers",
  "programming_language": "python", "solution": "print(int(input())+int(input()))",
  "test_cases": [{"input": "1\\n2", "expected_output": "3", "is_hidden": false, "weight": 1.0}]
}
```'''
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_resp = MagicMock()
        mock_resp.content = q_json
        mock_resp.tool_calls = []
        mock_llm.invoke.return_value = mock_resp
        mock_get_llm.return_value = mock_llm

        mock_val.return_value = [
            {"index": 0, "passed": True, "input": "1\n2", "expected": "3",
             "actual": "3", "error": "", "status": "AC"},
        ]

        resp = client.post("/api/v1/ai/generate", json={
            "prompt": "Create a simple addition problem",
            "language": "python",
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["question"] is not None
        assert data["question"]["title"] == "Sum"


class TestAnalyticsEndpoint:
    def test_analytics_student_can_only_view_own(self, client, mock_auth_student, mock_redis, student_user):
        other_id = student_user.id + 100
        resp = client.get(f"/api/v1/ai/analytics/{other_id}")
        assert resp.status_code == 403

    @patch("ai.agents.runtime.AIConfig")
    def test_analytics_returns_report(self, mock_config, client, mock_auth_teacher, mock_redis, db_session):
        report = '```json\n{"summary": "Good", "progress": {"trend": "improving"}}\n```'
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_resp = MagicMock()
        mock_resp.content = report
        mock_resp.tool_calls = []
        mock_llm.invoke.return_value = mock_resp
        mock_config.get_llm.return_value = mock_llm
        mock_config.validate.return_value = None

        resp = client.get("/api/v1/ai/analytics/1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "report" in data


class TestAsyncChatEndpoint:
    """Tests for the async chat task flow."""

    def test_chat_async_requires_message(self, client, mock_auth_student, mock_redis):
        resp = client.post("/api/v1/ai/chat/async", json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "invalid_request"

    def test_chat_async_validates_message_before_worker(self, client, mock_auth_student, mock_redis):
        with patch("app.services.agent_runtime_dispatcher._dispatch_remote") as submit_chat_task:
            resp = client.post("/api/v1/ai/chat/async", json={})

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "invalid_request"
        submit_chat_task.assert_not_called()

    @patch("app.services.agent_runtime_dispatcher._dispatch_remote")
    def test_chat_async_creates_task(self, mock_submit, client, mock_auth_student, mock_redis, db_session):
        resp = client.post("/api/v1/ai/chat/async", json={
            "message": "Help me with arrays",
            "agent_type": "auto",
        })

        assert resp.status_code == 202
        data = resp.get_json()
        assert "task_id" in data
        assert "conversation_id" in data
        mock_submit.assert_called_once()

    @patch("app.services.agent_runtime_dispatcher._dispatch_remote")
    def test_chat_async_ignores_manual_agent_type(self, mock_submit, client, mock_auth_student, mock_redis, db_session):
        resp = client.post("/api/v1/ai/chat/async", json={
            "message": "Generate a problem",
            "agent_type": "generator",
        })

        assert resp.status_code == 202
        task_id = resp.get_json()["task_id"]

        from domain.models.chat import ChatTask
        task = db_session.get(ChatTask, task_id)
        assert task.agent_type == "auto"

    def test_chat_agent_type_normalization_for_all_chat_entrypoints(self, app):
        with app.app_context():
            from app.api.v1.ai import _normalize_chat_agent_type

            assert _normalize_chat_agent_type({"agent_type": "generator"}) == "auto"
            assert _normalize_chat_agent_type({"agent_type": "reviewer"}) == "auto"
            assert _normalize_chat_agent_type({}) == "auto"

    def test_chat_task_status_not_found(self, client, mock_auth_student):
        resp = client.get("/api/v1/ai/chat/task/nonexistent-uuid")
        assert resp.status_code == 404

    @patch("app.services.agent_runtime_dispatcher._dispatch_remote")
    def test_chat_task_poll(self, mock_submit, client, mock_auth_student, mock_redis, db_session):
        resp = client.post("/api/v1/ai/chat/async", json={
            "message": "Test polling",
            "agent_type": "auto",
        })
        assert resp.status_code == 202
        task_id = resp.get_json()["task_id"]

        poll_resp = client.get(f"/api/v1/ai/chat/task/{task_id}")
        assert poll_resp.status_code == 200
        task_data = poll_resp.get_json()["task"]
        assert task_data["status"] == "pending"

    def test_frontend_resume_reads_nested_task_status(self):
        from pathlib import Path

        js = Path("app/static/js/ai_chat.js").read_text(encoding="utf-8")
        assert "const taskInfo = info.task || info;" in js
        assert 'taskInfo.status === "completed"' in js

    def test_chat_async_rate_limited(self, client, mock_auth_student):
        mock_redis = MagicMock()
        mock_redis.incr.return_value = 100
        mock_redis.ttl.return_value = 45

        with patch("app.api.v1.ai.redis_client", mock_redis):
            resp = client.post("/api/v1/ai/chat/async", json={
                "message": "help",
                "agent_type": "auto",
            })

        assert resp.status_code == 429
        assert "Retry-After" in resp.headers


class TestChatTaskModel:
    """Tests for the ChatTask model."""

    def test_chat_task_creation(self, app, db_session, student_user):
        from domain.models.chat import ChatTask
        from domain.models.chat import AIConversation

        conv = AIConversation(user_id=student_user.id, agent_type="tutor")
        db_session.add(conv)
        db_session.flush()

        task = ChatTask(
            conversation_id=conv.id,
            user_id=student_user.id,
            agent_type="auto",
            status="pending",
        )
        db_session.add(task)
        db_session.flush()

        assert task.id is not None
        assert len(task.id) == 36  # UUID
        assert task.status == "pending"
        assert task.conversation_id == conv.id

    def test_chat_task_to_dict(self, app, db_session, student_user):
        from domain.models.chat import ChatTask
        from domain.models.chat import AIConversation

        conv = AIConversation(user_id=student_user.id, agent_type="tutor")
        db_session.add(conv)
        db_session.flush()

        task = ChatTask(
            conversation_id=conv.id,
            user_id=student_user.id,
            agent_type="auto",
        )
        db_session.add(task)
        db_session.flush()

        d = task.to_dict()
        assert d["status"] == "pending"
        assert d["agent_type"] == "auto"
        assert d["id"] == task.id


class TestChatRedisBuffer:
    """Tests for the shared chat Redis buffer operations."""

    def test_push_and_get_events(self, app):
        with app.app_context():
            from ai.workers.redis_buffer import ct_get_events, ct_push_event

            mock_redis = MagicMock()
            stored = []

            def mock_rpush(key, val):
                stored.append(val)

            def mock_lrange(key, start, end):
                return stored[start:]

            mock_redis.rpush.side_effect = mock_rpush
            mock_redis.lrange.side_effect = mock_lrange
            mock_redis.expire.return_value = True

            with patch("ai.workers.redis_buffer.get_redis", return_value=mock_redis):
                ct_push_event(
                    "test-task", {"type": "start", "agent_type": "tutor"}
                )
                ct_push_event(
                    "test-task", {"type": "token", "content": "Hello"}
                )

                events = ct_get_events("test-task", start=0)
                assert len(events) == 2
                assert events[0]["type"] == "start"
                assert events[1]["content"] == "Hello"

    def test_get_events_with_offset(self, app):
        with app.app_context():
            from ai.workers.redis_buffer import ct_get_events, ct_push_event

            mock_redis = MagicMock()
            stored = []

            def mock_rpush(key, val):
                stored.append(val)

            def mock_lrange(key, start, end):
                return stored[start:]

            mock_redis.rpush.side_effect = mock_rpush
            mock_redis.lrange.side_effect = mock_lrange
            mock_redis.expire.return_value = True

            with patch("ai.workers.redis_buffer.get_redis", return_value=mock_redis):
                ct_push_event("test-task", {"type": "start"})
                ct_push_event(
                    "test-task", {"type": "token", "content": "A"}
                )
                ct_push_event(
                    "test-task", {"type": "token", "content": "B"}
                )

                events = ct_get_events("test-task", start=1)
                assert len(events) == 2
                assert events[0]["content"] == "A"

    def test_get_status_from_redis(self, app):
        with app.app_context():
            from ai.workers.redis_buffer import ct_get_status, ct_set_status

            mock_redis = MagicMock()
            store = {}

            def mock_set(key, val, ex=None):
                store[key] = val

            def mock_get(key):
                return store.get(key)

            mock_redis.set.side_effect = mock_set
            mock_redis.get.side_effect = mock_get

            with patch("ai.workers.redis_buffer.get_redis", return_value=mock_redis):
                ct_set_status("test-task", "processing", "tutor")
                info = ct_get_status("test-task")
                assert info["status"] == "processing"
                assert info["agent"] == "tutor"

    def test_no_redis_returns_empty(self, app):
        with app.app_context():
            from ai.workers.redis_buffer import ct_get_events, ct_get_status

            with patch("ai.workers.redis_buffer.get_redis", return_value=None):
                assert ct_get_events("x") == []
                assert ct_get_status("x") == {
                    "status": None,
                    "agent": None,
                }


class TestHelpers:
    def test_build_context(self, app):
        with app.app_context():
            from app.api.v1.ai import _build_context

            data = {
                "question_id": 1,
                "code": "print(1)",
                "language": "python",
                "extra_field": "ignored",
            }
            ctx = _build_context(data)
            assert ctx["question_id"] == 1
            assert ctx["code"] == "print(1)"
            assert "extra_field" not in ctx

    def test_try_parse_review_json_valid(self, app):
        with app.app_context():
            from app.api.v1.ai import _try_parse_review_json

            text = 'Some text\n```json\n{"score": "A"}\n```\nMore text'
            result = _try_parse_review_json(text)
            assert result == {"score": "A"}

    def test_try_parse_review_json_invalid(self, app):
        with app.app_context():
            from app.api.v1.ai import _try_parse_review_json

            assert _try_parse_review_json("no json here") is None
            assert _try_parse_review_json("```json\nnot json\n```") is None

    def test_try_parse_review_json_bare(self, app):
        with app.app_context():
            from app.api.v1.ai import _try_parse_review_json

            result = _try_parse_review_json('{"key": "value"}')
            assert result == {"key": "value"}
