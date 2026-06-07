"""Workflow domain, repository, and remote-runner contracts."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from domain.models.user import User, UserRole


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_workflow_mappings_use_the_shared_domain_metadata():
    from domain.base import DomainBase
    from domain.models.workflow import WorkflowApproval, WorkflowRun, WorkflowStep

    assert WorkflowRun.metadata is DomainBase.metadata
    assert WorkflowStep.metadata is DomainBase.metadata
    assert WorkflowApproval.metadata is DomainBase.metadata


def test_sync_repository_uses_compare_and_set_for_run_and_step(db_session):
    from domain.repositories.workflows import SyncWorkflowRepository

    user = User(
        username="workflow-user",
        password="hashed",
        email="workflow@test.com",
        role=UserRole.TEACHER,
    )
    db_session.add(user)
    db_session.flush()

    repo = SyncWorkflowRepository(db_session)
    run = repo.create_run(
        user_id=user.id,
        goal="Generate and review a problem",
        workflow_type="general",
        status="planning",
    )
    db_session.flush()
    step = repo.create_step(
        workflow_run_id=run.id,
        step_index=0,
        step_type="agent_call",
        instruction="Draft the problem",
        status="pending",
    )
    db_session.flush()

    assert repo.transition_run(run.id, "planning", "executing") is True
    assert repo.transition_run(run.id, "planning", "executing") is False
    assert repo.transition_step(step.id, "pending", "running") is True
    assert repo.transition_step(step.id, "pending", "running") is False

    approval = repo.add_approval(
        workflow_run_id=run.id,
        step_index=0,
        approver_user_id=user.id,
        decision="approved",
        feedback="looks good",
    )
    db_session.flush()

    db_session.refresh(run)
    db_session.refresh(step)
    assert run.status == "executing"
    assert step.status == "running"
    assert approval.decision == "approved"
    assert repo.list_steps(run.id) == [step]


def test_async_repository_claims_a_run_only_once():
    from domain.base import DomainBase
    from domain.models.workflow import WorkflowRun
    from domain.repositories.workflows import AsyncWorkflowRepository

    import domain.models.chat  # noqa: F401
    import domain.models.user  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def scenario():
        async with engine.begin() as conn:
            await conn.run_sync(DomainBase.metadata.create_all)

        factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with factory() as session:
            user = User(
                username="async-workflow-user",
                password="hashed",
                email="async-workflow@test.com",
                role=UserRole.TEACHER,
            )
            session.add(user)
            await session.flush()
            run = WorkflowRun(
                id="async-workflow",
                user_id=user.id,
                goal="Async workflow",
                workflow_type="general",
                status="planning",
            )
            session.add(run)
            await session.commit()

        async with factory() as first:
            repo = AsyncWorkflowRepository(first)
            assert await repo.transition_run(
                "async-workflow", "planning", "executing"
            ) is True
            await first.commit()

        async with factory() as second:
            repo = AsyncWorkflowRepository(second)
            assert await repo.transition_run(
                "async-workflow", "planning", "executing"
            ) is False

        await engine.dispose()

    _run(scenario())


def test_remote_runner_claims_and_executes_with_the_existing_engine(monkeypatch):
    from domain.base import DomainBase
    from domain.models.workflow import WorkflowRun
    from domain.repositories.workflows import AsyncWorkflowRepository
    from agent_runtime.services.workflow_runner import AsyncWorkflowRunner

    import domain.models.chat  # noqa: F401
    import domain.models.user  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def scenario():
        async with engine.begin() as conn:
            await conn.run_sync(DomainBase.metadata.create_all)

        factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with factory() as session:
            user = User(
                username="remote-workflow-user",
                password="hashed",
                email="remote-workflow@test.com",
                role=UserRole.TEACHER,
            )
            session.add(user)
            await session.flush()
            run = WorkflowRun(
                id="remote-workflow",
                user_id=user.id,
                goal="Remote workflow",
                workflow_type="general",
                status="planning",
                plan_json={"goal": "Remote workflow", "steps": []},
            )
            session.add(run)
            await session.commit()

        monkeypatch.setattr(
            AsyncWorkflowRunner,
            "_execute_sync",
            staticmethod(
                lambda run_id, user_role: (
                    {
                        "workflow_run_id": run_id,
                        "status": "completed",
                        "final_result": {"ok": True},
                    },
                    [{"type": "workflow_completed", "run_id": run_id}],
                )
            ),
        )

        async with factory() as session:
            result = await AsyncWorkflowRunner(session).run("remote-workflow")
            assert result["claimed"] is True
            assert result["status"] == "completed"

        async with factory() as session:
            repo = AsyncWorkflowRepository(session)
            saved = await repo.get_run("remote-workflow")
            assert saved.status == "completed"
            assert saved.result == {"ok": True}

        async with factory() as session:
            result = await AsyncWorkflowRunner(session).run("remote-workflow")
            assert result["claimed"] is False

        await engine.dispose()

    _run(scenario())
