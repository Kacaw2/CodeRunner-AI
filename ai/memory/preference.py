"""
Teacher preference learning (Phase 4, Task 17).

Automatically infers and updates teacher preferences based on their generation
history. Tracks patterns in topic choice, difficulty, language, and style over
time so the Generator agent can produce better-aligned questions.
"""

import logging
from collections import Counter
from app.core.timezone import now_china

logger = logging.getLogger(__name__)


def learn_from_generation(teacher_id: int, request_params: dict, generated_question: dict):
    """Update teacher preferences based on a successful generation.

    Called after the generation pipeline or single generate endpoint produces
    a verified question. Accumulates topic/difficulty/language patterns and
    optionally triggers an LLM-based style summary refresh.
    """
    from app.core.extensions import db
    from app.models.student_profile import TeacherPreference

    try:
        pref = TeacherPreference.query.filter_by(teacher_id=teacher_id).first()
        if not pref:
            pref = TeacherPreference(teacher_id=teacher_id)
            db.session.add(pref)

        language = (
            generated_question.get("programming_language")
            or request_params.get("language")
            or "python"
        )
        difficulty = (
            generated_question.get("difficulty")
            or request_params.get("difficulty")
            or "medium"
        )
        topic = request_params.get("topic", "")

        pref.preferred_language = language
        pref.preferred_difficulty = difficulty

        if topic:
            current_topics = pref.preferred_topics or []
            if topic not in current_topics:
                current_topics.append(topic)
            if len(current_topics) > 20:
                current_topics = current_topics[-20:]
            pref.preferred_topics = current_topics

        pref.updated_at = now_china()
        db.session.commit()

    except Exception as e:
        logger.warning("Failed to learn teacher preferences: %s", e)
        try:
            db.session.rollback()
        except Exception:
            pass


def refresh_teacher_style_summary(teacher_id: int):
    """Use LLM to generate a style summary from the teacher's generation history.

    Looks at the last N generated drafts to infer patterns in the teacher's
    preferred question style (description length, example format, constraints
    style, etc.) and writes a natural-language summary to style_notes.
    """
    from app.core.extensions import db
    from app.models.student_profile import TeacherPreference
    from app.models.generated_question_draft import GeneratedQuestionDraft

    try:
        drafts = (
            GeneratedQuestionDraft.query
            .filter_by(teacher_id=teacher_id)
            .filter(GeneratedQuestionDraft.status.in_(["published", "approved", "pending_review"]))
            .order_by(GeneratedQuestionDraft.created_at.desc())
            .limit(10)
            .all()
        )

        if len(drafts) < 3:
            return

        samples = []
        for d in drafts[:5]:
            qd = d.question_data or {}
            samples.append({
                "title": qd.get("title", ""),
                "difficulty": qd.get("difficulty", ""),
                "language": qd.get("programming_language", ""),
                "description_length": len(qd.get("description", "")),
                "test_case_count": len(qd.get("test_cases", [])),
                "has_starter_code": bool(qd.get("starter_code")),
                "has_explanation": bool(qd.get("solution_explanation")),
            })

        from ai.agents.config import AIConfig
        from langchain_core.messages import HumanMessage
        import json

        llm = AIConfig.get_llm()
        prompt = (
            "Based on these recently generated questions by a teacher, "
            "summarize their preferences in 2-3 sentences. "
            "Focus on: preferred difficulty, topics, description style (verbose vs concise), "
            "whether they favor starter code, and any patterns.\n\n"
            f"Recent questions:\n{json.dumps(samples, indent=2)}\n\n"
            "Output ONLY the preference summary as plain text, no JSON."
        )

        response = llm.invoke([HumanMessage(content=prompt)])
        summary = (response.content or "").strip()

        if summary and len(summary) > 20:
            pref = TeacherPreference.query.filter_by(teacher_id=teacher_id).first()
            if not pref:
                pref = TeacherPreference(teacher_id=teacher_id)
                db.session.add(pref)
            pref.style_notes = summary
            pref.updated_at = now_china()
            db.session.commit()
            logger.info("Updated style summary for teacher %d", teacher_id)

    except Exception as e:
        logger.warning("Failed to refresh teacher style summary: %s", e)
        try:
            db.session.rollback()
        except Exception:
            pass


def analyze_class_weak_areas(teacher_id: int):
    """Analyze all students in teacher's classrooms to find common weak areas.

    Updates the class_weak_areas field on TeacherPreference so the Generator
    can produce questions targeting areas where students struggle most.
    """
    from app.core.extensions import db
    from app.models.student_profile import TeacherPreference, StudentProfile
    from app.models.classroom import Classroom, Enrollment

    try:
        classrooms = Classroom.query.filter_by(teacher_id=teacher_id).all()
        if not classrooms:
            return

        classroom_ids = [c.id for c in classrooms]
        enrollments = Enrollment.query.filter(
            Enrollment.classroom_id.in_(classroom_ids)
        ).all()
        student_ids = list({e.student_id for e in enrollments})

        if not student_ids:
            return

        profiles = StudentProfile.query.filter(
            StudentProfile.student_id.in_(student_ids)
        ).all()

        topic_weakness = Counter()
        for p in profiles:
            km = p.knowledge_map or {}
            for topic, mastery in km.items():
                if mastery < 0.5:
                    topic_weakness[topic] += 1

            errors = p.error_patterns or {}
            for err_type, count in errors.items():
                if err_type != "AC" and count > 3:
                    topic_weakness[f"{err_type}_errors"] += 1

        if not topic_weakness:
            return

        weak_areas = [area for area, _ in topic_weakness.most_common(5)]

        pref = TeacherPreference.query.filter_by(teacher_id=teacher_id).first()
        if not pref:
            pref = TeacherPreference(teacher_id=teacher_id)
            db.session.add(pref)
        pref.class_weak_areas = weak_areas
        pref.updated_at = now_china()
        db.session.commit()
        logger.info("Updated class weak areas for teacher %d: %s", teacher_id, weak_areas)

    except Exception as e:
        logger.warning("Failed to analyze class weak areas: %s", e)
        try:
            db.session.rollback()
        except Exception:
            pass
