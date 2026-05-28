"""Core agent trace logic — no framework dependency."""


def get_agent_trace_impl(run_id: str, session=None) -> dict:
    from app.models.agent_trace import AgentRun, AgentRunStep

    try:
        if session:
            run = session.get(AgentRun, run_id)
        else:
            from app.core.extensions import db as _fdb
            run = _fdb.session.get(AgentRun, run_id)

        if not run:
            return {"error": "Agent run not found"}

        if session:
            steps = (
                session.query(AgentRunStep)
                .filter_by(run_id=run_id)
                .order_by(AgentRunStep.step_index)
                .all()
            )
        else:
            steps = (
                AgentRunStep.query
                .filter_by(run_id=run_id)
                .order_by(AgentRunStep.step_index)
                .all()
            )

        return {
            "run": run.to_dict(),
            "steps": [s.to_dict() for s in steps],
        }

    except Exception as e:
        return {"error": str(e), "run_id": run_id}
