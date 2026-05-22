"""Quiz Management API."""
from datetime import datetime

from flask import g, request
from flask_smorest import Blueprint, abort
from sqlalchemy import desc, select

from app.auth import require_auth, require_teacher
from app.core.extensions import db
from app.models.problem import Problem
from app.models.question import Question
from app.models.quiz import ClassroomQuiz
from app.models.submission import Submission
from app.models.user import User
from app.services.quiz_service import QuizService


blp = Blueprint(
    "quizzes",
    __name__,
    description="Quiz Management APIs",
    url_prefix="/api/v1/quizzes"
)


def _variant_ids(problem_id):
    return db.session.execute(
        select(Question.id).where(Question.problem_id == problem_id)
    ).scalars().all()


def _best_problem_submission(student_id, problem_id):
    variant_ids = _variant_ids(problem_id)
    if not variant_ids:
        return None
    return (
        Submission.query
        .filter(
            Submission.student_id == student_id,
            Submission.question_id.in_(variant_ids),
            Submission.status == "completed",
        )
        .order_by(Submission.score.desc(), Submission.submitted_at.desc())
        .first()
    )


def _serialize_problem(qp, student_id=None):
    problem = qp.problem
    if not problem:
        return None
    submission = _best_problem_submission(student_id, problem.id) if student_id else None
    completed = bool(submission and (submission.score or 0) >= 100)
    data = {
        "id": problem.id,
        "problem_id": problem.id,
        "title": problem.title,
        "description": problem.description,
        "difficulty": problem.difficulty,
        "order": qp.order,
        "points": qp.points,
        "completed": completed,
        "variants": [
            {"language": q.programming_language, "question_id": q.id}
            for q in sorted(problem.variants, key=lambda q: q.programming_language or "")
        ],
    }
    if submission:
        data["submission"] = {
            "id": submission.id,
            "status": submission.status,
            "score": submission.score,
            "question_score": round(((submission.score or 0) / 100.0) * (qp.points or 0), 1),
            "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else None,
        }
    else:
        data["submission"] = None
    return data


def _quiz_problems(quiz):
    return sorted(quiz.quiz_problems or [], key=lambda qp: (qp.order, qp.id))


def _ensure_teacher_owns_quiz(quiz_id):
    quiz = QuizService.get_quiz_by_id(quiz_id)
    if not quiz:
        abort(404, message="Quiz not found")
    if quiz.created_by != g.current_user.id:
        abort(403, message="You can only manage your own quizzes")
    return quiz


@blp.get("/")
@require_auth
def get_quizzes():
    current_user = g.current_user
    if current_user.role.value == "student":
        classroom_quizzes, _ = QuizService.get_student_quizzes(current_user.id)
        items = []
        for cq in classroom_quizzes:
            quiz = cq.quiz
            if not quiz:
                continue
            qps = _quiz_problems(quiz)
            completed_count = 0
            total_score = 0.0
            max_score = sum(qp.points or 0 for qp in qps)
            for qp in qps:
                submission = _best_problem_submission(current_user.id, qp.problem_id)
                if submission and (submission.score or 0) >= 100:
                    completed_count += 1
                if submission and submission.score is not None:
                    total_score += (submission.score / 100.0) * (qp.points or 0)

            total_count = len(qps)
            progress_percentage = (completed_count / total_count * 100) if total_count else 0
            attempt = None
            if completed_count > 0:
                attempt = {
                    "id": None,
                    "status": "completed" if completed_count == total_count else "in_progress",
                    "score": round(total_score, 1),
                    "max_score": max_score,
                    "percentage": round((total_score / max_score * 100) if max_score else 0, 1),
                }

            items.append({
                "id": quiz.id,
                "title": quiz.title,
                "description": quiz.description,
                "duration_minutes": quiz.duration_minutes,
                "question_count": total_count,
                "problem_count": total_count,
                "completed_questions": completed_count,
                "completed_problems": completed_count,
                "progress_percentage": round(progress_percentage, 1),
                "classroom": {"id": cq.classroom.id, "name": cq.classroom.name} if cq.classroom else None,
                "due_date": cq.due_date.isoformat() if cq.due_date else None,
                "is_overdue": cq.is_overdue,
                "attempt": attempt,
            })
        return {"items": items, "total": len(items)}

    if current_user.role.value == "teacher":
        quizzes = QuizService.get_teacher_quizzes(current_user.id)
        items = []
        for quiz in quizzes:
            assigned_count = ClassroomQuiz.query.filter_by(quiz_id=quiz.id).count()
            items.append({
                "id": quiz.id,
                "title": quiz.title,
                "description": quiz.description,
                "duration_minutes": quiz.duration_minutes,
                "is_published": quiz.is_published,
                "question_count": quiz.question_count,
                "problem_count": quiz.question_count,
                "total_points": quiz.total_points,
                "assigned_to_count": assigned_count,
                "created_at": quiz.created_at.isoformat() if quiz.created_at else None,
            })
        return {"items": items, "total": len(items)}

    abort(403, message="Invalid role")


@blp.post("")
@require_teacher
def create_quiz():
    data = request.get_json() or {}
    title = data.get("title", "").strip()
    if not title:
        abort(400, message="Quiz title is required")

    quiz = QuizService.create_quiz(
        title=title,
        description=data.get("description", ""),
        created_by=g.current_user.id,
        duration_minutes=data.get("duration_minutes"),
        is_published=data.get("is_published", False),
    )
    return {
        "id": quiz.id,
        "title": quiz.title,
        "description": quiz.description,
        "created_by": quiz.created_by,
        "duration_minutes": quiz.duration_minutes,
        "is_published": quiz.is_published,
        "created_at": quiz.created_at.isoformat() if quiz.created_at else None,
        "question_count": 0,
        "problem_count": 0,
        "total_points": 0,
    }, 201


@blp.get("/<int:quiz_id>")
@require_auth
def get_quiz(quiz_id):
    quiz = QuizService.get_quiz_by_id(quiz_id)
    if not quiz:
        abort(404, message="Quiz not found")

    current_user = g.current_user
    if current_user.role.value == "teacher":
        if quiz.created_by != current_user.id:
            abort(403, message="You can only view your own quizzes")
    else:
        if not quiz.is_published:
            abort(403, message="This quiz is not published")
        classroom_quizzes, _ = QuizService.get_student_quizzes(current_user.id)
        if quiz.id not in [cq.quiz_id for cq in classroom_quizzes]:
            abort(403, message="You don't have access to this quiz")

    problems = [
        item for item in (_serialize_problem(qp, current_user.id if current_user.role.value == "student" else None)
                          for qp in _quiz_problems(quiz))
        if item
    ]
    completed_count = sum(1 for p in problems if p.get("completed"))
    total_score = sum((p.get("submission") or {}).get("question_score", 0) for p in problems)
    max_score = sum(p.get("points") or 0 for p in problems)

    result = {
        "id": quiz.id,
        "title": quiz.title,
        "description": quiz.description,
        "created_by": quiz.created_by,
        "duration_minutes": quiz.duration_minutes,
        "is_published": quiz.is_published,
        "created_at": quiz.created_at.isoformat() if quiz.created_at else None,
        "updated_at": quiz.updated_at.isoformat() if quiz.updated_at else None,
        "question_count": len(problems),
        "problem_count": len(problems),
        "total_points": quiz.total_points,
        "creator": {"id": quiz.creator.id, "username": quiz.creator.username} if quiz.creator else None,
        "problems": problems,
        "questions": problems,
    }

    if current_user.role.value == "student":
        classroom_quizzes, _ = QuizService.get_student_quizzes(current_user.id)
        for cq in classroom_quizzes:
            if cq.quiz_id == quiz.id:
                result["classroom"] = {"id": cq.classroom.id, "name": cq.classroom.name} if cq.classroom else None
                result["due_date"] = cq.due_date.isoformat() if cq.due_date else None
                result["is_overdue"] = cq.is_overdue
                break
        result["progress"] = {
            "completed_problems": completed_count,
            "total_problems": len(problems),
            "completed_questions": completed_count,
            "total_questions": len(problems),
            "progress_percentage": round((completed_count / len(problems) * 100) if problems else 0, 1),
            "total_score": round(total_score, 1),
            "max_score": max_score,
            "percentage": round((total_score / max_score * 100) if max_score else 0, 1),
        }

    return result


@blp.put("/<int:quiz_id>")
@require_teacher
def update_quiz(quiz_id):
    quiz = _ensure_teacher_owns_quiz(quiz_id)
    data = request.get_json() or {}
    update_fields = {}
    if "title" in data:
        title = data["title"].strip()
        if not title:
            abort(400, message="Quiz title cannot be empty")
        update_fields["title"] = title
    for field in ("description", "duration_minutes", "is_published"):
        if field in data:
            update_fields[field] = data[field]
    if not update_fields:
        abort(400, message="No fields to update")
    quiz = QuizService.update_quiz(quiz.id, **update_fields)
    return {
        "id": quiz.id,
        "title": quiz.title,
        "description": quiz.description,
        "duration_minutes": quiz.duration_minutes,
        "is_published": quiz.is_published,
        "updated_at": quiz.updated_at.isoformat() if quiz.updated_at else None,
        "message": "Quiz updated successfully",
    }


@blp.delete("/<int:quiz_id>")
@require_teacher
def delete_quiz(quiz_id):
    quiz = _ensure_teacher_owns_quiz(quiz_id)
    if not QuizService.delete_quiz(quiz.id):
        abort(400, message="Failed to delete quiz")
    return {"message": "Quiz deleted successfully"}


@blp.get("/<int:quiz_id>/problems")
@require_teacher
def get_quiz_problems(quiz_id):
    quiz = _ensure_teacher_owns_quiz(quiz_id)
    items = [_serialize_problem(qp) for qp in _quiz_problems(quiz)]
    return {"items": [item for item in items if item], "total": len(items)}


@blp.post("/<int:quiz_id>/problems")
@require_teacher
def add_problem_to_quiz(quiz_id):
    _ensure_teacher_owns_quiz(quiz_id)
    payload = request.get_json() or {}
    problem_id = payload.get("problem_id") or payload.get("question_id")
    if not problem_id:
        abort(400, message="problem_id is required")
    problem = Problem.query.get(problem_id)
    if not problem:
        variant = Question.query.get(problem_id)
        problem = variant.problem if variant else None
    if not problem:
        abort(404, message="Problem not found")

    quiz_problem = QuizService.add_problem_to_quiz(
        quiz_id=quiz_id,
        problem_id=problem.id,
        order=payload.get("order"),
        points=payload.get("points", 10),
    )
    if not quiz_problem:
        abort(400, message="Failed to add problem. Problem may already exist in quiz.")
    return _serialize_problem(quiz_problem), 201


@blp.put("/<int:quiz_id>/problems/<int:problem_id>")
@require_teacher
def update_quiz_problem(quiz_id, problem_id):
    _ensure_teacher_owns_quiz(quiz_id)
    data = request.get_json() or {}
    quiz_problem = QuizService.update_quiz_problem(
        quiz_id,
        problem_id,
        order=data.get("order"),
        points=data.get("points"),
    )
    if not quiz_problem:
        abort(404, message="Problem not found in quiz")
    return {
        "id": quiz_problem.id,
        "order": quiz_problem.order,
        "points": quiz_problem.points,
        "message": "Quiz problem updated successfully",
    }


@blp.delete("/<int:quiz_id>/problems/<int:problem_id>")
@require_teacher
def remove_problem_from_quiz(quiz_id, problem_id):
    _ensure_teacher_owns_quiz(quiz_id)
    if not QuizService.remove_problem_from_quiz(quiz_id, problem_id):
        abort(404, message="Problem not found in this quiz")
    return {"message": "Problem removed successfully"}


@blp.get("/<int:quiz_id>/questions")
@require_teacher
def get_quiz_questions_compat(quiz_id):
    return get_quiz_problems(quiz_id)


@blp.post("/<int:quiz_id>/questions")
@require_teacher
def add_question_to_quiz_compat(quiz_id):
    return add_problem_to_quiz(quiz_id)


@blp.put("/<int:quiz_id>/questions/<int:question_id>")
@require_teacher
def update_quiz_question_compat(quiz_id, question_id):
    variant = Question.query.get(question_id)
    problem_id = variant.problem_id if variant else question_id
    return update_quiz_problem(quiz_id, problem_id)


@blp.delete("/<int:quiz_id>/questions/<int:question_id>")
@require_teacher
def remove_question_from_quiz_compat(quiz_id, question_id):
    variant = Question.query.get(question_id)
    problem_id = variant.problem_id if variant else question_id
    return remove_problem_from_quiz(quiz_id, problem_id)


@blp.post("/<int:quiz_id>/assign")
@require_teacher
def assign_quiz_to_classroom(quiz_id):
    _ensure_teacher_owns_quiz(quiz_id)
    data = request.get_json() or {}
    classroom_id = data.get("classroom_id")
    if not classroom_id:
        abort(400, message="classroom_id is required")
    due_date = None
    if data.get("due_date"):
        try:
            due_date = datetime.fromisoformat(data["due_date"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            abort(400, message="Invalid due_date format. Use ISO format.")
    classroom_quiz = QuizService.assign_quiz_to_classroom(
        quiz_id=quiz_id,
        classroom_id=classroom_id,
        assigned_by=g.current_user.id,
        due_date=due_date,
        allow_late_submission=data.get("allow_late_submission", False),
    )
    if not classroom_quiz:
        abort(400, message="Failed to assign quiz (may already be assigned or classroom not found)")
    return {
        "id": classroom_quiz.id,
        "quiz_id": classroom_quiz.quiz_id,
        "classroom_id": classroom_quiz.classroom_id,
        "due_date": classroom_quiz.due_date.isoformat() if classroom_quiz.due_date else None,
        "allow_late_submission": classroom_quiz.allow_late_submission,
        "message": "Quiz assigned to classroom successfully",
    }, 201


@blp.delete("/<int:quiz_id>/assign/<int:classroom_id>")
@require_teacher
def unassign_quiz_from_classroom(quiz_id, classroom_id):
    _ensure_teacher_owns_quiz(quiz_id)
    if not QuizService.unassign_quiz_from_classroom(quiz_id, classroom_id):
        abort(404, message="Quiz is not assigned to this classroom")
    return {"message": "Quiz unassigned from classroom successfully"}


@blp.get("/<int:quiz_id>/assignments")
@require_teacher
def get_quiz_assignments(quiz_id):
    _ensure_teacher_owns_quiz(quiz_id)
    items = []
    for cq in QuizService.get_quiz_classrooms(quiz_id):
        if cq.classroom:
            items.append({
                "id": cq.id,
                "classroom_id": cq.classroom.id,
                "classroom_name": cq.classroom.name,
                "classroom_code": cq.classroom.code,
                "assigned_at": cq.assigned_at.isoformat() if cq.assigned_at else None,
                "due_date": cq.due_date.isoformat() if cq.due_date else None,
                "is_overdue": cq.is_overdue,
                "allow_late_submission": cq.allow_late_submission,
            })
    return {"items": items, "total": len(items)}


@blp.get("/<int:quiz_id>/attempts")
@require_teacher
def get_quiz_attempts(quiz_id):
    quiz = _ensure_teacher_owns_quiz(quiz_id)
    qps = _quiz_problems(quiz)
    variant_ids_by_problem = {qp.problem_id: _variant_ids(qp.problem_id) for qp in qps}
    all_variant_ids = [qid for ids in variant_ids_by_problem.values() for qid in ids]
    if not all_variant_ids:
        return {"items": [], "total": 0}

    students = (
        db.session.query(Submission.student_id, User.username)
        .join(User, Submission.student_id == User.id)
        .filter(Submission.question_id.in_(all_variant_ids))
        .distinct()
        .all()
    )
    items = []
    for student_id, student_username in students:
        completed_count = 0
        total_score = 0.0
        max_score = sum(qp.points or 0 for qp in qps)
        submission_times = []
        for qp in qps:
            submission = _best_problem_submission(student_id, qp.problem_id)
            if not submission:
                continue
            if (submission.score or 0) >= 100:
                completed_count += 1
            total_score += ((submission.score or 0) / 100.0) * (qp.points or 0)
            if submission.submitted_at:
                submission_times.append(submission.submitted_at)

        if not submission_times:
            continue
        started_at = min(submission_times)
        completed_at = max(submission_times)
        status = "completed" if completed_count == len(qps) else "in_progress"
        duration = (completed_at - started_at).total_seconds() / 60 if completed_at != started_at else None
        items.append({
            "id": None,
            "student": {"id": student_id, "username": student_username},
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat() if status == "completed" else None,
            "status": status,
            "score": round(total_score, 1),
            "max_score": max_score,
            "percentage": round((total_score / max_score * 100) if max_score else 0, 1),
            "duration_minutes": round(duration, 1) if duration else None,
        })

    items.sort(key=lambda x: x["score"], reverse=True)
    return {"items": items, "total": len(items)}
