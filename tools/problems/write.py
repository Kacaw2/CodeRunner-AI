"""Core question-save logic — no framework dependency."""


def save_generated_problem_impl(
    question_data: dict,
    teacher_id: int,
    session=None,
) -> dict:
    from app.models.generated_question_draft import GeneratedQuestionDraft
    from app.core.timezone import now_china

    try:
        draft = GeneratedQuestionDraft(
            teacher_id=teacher_id,
            question_data=question_data,
            status="pending_review",
            created_at=now_china(),
        )

        if session:
            session.add(draft)
            session.flush()
            draft_id = draft.id
        else:
            from app.core.extensions import db
            db.session.add(draft)
            db.session.flush()
            draft_id = draft.id

        return {
            "draft_id": draft_id,
            "status": "pending_review",
            "message": "Question saved as draft — pending teacher review.",
        }

    except Exception as e:
        return {"error": str(e)}
