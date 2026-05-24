def test_agent_trace_defaults_use_china_local_time(app, db_session, teacher_user):
    with app.app_context():
        from app.core.timezone import now_china
        from app.models.agent_trace import AgentRun

        before = now_china()
        run = AgentRun(
            id="china-time-test",
            user_id=teacher_user.id,
            agent_type="tutor",
            status="completed",
        )
        db_session.add(run)
        db_session.commit()
        after = now_china()

        assert before <= run.created_at <= after
