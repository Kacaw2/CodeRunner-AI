"""Tests for the chat domain repository (sync path).

These exercise the repository surface used by the Flask request path and the
embedded worker: conversation create/read, message append, ordered history,
task create, and the compare-and-set task state transitions. The repository
never commits — the test owns the transaction (``db_session``).
"""
import pytest

from domain.models.user import User, UserRole
from domain.models.chat import AIConversation, AIMessage, ChatTask
from domain.repositories.chat import SyncChatRepository


@pytest.fixture()
def chat_user(db_session):
    user = User(username="chatuser", password="hashed",
                email="chat@test.com", role=UserRole.STUDENT)
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def repo(db_session):
    return SyncChatRepository(db_session)


class TestConversation:
    def test_create_and_get_conversation(self, repo, db_session, chat_user):
        conv = repo.create_conversation(
            user_id=chat_user.id, agent_type="tutor", context_type="question",
            context_id=42,
        )
        db_session.flush()

        assert conv.id is not None
        fetched = repo.get_conversation(conv.id)
        assert fetched is not None
        assert fetched.id == conv.id
        assert fetched.agent_type == "tutor"
        assert fetched.context_type == "question"
        assert fetched.context_id == 42

    def test_get_conversation_for_user_scopes_by_owner(self, repo, db_session, chat_user):
        conv = repo.create_conversation(user_id=chat_user.id, agent_type="tutor")
        db_session.flush()

        assert repo.get_conversation_for_user(conv.id, chat_user.id) is not None
        # Different owner -> not found
        assert repo.get_conversation_for_user(conv.id, chat_user.id + 999) is None

    def test_repository_does_not_commit(self, repo, db_session, chat_user):
        conv = repo.create_conversation(user_id=chat_user.id, agent_type="tutor")
        db_session.flush()
        conv_id = conv.id
        db_session.rollback()
        # After rollback the staged-but-uncommitted conversation is gone.
        assert repo.get_conversation(conv_id) is None


class TestMessages:
    def test_append_message_and_count(self, repo, db_session, chat_user):
        conv = repo.create_conversation(user_id=chat_user.id, agent_type="tutor")
        db_session.flush()

        repo.add_message(conv.id, role="user", content="hi")
        repo.add_message(conv.id, role="assistant", content="hello")
        db_session.flush()

        assert repo.count_messages(conv.id) == 2

    def test_ordered_history_by_message_id(self, repo, db_session, chat_user):
        conv = repo.create_conversation(user_id=chat_user.id, agent_type="tutor")
        db_session.flush()

        m1 = repo.add_message(conv.id, role="user", content="first")
        db_session.flush()
        m2 = repo.add_message(conv.id, role="assistant", content="second")
        db_session.flush()
        m3 = repo.add_message(conv.id, role="user", content="third")
        db_session.flush()

        rows = repo.get_messages_ordered(conv.id)
        assert [r.id for r in rows] == [m1.id, m2.id, m3.id]
        assert [r.content for r in rows] == ["first", "second", "third"]


class TestTaskLifecycle:
    def _make_conv(self, repo, db_session, chat_user):
        conv = repo.create_conversation(user_id=chat_user.id, agent_type="auto")
        db_session.flush()
        return conv

    def test_create_task_defaults_pending(self, repo, db_session, chat_user):
        conv = self._make_conv(repo, db_session, chat_user)
        task = repo.create_task(
            conversation_id=conv.id, user_id=chat_user.id,
            agent_type="auto", routed_agent="generator",
        )
        db_session.flush()

        assert task.id is not None
        assert len(task.id) == 36
        assert task.status == "pending"
        assert task.agent_type == "auto"
        assert task.routed_agent == "generator"

        fetched = repo.get_task(task.id)
        assert fetched is not None
        assert fetched.id == task.id

    def test_get_task_for_user_scopes_by_owner(self, repo, db_session, chat_user):
        conv = self._make_conv(repo, db_session, chat_user)
        task = repo.create_task(conversation_id=conv.id, user_id=chat_user.id)
        db_session.flush()

        assert repo.get_task_for_user(task.id, chat_user.id) is not None
        assert repo.get_task_for_user(task.id, chat_user.id + 999) is None

    def test_compare_and_set_pending_to_processing(self, repo, db_session, chat_user):
        conv = self._make_conv(repo, db_session, chat_user)
        task = repo.create_task(conversation_id=conv.id, user_id=chat_user.id)
        db_session.flush()

        ok = repo.mark_processing(task.id, expected_status="pending")
        db_session.flush()
        assert ok is True

        db_session.refresh(task)
        assert task.status == "processing"
        assert task.started_at is not None

    def test_compare_and_set_fails_on_wrong_expected_state(self, repo, db_session, chat_user):
        conv = self._make_conv(repo, db_session, chat_user)
        task = repo.create_task(conversation_id=conv.id, user_id=chat_user.id)
        db_session.flush()

        # First worker wins the pending -> processing transition.
        assert repo.mark_processing(task.id, expected_status="pending") is True
        db_session.flush()

        # Second worker tries the same guarded transition; row is no longer
        # "pending", so the compare-and-set must report it did NOT transition.
        assert repo.mark_processing(task.id, expected_status="pending") is False
        db_session.flush()

        db_session.refresh(task)
        assert task.status == "processing"  # unchanged by the losing worker

    def test_mark_completed_sets_result_and_timestamp(self, repo, db_session, chat_user):
        conv = self._make_conv(repo, db_session, chat_user)
        task = repo.create_task(conversation_id=conv.id, user_id=chat_user.id)
        db_session.flush()
        repo.mark_processing(task.id, expected_status="pending")
        db_session.flush()

        result_msg = repo.add_message(conv.id, role="assistant", content="done")
        db_session.flush()

        ok = repo.mark_completed(
            task.id, expected_status="processing",
            result_message_id=result_msg.id,
        )
        db_session.flush()
        assert ok is True

        db_session.refresh(task)
        assert task.status == "completed"
        assert task.result_message_id == result_msg.id
        assert task.completed_at is not None

    def test_mark_failed_records_error(self, repo, db_session, chat_user):
        conv = self._make_conv(repo, db_session, chat_user)
        task = repo.create_task(conversation_id=conv.id, user_id=chat_user.id)
        db_session.flush()
        repo.mark_processing(task.id, expected_status="pending")
        db_session.flush()

        ok = repo.mark_failed(task.id, error_detail="boom")
        db_session.flush()
        assert ok is True

        db_session.refresh(task)
        assert task.status == "failed"
        assert task.error_detail == "boom"
        assert task.completed_at is not None

    def test_mark_completed_fails_if_not_processing(self, repo, db_session, chat_user):
        conv = self._make_conv(repo, db_session, chat_user)
        task = repo.create_task(conversation_id=conv.id, user_id=chat_user.id)
        db_session.flush()
        # Still pending; completing with expected "processing" must fail.
        ok = repo.mark_completed(
            task.id, expected_status="processing", result_message_id=None,
        )
        db_session.flush()
        assert ok is False

        db_session.refresh(task)
        assert task.status == "pending"


def test_recent_summaries_filter_agent_types_and_exclude_current(
    repo, db_session, chat_user
):
    from domain.models.chat import AIConversation

    tutor = AIConversation(
        user_id=chat_user.id,
        agent_type="tutor",
        summary="Tutor memory",
    )
    generator = AIConversation(
        user_id=chat_user.id,
        agent_type="generator",
        summary="Generator memory",
    )
    current = AIConversation(
        user_id=chat_user.id,
        agent_type="tutor",
        summary="Current tutor memory",
    )
    db_session.add_all([tutor, generator, current])
    db_session.commit()

    rows = repo.get_recent_summarized_conversations(
        chat_user.id,
        exclude_conversation_id=current.id,
        agent_types=("tutor",),
        limit=3,
    )

    assert [row.id for row in rows] == [tutor.id]
