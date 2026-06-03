# Problem Variant Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild CodeRunner-AI's question bank around LeetCode-style parent problems, where one `Problem` owns shared test cases and Python/C language variants.

**Architecture:** Introduce `Problem` as the public, quiz, dashboard, and completion unit. Keep `Question` as the executable language variant used internally for starter code, reference solution, executor language, and submission linkage. Move shared fields and shared test cases to `Problem`, replace `quiz_questions` with `quiz_problems`, remove the public `/question/<question_id>` route, and use `/problem/<problem_id>?language=python|c` as the user-facing runner.

**Tech Stack:** Flask, Flask-Smorest, SQLAlchemy, Alembic migrations, MySQL/SQLite-compatible ORM patterns already used in the repo, vanilla JS templates, Bootstrap/Codemirror, pytest, Cypress.

---

## Confirmed Decisions

- Old seed data is cleared and recreated in grouped form. Existing pairs such as `Add Two Numbers` and `Add Two Numbers (C)` become one `Problem` with Python and C variants.
- Language variants may be missing in general, but the initial seed creates both Python and C variants for every seeded problem.
- Quiz membership moves from `quiz_questions.question_id` to `quiz_problems.problem_id`.
- Test cases are stored at `Problem` level and are shared by Python and C.
- User-facing entry is `/problem/<problem_id>`. The page selects Python by default and allows switching language in-page.
- The old `/question/<question_id>` user-facing URL is removed from templates and navigation.
- Dashboard language display is a per-row language dropdown.
- Dashboard row click opens `/problem/<problem_id>?language=python`.
- Teacher creation creates one `Problem` and accepts optional Python/C starter code and solution fields in the same form.
- There are no language-specific extra test cases. A shared problem-level test case may still be public or hidden, but all variants use the same set.
- Completion is counted at `Problem` level: any accepted submission in any language marks the problem complete.
- `questions` loses problem-level fields; `problems` owns title, description, difficulty, order, points, and created_by.
- `test_cases` loses `question_id`; it only stores `problem_id`.

## Final Database Shape

```text
problems
  id
  slug
  title
  description
  difficulty
  points
  order
  created_by
  created_at
  updated_at

questions
  id
  problem_id
  programming_language
  starter_code
  solution
  solution_explanation
  created_at
  updated_at

test_cases
  id
  problem_id
  input
  expected_output
  is_hidden
  weight

quiz_problems
  id
  quiz_id
  problem_id
  order
  points
  added_at

submissions
  id
  student_id
  question_id
  code
  score
  status
  error_message
  submitted_at
  execution_time
  memory_used

test_results
  id
  submission_id
  test_case_id
  passed
  actual_output
  error_message
  execution_time
```

`submissions.question_id` stays because a submission must identify the selected language variant. The user-facing route no longer exposes question IDs.

## File Structure

- Create `app/models/problem.py`: `Problem` model and relationships to variants, test cases, and quiz associations.
- Modify `app/models/question.py`: remove problem-level fields from `Question`, move `TestCase.question_id` to `TestCase.problem_id`, update relationships and serializers.
- Modify `app/models/quiz.py`: replace `QuizQuestion` with `QuizProblem`; update `Quiz.question_count` and `Quiz.total_points`.
- Modify `app/models/__init__.py`: export `Problem` and `QuizProblem`, remove `QuizQuestion`.
- Create migration `migrations/versions/20260522_problem_variant_schema.py`: create `problems` and `quiz_problems`, backfill grouped records, rebuild `questions` and `test_cases` without old fields.
- Modify `app/schemas/questions_schema.py`: add `ProblemVariantOut`, `ProblemListItemOut`, `ProblemListResponse`, `ProblemCreateIn`, and `ProblemSubmitIn`.
- Modify `app/schemas/quiz_schema.py`: replace question-based quiz schemas with problem-based ones.
- Modify `app/services/question_service.py`: keep variant-specific helpers or replace with `ProblemService`.
- Create `app/services/problem_service.py`: parent problem CRUD, variant selection, shared test case management, completion projection.
- Modify `app/services/submission_service.py`: submit by `problem_id + language`, use shared `Problem.test_cases`, store variant `question_id`.
- Modify `app/services/quiz_service.py`: use `QuizProblem`.
- Modify `app/api/v1/questions.py`: remove public and teacher list/create/update behavior from active frontend paths; keep only variant helpers that are still called by internal AI or submission code.
- Create `app/api/v1/problems.py`: public dashboard/detail/submit and teacher CRUD endpoints.
- Modify `app/api/v1/quizzes.py`: quiz problem add/remove/list APIs.
- Modify `app/api/public/metrics.py`: count `Problem`, not `Question`.
- Modify `app/web/question.py`: replace `/question/<question_id>` with `/problem/<problem_id>`.
- Create `app/templates/problem_runner.html` from the current runner layout and remove active use of `app/templates/question_runner.html`.
- Modify `app/static/js/question_runner.js`: load and submit through problem APIs and support language switching.
- Modify `app/templates/dashboard.html` and `app/static/js/dashboard.js`: fetch problems and render language dropdowns.
- Modify `app/templates/teacher/teacher_questions_create.html` and `app/static/js/teacher_questions_create.js`: create Problem with Python/C variants together.
- Modify `app/templates/teacher/teacher_questions_manage.html` and `app/static/js/teacher_questions_manage.js`: manage Problem details, shared test cases, and language variant code.
- Modify `app/static/js/student_quizzes.js`, `app/static/js/quizzes.js`, `app/static/js/teacher_profile.js`, `app/static/js/submissions.js`, and related templates: replace question wording and routes with problem-level behavior.
- Modify `app/agents/tools/question_query.py`, AI generator publishing paths, and any `GeneratedQuestionDraft` publish logic so generated questions become Problems with one or more variants.
- Modify `app/core/init_db.py`: replace flat `questions_data` with grouped `problems_data`.
- Modify Cypress fixtures under `tests/cypress/fixtures/**`: replace question list fixtures with problem + variants payloads.
- Modify pytest tests under `tests/`: update factories to create `Problem`, variants, and shared `TestCase`.
- Update docs `docs/API.md`, `docs/ARCHITECTURE.md`, and `docs/TESTING.md`.

---

### Task 1: Add Problem-Level Models and ORM Relationships

**Files:**
- Create: `app/models/problem.py`
- Modify: `app/models/question.py`
- Modify: `app/models/quiz.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_problem_models.py`

- [ ] **Step 1: Write failing model tests**

Create `tests/test_problem_models.py`:

```python
from app.core.extensions import db
from app.models.problem import Problem
from app.models.question import Question, TestCase
from app.models.quiz import Quiz, QuizProblem
from app.models.user import User, UserRole


def test_problem_owns_language_variants_and_shared_test_cases(app):
    with app.app_context():
        teacher = User(username="teacher_model", email="teacher_model@example.com", role=UserRole.TEACHER)
        db.session.add(teacher)
        db.session.flush()

        problem = Problem(
            slug="two-sum-model",
            title="Two Sum",
            description="Read two integers and output their sum.",
            difficulty="easy",
            points=10,
            order=1,
            created_by=teacher.id,
        )
        db.session.add(problem)
        db.session.flush()

        py = Question(problem_id=problem.id, programming_language="python", starter_code="", solution="")
        c = Question(problem_id=problem.id, programming_language="c", starter_code="", solution="")
        case = TestCase(problem_id=problem.id, input="1 2", expected_output="3", is_hidden=False, weight=1.0)
        db.session.add_all([py, c, case])
        db.session.commit()

        loaded = Problem.query.filter_by(slug="two-sum-model").one()
        assert {q.programming_language for q in loaded.variants} == {"python", "c"}
        assert loaded.test_cases[0].expected_output == "3"


def test_quiz_problem_counts_problem_once(app):
    with app.app_context():
        teacher = User(username="teacher_quiz_problem", email="teacher_qp@example.com", role=UserRole.TEACHER)
        db.session.add(teacher)
        db.session.flush()

        problem = Problem(slug="count-once", title="Count Once", description="Desc", created_by=teacher.id)
        quiz = Quiz(title="Quiz", description="Desc", created_by=teacher.id, is_published=True)
        db.session.add_all([problem, quiz])
        db.session.flush()

        db.session.add(QuizProblem(quiz_id=quiz.id, problem_id=problem.id, order=1, points=15))
        db.session.commit()

        assert quiz.question_count == 1
        assert quiz.total_points == 15
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
pytest tests/test_problem_models.py -q
```

Expected: fail because `app.models.problem.Problem` and `QuizProblem` do not exist.

- [ ] **Step 3: Create `Problem` model**

Create `app/models/problem.py`:

```python
from datetime import datetime

from app.core.extensions import db


class Problem(db.Model):
    """Parent problem shown in dashboard, quizzes, and problem runner."""

    __tablename__ = "problems"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(160), nullable=False, unique=True, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    difficulty = db.Column(db.String(20), default="easy")
    points = db.Column(db.Integer, default=10)
    order = db.Column(db.Integer, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    variants = db.relationship(
        "Question",
        back_populates="problem",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="Question.programming_language",
    )
    test_cases = db.relationship(
        "TestCase",
        back_populates="problem",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="TestCase.id",
    )
    quiz_associations = db.relationship(
        "QuizProblem",
        back_populates="problem",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="QuizProblem.order",
    )

    def __repr__(self):
        return f"<Problem {self.id}: {self.title}>"

    def variant_for(self, language):
        target = (language or "python").lower()
        for variant in self.variants:
            if (variant.programming_language or "").lower() == target:
                return variant
        return None
```

- [ ] **Step 4: Update `Question` and `TestCase` models**

In `app/models/question.py`, change `Question` to variant-only fields and change `TestCase` to `problem_id`:

```python
from app.core.extensions import db
from datetime import datetime


class Question(db.Model):
    """Language-specific executable variant for a parent Problem."""

    __tablename__ = "questions"

    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey("problems.id"), nullable=False)
    programming_language = db.Column(db.String(20), nullable=False, default="python")
    starter_code = db.Column(db.Text)
    solution = db.Column(db.Text)
    solution_explanation = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    problem = db.relationship("Problem", back_populates="variants")
    submissions = db.relationship("Submission", back_populates="question", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("problem_id", "programming_language", name="uq_question_problem_language"),
    )

    def __repr__(self):
        return f"<Question variant problem={self.problem_id} language={self.programming_language}>"

    def to_dict(self, include_solution=False):
        data = {
            "id": self.id,
            "problem_id": self.problem_id,
            "programming_language": self.programming_language,
            "starter_code": self.starter_code,
            "created_at": self.created_at,
        }
        if include_solution:
            data["solution"] = self.solution
            data["solution_explanation"] = self.solution_explanation
        return data


class TestCase(db.Model):
    """Shared problem-level test case used by every language variant."""

    __tablename__ = "test_cases"

    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey("problems.id"), nullable=False)
    input = db.Column(db.Text, nullable=False)
    expected_output = db.Column(db.Text, nullable=False)
    is_hidden = db.Column(db.Boolean, default=False)
    weight = db.Column(db.Float, default=1.0)

    problem = db.relationship("Problem", back_populates="test_cases")
    test_results = db.relationship("TestResult", back_populates="test_case", lazy=True)

    def __repr__(self):
        return f"<TestCase problem_id={self.problem_id} hidden={self.is_hidden}>"

    def to_dict(self, include_expected=True):
        data = {
            "id": self.id,
            "problem_id": self.problem_id,
            "input": self.input,
            "is_hidden": self.is_hidden,
            "weight": self.weight,
        }
        if include_expected:
            data["expected_output"] = self.expected_output
        return data
```

- [ ] **Step 5: Replace `QuizQuestion` with `QuizProblem`**

In `app/models/quiz.py`, replace `quiz_questions` and `QuizQuestion` with:

```python
    quiz_problems = db.relationship(
        "QuizProblem",
        back_populates="quiz",
        cascade="all, delete-orphan",
        order_by="QuizProblem.order",
    )

    @property
    def question_count(self):
        return len(self.quiz_problems)

    @property
    def total_points(self):
        return sum(qp.points for qp in self.quiz_problems)
```

Add:

```python
class QuizProblem(db.Model):
    """Association table for Quiz and Problem."""

    __tablename__ = "quiz_problems"

    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quizzes.id"), nullable=False)
    problem_id = db.Column(db.Integer, db.ForeignKey("problems.id"), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)
    points = db.Column(db.Integer, default=10)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    quiz = db.relationship("Quiz", back_populates="quiz_problems")
    problem = db.relationship("Problem", back_populates="quiz_associations")

    __table_args__ = (
        db.UniqueConstraint("quiz_id", "problem_id", name="unique_quiz_problem"),
    )

    def __repr__(self):
        return f"<QuizProblem quiz={self.quiz_id} problem={self.problem_id} order={self.order}>"
```

- [ ] **Step 6: Update model exports**

In `app/models/__init__.py`, import and export:

```python
from .problem import Problem
from .quiz import Quiz, QuizProblem, ClassroomQuiz, QuizAttempt
from .question import Question, TestCase
```

Remove `QuizQuestion` from imports and `__all__`.

- [ ] **Step 7: Run model tests**

Run:

```powershell
pytest tests/test_problem_models.py -q
```

Expected: both tests pass.

---

### Task 2: Create Destructive Schema Migration

**Files:**
- Create: `migrations/versions/20260522_problem_variant_schema.py`
- Test: run Alembic upgrade against a disposable database

- [ ] **Step 1: Write migration with final schema**

Create a migration that performs these operations in order:

```python
from alembic import op
import sqlalchemy as sa


revision = "problem_variant_schema"
down_revision = "6ed1b6dd2b48"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "problems",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.String(length=20), nullable=True, server_default="easy"),
        sa.Column("points", sa.Integer(), nullable=True, server_default="10"),
        sa.Column("order", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.UniqueConstraint("slug", name="uq_problems_slug"),
    )
    op.create_index("ix_problems_slug", "problems", ["slug"])

    op.create_table(
        "quiz_problems",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("quiz_id", sa.Integer(), nullable=False),
        sa.Column("problem_id", sa.Integer(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("points", sa.Integer(), nullable=True, server_default="10"),
        sa.Column("added_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"]),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"]),
        sa.UniqueConstraint("quiz_id", "problem_id", name="unique_quiz_problem"),
    )

    op.add_column("questions", sa.Column("problem_id", sa.Integer(), nullable=True))
    op.add_column("questions", sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.create_foreign_key("fk_questions_problem", "questions", "problems", ["problem_id"], ["id"])

    op.add_column("test_cases", sa.Column("problem_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_test_cases_problem", "test_cases", "problems", ["problem_id"], ["id"])

    # Backfill is implemented with SQLAlchemy connection in Step 2.
```

- [ ] **Step 2: Add backfill logic for existing flat questions**

In the same migration, after adding nullable columns, use `op.get_bind()` to group old questions.

Normalization rule:

```python
def canonical_title(title):
    title = (title or "").strip()
    for suffix in (" (C)", " (c)", " - C", " - c"):
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title
```

For each canonical title:

- Insert one row into `problems`.
- Use the first old question's `description`, `points`, `order`, and `created_by`.
- Set all grouped `questions.problem_id`.
- For test cases, choose one source set:
  - Prefer the Python variant's old test cases if present.
  - Otherwise use the first variant's old test cases.
- Set selected `test_cases.problem_id`.
- Delete duplicate old test cases from non-selected variants before dropping `test_cases.question_id`.
- Insert `quiz_problems` for every old `quiz_questions` association, deduplicating `(quiz_id, problem_id)`.

Use deterministic slugs:

```python
import re


def slugify(title, fallback_id):
    base = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return base or f"problem-{fallback_id}"
```

- [ ] **Step 3: Drop old columns and old table after backfill**

Finish migration:

```python
    with op.batch_alter_table("questions") as batch_op:
        batch_op.alter_column("problem_id", nullable=False)
        batch_op.drop_column("title")
        batch_op.drop_column("description")
        batch_op.drop_column("points")
        batch_op.drop_column("order")
        batch_op.drop_column("created_by")
        batch_op.create_unique_constraint("uq_question_problem_language", ["problem_id", "programming_language"])

    with op.batch_alter_table("test_cases") as batch_op:
        batch_op.alter_column("problem_id", nullable=False)
        batch_op.drop_column("question_id")

    op.drop_table("quiz_questions")
```

- [ ] **Step 4: Define downgrade as destructive reverse guard**

Because the user requested a direct thorough migration, write downgrade to recreate old tables only for schema rollback, not data restoration:

```python
def downgrade():
    op.create_table(
        "quiz_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("quiz_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("points", sa.Integer(), server_default="10"),
        sa.Column("added_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"]),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"]),
        sa.UniqueConstraint("quiz_id", "question_id", name="unique_quiz_question"),
    )
    with op.batch_alter_table("test_cases") as batch_op:
        batch_op.add_column(sa.Column("question_id", sa.Integer(), nullable=True))
        batch_op.drop_column("problem_id")
    with op.batch_alter_table("questions") as batch_op:
        batch_op.add_column(sa.Column("created_by", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("order", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("points", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("title", sa.String(length=200), nullable=True))
        batch_op.drop_constraint("uq_question_problem_language", type_="unique")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("problem_id")
    op.drop_table("quiz_problems")
    op.drop_index("ix_problems_slug", table_name="problems")
    op.drop_table("problems")
```

- [ ] **Step 5: Run migration on disposable DB**

Run:

```powershell
flask db upgrade
```

Expected: schema upgrade succeeds. If the current local database is disposable, run the project seed command after Task 8 instead of preserving existing rows.

---

### Task 3: Add Problem Schemas and Service Layer

**Files:**
- Create: `app/services/problem_service.py`
- Modify: `app/schemas/questions_schema.py`
- Test: `tests/test_problem_service.py`

- [ ] **Step 1: Write service tests**

Create `tests/test_problem_service.py`:

```python
from app.core.extensions import db
from app.models.problem import Problem
from app.models.question import Question, TestCase
from app.models.submission import Submission
from app.models.user import User, UserRole
from app.services.problem_service import ProblemService


def test_problem_list_contains_variants_and_default_python(app):
    with app.app_context():
        teacher = User(username="teacher_problem_service", email="teacher_ps@example.com", role=UserRole.TEACHER)
        db.session.add(teacher)
        db.session.flush()

        problem = Problem(slug="service-two-sum", title="Two Sum", description="Desc", created_by=teacher.id)
        db.session.add(problem)
        db.session.flush()
        db.session.add_all([
            Question(problem_id=problem.id, programming_language="c", starter_code="c", solution="c"),
            Question(problem_id=problem.id, programming_language="python", starter_code="py", solution="py"),
        ])
        db.session.commit()

        result = ProblemService.list_public_problems()
        item = next(p for p in result["items"] if p["id"] == problem.id)
        assert item["default_language"] == "python"
        assert [v["language"] for v in item["variants"]] == ["python", "c"]


def test_problem_completed_when_any_variant_has_accepted_submission(app):
    with app.app_context():
        student = User(username="student_done", email="student_done@example.com", role=UserRole.STUDENT)
        teacher = User(username="teacher_done", email="teacher_done@example.com", role=UserRole.TEACHER)
        db.session.add_all([student, teacher])
        db.session.flush()

        problem = Problem(slug="done-problem", title="Done", description="Desc", created_by=teacher.id)
        db.session.add(problem)
        db.session.flush()
        variant = Question(problem_id=problem.id, programming_language="c", starter_code="", solution="")
        db.session.add(variant)
        db.session.flush()
        db.session.add(Submission(student_id=student.id, question_id=variant.id, code="x", score=100, status="completed"))
        db.session.commit()

        assert ProblemService.is_problem_completed(student.id, problem.id) is True
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
pytest tests/test_problem_service.py -q
```

Expected: fail because `ProblemService` does not exist.

- [ ] **Step 3: Add schemas**

In `app/schemas/questions_schema.py`, add:

```python
class ProblemVariantOut(Schema):
    question_id = fields.Int(required=True)
    language = fields.Str(required=True)
    starter_code = fields.Str(allow_none=True)


class ProblemListItemOut(Schema):
    id = fields.Int(required=True)
    slug = fields.Str()
    title = fields.Str(required=True)
    description = fields.Str()
    difficulty = fields.Str(allow_none=True)
    points = fields.Int()
    order = fields.Int()
    default_language = fields.Str()
    completed = fields.Bool(load_default=False)
    variants = fields.List(fields.Nested(ProblemVariantOut))


class ProblemListResponse(Schema):
    items = fields.List(fields.Nested(ProblemListItemOut))
    total = fields.Int()
    limit = fields.Int()
    offset = fields.Int()


class ProblemCreateIn(Schema):
    quiz_id = fields.Int(required=False, allow_none=True, load_default=None)
    title = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    description = fields.Str(required=True)
    difficulty = fields.Str(load_default="easy", validate=validate.OneOf(["easy", "medium", "hard"]))
    points = fields.Int(load_default=10)
    order = fields.Int(load_default=1)
    python_starter_code = fields.Str(load_default="")
    python_solution = fields.Str(load_default="")
    python_solution_explanation = fields.Str(load_default="")
    c_starter_code = fields.Str(load_default="")
    c_solution = fields.Str(load_default="")
    c_solution_explanation = fields.Str(load_default="")


class ProblemSubmitIn(Schema):
    language = fields.Str(load_default="python", validate=validate.OneOf(["python", "c"]))
    code = fields.Str(required=True)
    time_limit_sec = fields.Float(load_default=2.0, validate=validate.Range(min=0.1, max=10.0))
```

- [ ] **Step 4: Implement `ProblemService`**

Create `app/services/problem_service.py` with:

```python
import re
from typing import Any, Dict, Optional

from flask_smorest import abort
from sqlalchemy import select, func

from app.core.extensions import db
from app.models.problem import Problem
from app.models.question import Question, TestCase
from app.models.quiz import Quiz, QuizProblem
from app.models.submission import Submission


LANGUAGE_ORDER = {"python": 0, "c": 1}


def slugify(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return base or "problem"


class ProblemService:
    @staticmethod
    def _ordered_variants(problem: Problem):
        return sorted(
            problem.variants,
            key=lambda q: LANGUAGE_ORDER.get((q.programming_language or "").lower(), 99),
        )

    @staticmethod
    def _default_language(problem: Problem) -> Optional[str]:
        if problem.variant_for("python"):
            return "python"
        variants = ProblemService._ordered_variants(problem)
        return variants[0].programming_language if variants else None

    @staticmethod
    def is_problem_completed(student_id: int, problem_id: int) -> bool:
        variant_ids = db.session.execute(
            select(Question.id).where(Question.problem_id == problem_id)
        ).scalars().all()
        if not variant_ids:
            return False
        count = db.session.execute(
            select(func.count(Submission.id)).where(
                Submission.student_id == student_id,
                Submission.question_id.in_(variant_ids),
                Submission.status == "completed",
                Submission.score >= 100,
            )
        ).scalar()
        return bool(count)

    @staticmethod
    def list_public_problems(limit: int = 100, offset: int = 0, quiz_id: Optional[int] = None, user_id: Optional[int] = None):
        query = select(Problem)
        if quiz_id:
            query = query.join(QuizProblem, QuizProblem.problem_id == Problem.id).where(QuizProblem.quiz_id == quiz_id)
            query = query.order_by(QuizProblem.order, Problem.id)
        else:
            query = query.order_by(Problem.order, Problem.id)

        total = db.session.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
        problems = db.session.execute(query.offset(offset).limit(limit)).scalars().all()

        items = []
        for problem in problems:
            variants = ProblemService._ordered_variants(problem)
            items.append({
                "id": problem.id,
                "slug": problem.slug,
                "title": problem.title,
                "description": problem.description,
                "difficulty": problem.difficulty,
                "points": problem.points,
                "order": problem.order,
                "default_language": ProblemService._default_language(problem),
                "completed": ProblemService.is_problem_completed(user_id, problem.id) if user_id else False,
                "variants": [
                    {
                        "question_id": q.id,
                        "language": q.programming_language,
                        "starter_code": q.starter_code,
                    }
                    for q in variants
                ],
            })
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @staticmethod
    def get_problem_detail(problem_id: int, language: str = "python", user_id: Optional[int] = None) -> Dict[str, Any]:
        problem = Problem.query.get(problem_id)
        if not problem:
            abort(404, message="Problem not found")

        variant = problem.variant_for(language) or problem.variant_for("python")
        if not variant:
            variants = ProblemService._ordered_variants(problem)
            variant = variants[0] if variants else None
        if not variant:
            abort(404, message="No language variant available for this problem")

        has_submission = False
        if user_id:
            has_submission = db.session.execute(
                select(Submission.id)
                .where(Submission.student_id == user_id, Submission.question_id == variant.id)
                .limit(1)
            ).first() is not None

        return {
            "id": problem.id,
            "slug": problem.slug,
            "title": problem.title,
            "description": problem.description,
            "difficulty": problem.difficulty,
            "points": problem.points,
            "selected_language": variant.programming_language,
            "selected_question_id": variant.id,
            "starter_code": variant.starter_code,
            "solution": variant.solution if has_submission else None,
            "solution_explanation": variant.solution_explanation if has_submission else None,
            "variants": [
                {"language": q.programming_language, "question_id": q.id}
                for q in ProblemService._ordered_variants(problem)
            ],
            "test_cases": [
                {
                    "id": tc.id,
                    "input": tc.input,
                    "expected_output": tc.expected_output,
                    "weight": tc.weight,
                    "is_hidden": tc.is_hidden,
                }
                for tc in problem.test_cases
                if not tc.is_hidden
            ],
        }
```

- [ ] **Step 5: Run service tests**

Run:

```powershell
pytest tests/test_problem_service.py -q
```

Expected: pass.

---

### Task 4: Rework Submission Flow Around Problem and Shared Test Cases

**Files:**
- Modify: `app/services/submission_service.py`
- Modify: `app/api/v1/submissions.py`
- Test: `tests/test_problem_submission.py`

- [ ] **Step 1: Write submission tests**

Create `tests/test_problem_submission.py`:

```python
from unittest.mock import patch

from app.core.extensions import db
from app.models.problem import Problem
from app.models.question import Question, TestCase
from app.models.user import User, UserRole
from app.services.submission_service import SubmissionService


def test_submit_problem_uses_shared_problem_test_cases(app):
    with app.app_context():
        student = User(username="student_problem_submit", email="student_ps@example.com", role=UserRole.STUDENT)
        teacher = User(username="teacher_problem_submit", email="teacher_ps@example.com", role=UserRole.TEACHER)
        db.session.add_all([student, teacher])
        db.session.flush()

        problem = Problem(slug="submit-shared", title="Shared", description="Desc", created_by=teacher.id)
        db.session.add(problem)
        db.session.flush()
        py = Question(problem_id=problem.id, programming_language="python", starter_code="", solution="")
        c = Question(problem_id=problem.id, programming_language="c", starter_code="", solution="")
        case = TestCase(problem_id=problem.id, input="2 3", expected_output="5", is_hidden=False, weight=1.0)
        db.session.add_all([py, c, case])
        db.session.commit()

        with patch("app.services.submission_service.ExecutorService.run_code") as run_code:
            run_code.return_value = {"status": "AC", "passed": True, "stdout": "5\n", "stderr": "", "time_ms": 5}
            result = SubmissionService.submit_problem_code(
                student_id=student.id,
                problem_id=problem.id,
                language="c",
                code="int main(){return 0;}",
                time_limit_sec=2.0,
            )

        assert result["score"] == 100.0
        assert result["question_id"] == c.id
        run_code.assert_called_once()
        assert run_code.call_args.kwargs["language"] == "c"
        assert run_code.call_args.kwargs["stdin_text"] == "2 3"
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```powershell
pytest tests/test_problem_submission.py -q
```

Expected: fail because `submit_problem_code` does not exist.

- [ ] **Step 3: Implement `submit_problem_code`**

In `app/services/submission_service.py`, add:

```python
    @staticmethod
    def submit_problem_code(student_id: int, problem_id: int, language: str, code: str, time_limit_sec: float = 2.0):
        from app.models.problem import Problem

        problem = Problem.query.get(problem_id)
        if not problem:
            abort(404, message="Problem not found")

        variant = problem.variant_for(language)
        if not variant:
            abort(404, message=f"No {language} variant available for this problem")

        return SubmissionService.submit_code(
            student_id=student_id,
            question_id=variant.id,
            code=code,
            time_limit_sec=time_limit_sec,
        )
```

Then change `submit_code()` test-case lookup:

```python
        test_cases = TestCase.query.filter_by(problem_id=question.problem_id).order_by(TestCase.id).all()
```

Add `question_id` and `problem_id` to response:

```python
        return {
            "id": submission.id,
            "problem_id": question.problem_id,
            "question_id": submission.question_id,
            "language": language,
            "status": submission.status,
            "score": submission.score,
            "cases": cases_output,
        }
```

- [ ] **Step 4: Update submission endpoint**

In `app/api/v1/submissions.py`, keep old `POST /questions/<int:question_id>/submit` out of frontend use and add:

```python
@blp.post("/problems/<int:problem_id>/submit")
@blp.arguments(ProblemSubmitIn)
@blp.response(201, SubmitOut)
@require_student
def submit_problem_code(payload, problem_id):
    current_user = g.current_user
    return SubmissionService.submit_problem_code(
        student_id=current_user.id,
        problem_id=problem_id,
        language=payload.get("language", "python"),
        code=payload["code"],
        time_limit_sec=payload.get("time_limit_sec", 2.0),
    )
```

Import `ProblemSubmitIn` from `app.schemas.questions_schema`.

- [ ] **Step 5: Run submission tests**

Run:

```powershell
pytest tests/test_problem_submission.py tests/test_tools.py -q
```

Expected: new problem submission test passes. `tests/test_tools.py` may still fail until Task 10 updates AI tools from question-level test cases to problem-level test cases.

---

### Task 5: Add Problem APIs and Register Blueprint

**Files:**
- Create: `app/api/v1/problems.py`
- Modify: `app/__init__.py`
- Modify: `app/api/public/metrics.py`
- Test: `tests/test_api_problems.py`

- [ ] **Step 1: Write API tests**

Create `tests/test_api_problems.py`:

```python
from app.core.extensions import db
from app.models.problem import Problem
from app.models.question import Question, TestCase
from app.models.user import User, UserRole


def test_public_problem_list_returns_language_variants(client, app):
    with app.app_context():
        teacher = User(username="teacher_api_problem", email="teacher_api_problem@example.com", role=UserRole.TEACHER)
        db.session.add(teacher)
        db.session.flush()
        problem = Problem(slug="api-two-sum", title="API Two Sum", description="Desc", created_by=teacher.id)
        db.session.add(problem)
        db.session.flush()
        db.session.add_all([
            Question(problem_id=problem.id, programming_language="python", starter_code="py", solution="py"),
            Question(problem_id=problem.id, programming_language="c", starter_code="c", solution="c"),
        ])
        db.session.commit()

    resp = client.get("/api/v1/problems")
    assert resp.status_code == 200
    data = resp.get_json()
    item = next(p for p in data["items"] if p["title"] == "API Two Sum")
    assert item["default_language"] == "python"
    assert [v["language"] for v in item["variants"]] == ["python", "c"]


def test_problem_detail_selects_language(client, app):
    with app.app_context():
        teacher = User(username="teacher_api_detail", email="teacher_api_detail@example.com", role=UserRole.TEACHER)
        db.session.add(teacher)
        db.session.flush()
        problem = Problem(slug="api-detail", title="API Detail", description="Desc", created_by=teacher.id)
        db.session.add(problem)
        db.session.flush()
        db.session.add_all([
            Question(problem_id=problem.id, programming_language="python", starter_code="py-code", solution="py-sol"),
            Question(problem_id=problem.id, programming_language="c", starter_code="c-code", solution="c-sol"),
            TestCase(problem_id=problem.id, input="1", expected_output="1", is_hidden=False, weight=1.0),
        ])
        db.session.commit()
        problem_id = problem.id

    resp = client.get(f"/api/v1/problems/{problem_id}?language=c")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["selected_language"] == "c"
    assert data["starter_code"] == "c-code"
    assert data["test_cases"][0]["input"] == "1"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
pytest tests/test_api_problems.py -q
```

Expected: 404 for `/api/v1/problems`.

- [ ] **Step 3: Create API blueprint**

Create `app/api/v1/problems.py`:

```python
from flask import g, request
from flask_smorest import Blueprint

from app.auth import optional_auth, require_teacher
from app.schemas.questions_schema import ProblemCreateIn, ProblemListResponse
from app.services.problem_service import ProblemService


blp = Blueprint("problems", __name__, description="Problem APIs", url_prefix="/api/v1")


@blp.get("/problems")
@blp.response(200, ProblemListResponse)
@optional_auth
def list_problems():
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    quiz_id = request.args.get("quiz_id", type=int)
    current_user = getattr(g, "current_user", None)
    user_id = current_user.id if current_user else None
    return ProblemService.list_public_problems(limit=limit, offset=offset, quiz_id=quiz_id, user_id=user_id)


@blp.get("/problems/<int:problem_id>")
@optional_auth
def get_problem(problem_id):
    language = request.args.get("language", "python", type=str)
    current_user = getattr(g, "current_user", None)
    user_id = current_user.id if current_user else None
    return ProblemService.get_problem_detail(problem_id, language=language, user_id=user_id)


@blp.post("/problems")
@blp.arguments(ProblemCreateIn)
@require_teacher
def create_problem(payload):
    return ProblemService.create_problem(g.current_user.id, payload), 201
```

- [ ] **Step 4: Register blueprint**

In `app/__init__.py`, add:

```python
    from app.api.v1.problems import blp as problems_blp
    api.register_blueprint(problems_blp)
```

- [ ] **Step 5: Update metrics**

In `app/api/public/metrics.py`, replace `Question.query.count()` with `Problem.query.count()` and import `Problem`.

- [ ] **Step 6: Run API tests**

Run:

```powershell
pytest tests/test_api_problems.py -q
```

Expected: pass.

---

### Task 6: Rebuild Dashboard Around Problem Rows and Language Dropdown

**Files:**
- Modify: `app/templates/dashboard.html`
- Modify: `app/static/js/dashboard.js`
- Modify: `app/static/css/dashboard.css`
- Test: `tests/cypress/e2e/public_home.cy.js` or new `tests/cypress/e2e/dashboard_problems.cy.js`

- [ ] **Step 1: Add Cypress fixture**

Create `tests/cypress/fixtures/public/problems.json`:

```json
{
  "items": [
    {
      "id": 1,
      "slug": "add-two-numbers",
      "title": "Add Two Numbers",
      "description": "Read two integers and output their sum.",
      "difficulty": "easy",
      "points": 10,
      "default_language": "python",
      "completed": false,
      "variants": [
        {"question_id": 101, "language": "python"},
        {"question_id": 102, "language": "c"}
      ]
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

- [ ] **Step 2: Write Cypress test**

Create `tests/cypress/e2e/dashboard_problems.cy.js`:

```javascript
describe("Dashboard problem list", () => {
  it("shows one problem row with a language dropdown and defaults row click to Python", () => {
    cy.intercept("GET", "**/api/v1/problems*", { fixture: "public/problems.json" }).as("problems");
    cy.intercept("GET", "**/api/v1/metrics/overview", {
      body: { global: { questions: 1, quizzes: 0, active_users: 0, submissions_24h: 0 } }
    });
    cy.intercept("GET", "**/api/public/quizzes", { body: { items: [], total: 0 } });

    cy.visit("/dashboard");
    cy.wait("@problems");
    cy.contains("td", "Add Two Numbers").should("exist");
    cy.get("[data-problem-language='1']").should("have.value", "python");
    cy.get("[data-problem-row='1']").click();
    cy.location("pathname").should("eq", "/problem/1");
    cy.location("search").should("contain", "language=python");
  });
});
```

- [ ] **Step 3: Update dashboard table header**

In `app/templates/dashboard.html`, replace the language header with:

```html
<th class="col-lang">Language</th>
```

Keep one language column, but it will contain a select element instead of a static tag.

- [ ] **Step 4: Update dashboard data fetch**

In `app/static/js/dashboard.js`, replace:

```javascript
let apiUrl = `${API_PUBLIC}/questions?limit=1000&offset=0`;
```

with:

```javascript
let apiUrl = `${API_PUBLIC}/problems?limit=1000&offset=0`;
```

Render rows with:

```javascript
pageItems.forEach((problem, idx) => {
    const globalIdx = (itemsPerPage === 'all') ? idx + 1 : (currentPage - 1) * itemsPerPage + idx + 1;
    const defaultLang = problem.default_language || 'python';
    const tr = document.createElement('tr');
    tr.dataset.problemRow = String(problem.id);
    tr.onclick = (event) => {
        if (event.target.closest('select')) return;
        window.location.href = `/problem/${problem.id}?language=python`;
    };

    const options = (problem.variants || []).map(v => {
        const selected = v.language === defaultLang ? 'selected' : '';
        return `<option value="${escapeHtml(v.language)}" ${selected}>${escapeHtml(v.language.toUpperCase())}</option>`;
    }).join('');

    tr.innerHTML = `
        <td class="col-status">
            <span class="status-icon" title="${problem.completed ? 'Completed' : 'Not attempted'}">
                <i class="bi ${problem.completed ? 'bi-check-circle-fill text-success' : 'bi-circle'}"></i>
            </span>
        </td>
        <td class="col-id"><span class="problem-id">${globalIdx}</span></td>
        <td class="col-title">
            <a class="problem-title-link" href="/problem/${problem.id}?language=python">${escapeHtml(problem.title || 'Untitled')}</a>
        </td>
        <td class="col-difficulty">${renderDifficulty(problem.difficulty)}</td>
        <td class="col-lang">
            <select class="form-select form-select-sm problem-language-select" data-problem-language="${problem.id}">
                ${options}
            </select>
        </td>
    `;
    tbody.appendChild(tr);
});

tbody.querySelectorAll('.problem-language-select').forEach(select => {
    select.addEventListener('change', (event) => {
        const problemId = event.currentTarget.dataset.problemLanguage;
        const lang = event.currentTarget.value || 'python';
        window.location.href = `/problem/${problemId}?language=${encodeURIComponent(lang)}`;
    });
});
```

Add `renderDifficulty()`:

```javascript
function renderDifficulty(difficulty) {
    const diff = (difficulty || '').toLowerCase();
    return diff
        ? `<span class="diff-badge ${escapeHtml(diff)}">${escapeHtml(diff)}</span>`
        : '<span class="diff-badge" style="background:#f3f4f6;color:#9ca3af;">-</span>';
}
```

- [ ] **Step 5: Run Cypress dashboard test**

Run:

```powershell
npx cypress run --spec tests/cypress/e2e/dashboard_problems.cy.js
```

Expected: dashboard shows one problem row and navigates to `/problem/1?language=python`.

---

### Task 7: Replace Question Runner URL With Problem Runner

**Files:**
- Modify: `app/web/question.py`
- Rename or copy: `app/templates/question_runner.html` to `app/templates/problem_runner.html`
- Modify: `app/static/js/question_runner.js`
- Modify: links in `app/templates/public/home.html`, `app/static/js/dashboard.js`, `app/static/js/student_quizzes.js`, `app/static/js/submissions.js`
- Test: `tests/cypress/e2e/student/question_runner.cy.js`

- [ ] **Step 1: Update web route**

In `app/web/question.py`, replace the route with:

```python
"""problem run page"""
from flask import Blueprint, render_template, abort, request
from app.models.problem import Problem

question_bp = Blueprint("question", __name__)


@question_bp.route("/problem/<int:problem_id>")
def run_problem(problem_id):
    problem = Problem.query.get(problem_id)
    if not problem:
        abort(404, description="Problem not found")

    selected_language = request.args.get("language", "python")
    return render_template(
        "problem_runner.html",
        problem=problem,
        selected_language=selected_language,
    )
```

Do not define `/question/<int:question_id>`.

- [ ] **Step 2: Update template data attributes**

In `app/templates/problem_runner.html`, use:

```html
<h1 class="problem-title">{{ problem.title }}</h1>
<div class="description-content">{{ problem.description|safe }}</div>

<select id="problemLanguageSelect" class="form-select form-select-sm">
  {% for variant in problem.variants %}
    <option value="{{ variant.programming_language }}" {% if variant.programming_language == selected_language %}selected{% endif %}>
      {{ variant.programming_language|upper }}
    </option>
  {% endfor %}
</select>

<textarea
  id="codeEditor"
  data-problem-id="{{ problem.id }}"
  data-language="{{ selected_language or 'python' }}"
  placeholder="// Write your code here..."
></textarea>
```

- [ ] **Step 3: Update runner JavaScript APIs**

In `app/static/js/question_runner.js`, change context:

```javascript
const PROBLEM_ID = Number(codeEl?.dataset?.problemId || 0);
let LANG = String(codeEl?.dataset?.language || "python").toLowerCase();

const API_SUBMIT = (id) => `/api/v1/problems/${id}/submit`;
const API_PROBLEM = (id, language) => `/api/v1/problems/${id}?language=${encodeURIComponent(language)}`;
```

Load detail on init:

```javascript
async function loadProblemDetail() {
  const response = await fetch(API_PROBLEM(PROBLEM_ID, LANG), { headers: AUTH.authHeaders() });
  if (!response.ok) throw new Error("Failed to load problem");
  const data = await response.json();
  if (cm) {
    cm.setValue(data.starter_code || "");
    cm.setOption("mode", cmModeFor(data.selected_language));
  } else if (els.code) {
    els.code.value = data.starter_code || "";
  }
  LANG = data.selected_language || LANG;
  hydrateTestCases(data.test_cases || []);
  hydrateSolution(data);
}
```

Change submit payload:

```javascript
const payload = {
  code: code,
  language: LANG,
  time_limit_sec: tlimit
};

const response = await fetch(API_SUBMIT(PROBLEM_ID), {
  method: "POST",
  headers: AUTH.authHeaders(),
  body: JSON.stringify(payload),
});
```

Add language selector behavior:

```javascript
const languageSelect = document.getElementById("problemLanguageSelect");
if (languageSelect) {
  languageSelect.addEventListener("change", () => {
    const next = languageSelect.value || "python";
    window.location.href = `/problem/${PROBLEM_ID}?language=${encodeURIComponent(next)}`;
  });
}
```

- [ ] **Step 4: Update links**

Replace all frontend `href="/question/${id}"` and `/question/{{ question_id }}` links with `/problem/<problem_id>?language=python`.

For submission history, include problem info in API responses first, then link:

```javascript
const href = item.problem_id ? `/problem/${item.problem_id}?language=${encodeURIComponent(item.language || 'python')}` : "/dashboard";
```

- [ ] **Step 5: Update Cypress runner test**

In `tests/cypress/e2e/student/question_runner.cy.js`, visit `/problem/1?language=python` and intercept `/api/v1/problems/1?language=python`.

- [ ] **Step 6: Run runner Cypress test**

Run:

```powershell
npx cypress run --spec tests/cypress/e2e/student/question_runner.cy.js
```

Expected: runner loads problem detail, default language is Python, language select can switch to C, submit posts to `/api/v1/problems/1/submit`.

---

### Task 8: Rewrite Seed Data as Grouped Problems

**Files:**
- Modify: `app/core/init_db.py`
- Test: `python -m app.core.init_db --drop --seed --force`

- [ ] **Step 1: Replace imports**

In `app/core/init_db.py`, replace:

```python
from app.models.quiz import Quiz, QuizQuestion, ClassroomQuiz
from app.models.question import Question, TestCase
```

with:

```python
from app.models.problem import Problem
from app.models.quiz import Quiz, QuizProblem, ClassroomQuiz
from app.models.question import Question, TestCase
```

- [ ] **Step 2: Replace `questions_data` with `problems_data`**

Use this shape:

```python
problems_data = [
    {
        "quiz": quizzes[0],
        "slug": "add-two-numbers",
        "title": "Add Two Numbers",
        "description": """Read two integers from input and output their sum.

Example:
    Input:
        5 3
    Output:
        8""",
        "difficulty": "easy",
        "order": 1,
        "points": 5,
        "created_by": teachers[0].id,
        "test_cases": [
            ("5 3", "8", False, 0.5),
            ("-10 20", "10", True, 0.5),
        ],
        "variants": {
            "python": {
                "starter_code": "# Read input and calculate sum\n# Your code here",
                "solution": "a, b = map(int, input().split())\nprint(a + b)",
                "solution_explanation": "Read two integers and print their sum.",
            },
            "c": {
                "starter_code": "#include <stdio.h>\n\nint main() {\n    return 0;\n}",
                "solution": "#include <stdio.h>\n\nint main() {\n    int a, b;\n    scanf(\"%d %d\", &a, &b);\n    printf(\"%d\\n\", a + b);\n    return 0;\n}",
                "solution_explanation": "Use scanf to read two integers and printf to output their sum.",
            },
        },
    },
]
```

Convert every current Python/C pair into one entry. Remove suffixes such as `(C)` from titles.

- [ ] **Step 3: Create records from grouped data**

Replace the old creation loop with:

```python
for p_data in problems_data:
    problem = Problem(
        slug=p_data["slug"],
        title=p_data["title"],
        description=p_data["description"],
        difficulty=p_data.get("difficulty", "easy"),
        points=p_data.get("points", 10),
        order=p_data.get("order", 1),
        created_by=p_data.get("created_by"),
    )
    db.session.add(problem)
    db.session.flush()

    quiz_problem = QuizProblem(
        quiz_id=p_data["quiz"].id,
        problem_id=problem.id,
        order=p_data.get("order", 1),
        points=p_data.get("points", 10),
    )
    db.session.add(quiz_problem)

    for input_data, expected, is_hidden, weight in p_data["test_cases"]:
        db.session.add(TestCase(
            problem_id=problem.id,
            input=input_data,
            expected_output=expected,
            is_hidden=is_hidden,
            weight=weight,
        ))

    for language, variant_data in p_data["variants"].items():
        db.session.add(Question(
            problem_id=problem.id,
            programming_language=language,
            starter_code=variant_data.get("starter_code", ""),
            solution=variant_data.get("solution", ""),
            solution_explanation=variant_data.get("solution_explanation", ""),
        ))
```

- [ ] **Step 4: Update verification output**

Replace `QuizQuestion` counts with:

```python
total_problems = Problem.query.count()
total_variants = Question.query.count()
total_quiz_problems = QuizProblem.query.count()

print(f"   - Problems: {total_problems}")
print(f"   - Language variants: {total_variants}")
print(f"   - QuizProblem associations: {total_quiz_problems}")
```

- [ ] **Step 5: Run seed**

Run:

```powershell
python -m app.core.init_db --drop --seed --force
```

Expected: database is cleared and recreated. Seed output reports Problems, language variants, and QuizProblem associations.

---

### Task 9: Rework Teacher Problem Creation and Management

**Files:**
- Modify: `app/templates/teacher/teacher_questions_create.html`
- Modify: `app/static/js/teacher_questions_create.js`
- Modify: `app/templates/teacher/teacher_questions_manage.html`
- Modify: `app/static/js/teacher_questions_manage.js`
- Modify: `app/web/teacher.py`
- Test: `tests/cypress/e2e/teacher/questions.cy.js`

- [ ] **Step 1: Update teacher routes**

In `app/web/teacher.py`, keep `/teacher/questions/create` as the existing navigation entry and add `/teacher/problems/<problem_id>/manage` as the management route:

```python
@teacher_bp.get("/questions/create")
@teacher_required
def questions_create():
    return render_template("teacher/teacher_questions_create.html", page="questions")


@teacher_bp.get("/problems/<int:problem_id>/manage")
@teacher_required
def problem_manage(problem_id):
    return render_template("teacher/teacher_questions_manage.html", page="questions", problem_id=problem_id)
```

- [ ] **Step 2: Update creation form fields**

In `teacher_questions_create.html`, replace single `qLang` and `qStarter` with fields:

```html
<textarea id="pythonStarter" class="form-control code-textarea" rows="4"></textarea>
<textarea id="pythonSolution" class="form-control code-textarea" rows="6"></textarea>
<textarea id="cStarter" class="form-control code-textarea" rows="4"></textarea>
<textarea id="cSolution" class="form-control code-textarea" rows="6"></textarea>
```

Keep title, description, difficulty, order, points, and quiz selection at problem level.

- [ ] **Step 3: Update creation JS payload**

In `teacher_questions_create.js`, replace `createQuestion()` payload with:

```javascript
const payload = {
  quiz_id: selectedQuizId || null,
  title,
  description,
  difficulty: document.getElementById('qDifficulty').value || 'easy',
  order: parseInt(document.getElementById('qOrder').value) || 1,
  points: parseInt(document.getElementById('qPoints').value) || 10,
  python_starter_code: document.getElementById('pythonStarter').value || '',
  python_solution: document.getElementById('pythonSolution').value || '',
  python_solution_explanation: document.getElementById('pythonSolutionExplanation').value || '',
  c_starter_code: document.getElementById('cStarter').value || '',
  c_solution: document.getElementById('cSolution').value || '',
  c_solution_explanation: document.getElementById('cSolutionExplanation').value || ''
};

const response = await authenticatedFetch(`${API_BASE}/problems`, {
  method: 'POST',
  body: JSON.stringify(payload)
});
```

- [ ] **Step 4: Update manage page**

`teacher_questions_manage.html` should show:

- Problem title, description, difficulty, order, points.
- Language tabs for Python and C.
- Variant starter code and solution fields for the selected language.
- One shared test case panel.

Test case endpoints must be problem-level:

```javascript
authenticatedFetch(`${API_BASE}/problems/${problemId}/test-cases`)
authenticatedFetch(`${API_BASE}/test-cases/${tcId}`)
```

- [ ] **Step 5: Update teacher list**

Teacher list should fetch `/api/v1/teacher/problems` or `/api/v1/problems?created_by_me=true` and render one row per Problem. Manage button goes to:

```javascript
window.location.href = `/teacher/problems/${id}/manage`;
```

- [ ] **Step 6: Run teacher Cypress tests**

Run:

```powershell
npx cypress run --spec tests/cypress/e2e/teacher/questions.cy.js
```

Expected: teacher can create one Problem with Python/C optional code fields and manage one shared test-case set.

---

### Task 10: Rework Quiz APIs, Student Quiz Views, and Completion Progress

**Files:**
- Modify: `app/services/quiz_service.py`
- Modify: `app/api/v1/quizzes.py`
- Modify: `app/schemas/quiz_schema.py`
- Modify: `app/static/js/quizzes.js`
- Modify: `app/static/js/student_quizzes.js`
- Test: `tests/cypress/e2e/teacher/quizzes.cy.js`
- Test: `tests/cypress/e2e/student/quizzes.cy.js`

- [ ] **Step 1: Replace service methods**

In `QuizService`, replace question methods with problem methods:

```python
@staticmethod
def add_problem_to_quiz(quiz_id, problem_id, order=None, points=10):
    quiz = Quiz.query.get(quiz_id)
    problem = Problem.query.get(problem_id)
    if not quiz or not problem:
        return None
    existing = QuizProblem.query.filter_by(quiz_id=quiz_id, problem_id=problem_id).first()
    if existing:
        return None
    if order is None:
        max_order = db.session.query(db.func.max(QuizProblem.order)).filter_by(quiz_id=quiz_id).scalar()
        order = (max_order or 0) + 1
    quiz_problem = QuizProblem(quiz_id=quiz_id, problem_id=problem_id, order=order, points=points)
    db.session.add(quiz_problem)
    db.session.commit()
    return quiz_problem
```

Also implement `remove_problem_from_quiz()` and `update_quiz_problem()` with `QuizProblem`.

- [ ] **Step 2: Update quiz detail serialization**

Return `problems` instead of `questions`:

```json
{
  "id": 201,
  "title": "Python Basics Quiz",
  "problems": [
    {
      "id": 1,
      "title": "Add Two Numbers",
      "difficulty": "easy",
      "points": 10,
      "completed": true,
      "variants": [
        {"language": "python", "question_id": 101},
        {"language": "c", "question_id": 102}
      ]
    }
  ],
  "progress": {
    "completed_problems": 1,
    "total_problems": 1
  }
}
```

- [ ] **Step 3: Update completion logic**

For each quiz problem, count completed if any variant has a `Submission` with `status == "completed"` and `score >= 100`.

- [ ] **Step 4: Update student quiz frontend**

In `student_quizzes.js`, replace `quiz.questions` with `quiz.problems` and link:

```javascript
<a href="/problem/${problem.id}?language=python" class="btn btn-sm ${hasSubmission ? 'btn-outline-success' : 'btn-primary'}">
  ${hasSubmission ? 'Review' : 'Start'}
</a>
```

- [ ] **Step 5: Update teacher quiz frontend**

In `quizzes.js`, change add/remove endpoints from `questions` to `problems`:

```javascript
`${API_BASE}/quizzes/${currentQuizId}/problems`
`${API_BASE}/quizzes/${currentQuizId}/problems/${problemId}`
```

- [ ] **Step 6: Run quiz Cypress tests**

Run:

```powershell
npx cypress run --spec tests/cypress/e2e/teacher/quizzes.cy.js,tests/cypress/e2e/student/quizzes.cy.js
```

Expected: quizzes display problems once, progress is problem-based, and Start opens `/problem/<id>?language=python`.

---

### Task 11: Update AI Tools, Generated Question Publishing, and Security-Sensitive Query Paths

**Files:**
- Modify: `app/agents/tools/question_query.py`
- Modify: `app/agents/agents/generator.py`
- Modify: `app/api/v1/ai.py`
- Modify: `app/models/generated_question_draft.py`
- Test: `tests/test_tools.py`
- Test: `tests/test_agents.py`
- Test: `tests/test_api_ai.py`

- [ ] **Step 1: Update question query tool**

Change `get_question_detail(question_id)` to resolve variant then parent problem:

```python
q = Question.query.get(question_id)
problem = q.problem if q else None
cases = TestCase.query.filter_by(problem_id=problem.id, is_hidden=False).all()
```

Return:

```python
{
    "id": q.id,
    "problem_id": problem.id,
    "title": problem.title,
    "description": problem.description,
    "language": q.programming_language,
    "test_cases": [
        {"input": tc.input, "expected_output": tc.expected_output}
        for tc in cases
    ],
}
```

- [ ] **Step 2: Update generator publishing**

When generator output includes one language only, create:

- One `Problem`
- One `Question` variant for the generated language
- Shared `TestCase` rows on `problem_id`

When generator output includes Python and C, create one `Problem` and two `Question` variants.

- [ ] **Step 3: Update generated draft model references**

Keep `GeneratedQuestionDraft.published_question_id` as the selected variant link and add `published_problem_id` so review queue links to `/problem/<problem_id>`.

Migration:

```python
op.add_column("generated_question_drafts", sa.Column("published_problem_id", sa.Integer(), nullable=True))
op.create_foreign_key("fk_generated_question_draft_problem", "generated_question_drafts", "problems", ["published_problem_id"], ["id"])
```

- [ ] **Step 4: Run AI tests**

Run:

```powershell
pytest tests/test_tools.py tests/test_agents.py tests/test_api_ai.py -q
```

Expected: tests pass with problem-level shared cases.

---

### Task 12: Update Submission Lists, Profiles, Grades, and Metrics

**Files:**
- Modify: `app/services/submission_service.py`
- Modify: `app/api/v1/grades.py`
- Modify: `app/services/teacher_stats_service.py`
- Modify: `app/static/js/submissions.js`
- Modify: `app/static/js/submission_detail.js`
- Modify: `app/static/js/student_profile.js`
- Modify: `app/static/js/teacher_profile.js`
- Test: `tests/cypress/e2e/student/profile.cy.js`
- Test: `tests/cypress/e2e/teacher/profile.cy.js`
- Test: `tests/cypress/e2e/teacher/grades.cy.js`

- [ ] **Step 1: Include problem metadata in submission responses**

In `SubmissionService.get_student_submissions()`, join `Submission -> Question -> Problem` and return:

```python
{
    "id": submission.id,
    "problem_id": problem.id,
    "question_id": submission.question_id,
    "question_title": problem.title,
    "language": question.programming_language,
    "status": submission.status,
    "score": submission.score,
    "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else None,
}
```

- [ ] **Step 2: Update frontend links**

In submission/profile views, link to:

```javascript
`/problem/${item.problem_id}?language=${encodeURIComponent(item.language || 'python')}`
```

- [ ] **Step 3: Update teacher stats**

Question count becomes problem count:

```python
Problem.query.filter_by(created_by=teacher_id).count()
```

Recent published questions should become recent problems and display available languages.

- [ ] **Step 4: Update grades filters**

Grades can keep filtering by selected Problem. Backend maps a `problem_id` filter to all variant `question_id`s:

```python
variant_ids = select(Question.id).where(Question.problem_id == problem_id)
query = query.filter(Submission.question_id.in_(variant_ids))
```

- [ ] **Step 5: Run affected Cypress tests**

Run:

```powershell
npx cypress run --spec tests/cypress/e2e/student/profile.cy.js,tests/cypress/e2e/teacher/profile.cy.js,tests/cypress/e2e/teacher/grades.cy.js
```

Expected: profile, submission, and grades views show problem title and language, with problem-level links.

---

### Task 13: Update Fixtures and End-to-End Tests

**Files:**
- Modify: `tests/cypress/fixtures/student/*.json`
- Modify: `tests/cypress/fixtures/teacher/*.json`
- Modify: `tests/cypress/e2e/**/*.cy.js`

- [ ] **Step 1: Replace fixture fields**

Update fixture objects:

```json
{
  "problem_id": 1,
  "title": "Add Two Numbers",
  "difficulty": "easy",
  "language": "python",
  "variants": [
    {"language": "python", "question_id": 101},
    {"language": "c", "question_id": 102}
  ]
}
```

Remove assumptions that one row equals one language-specific title.

- [ ] **Step 2: Update route assertions**

Replace assertions for `/question/` with `/problem/`.

```javascript
cy.location("pathname").should("match", /^\/problem\/\d+$/);
```

- [ ] **Step 3: Update completion assertions**

For quizzes and dashboard, assert one completed Problem when any variant submission has score 100.

- [ ] **Step 4: Run full Cypress suite**

Run:

```powershell
npx cypress run
```

Expected: all Cypress specs pass.

---

### Task 14: Update Documentation

**Files:**
- Modify: `docs/API.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/TESTING.md`
- Modify: `README.md` if it describes question storage or dashboard flow

- [ ] **Step 1: Update architecture docs**

Document:

```text
Problem is the public practice unit.
Question is an executable language variant.
TestCase belongs to Problem and is shared by variants.
Submission belongs to Question so language-specific history remains available.
QuizProblem links quizzes to Problems.
```

- [ ] **Step 2: Update API docs**

Add:

```text
GET /api/v1/problems
GET /api/v1/problems/{problem_id}?language=python
POST /api/v1/problems/{problem_id}/submit
POST /api/v1/problems
PATCH /api/v1/problems/{problem_id}
POST /api/v1/problems/{problem_id}/test-cases
```

Remove user-facing documentation for `/question/<question_id>`.

- [ ] **Step 3: Update testing docs**

Document seed command:

```powershell
python -m app.core.init_db --drop --seed --force
```

Document that seed creates grouped Problems with Python/C variants.

---

### Task 15: Full Verification

**Files:**
- No source files changed in this task.

- [ ] **Step 1: Run database reset and seed**

Run:

```powershell
python -m app.core.init_db --drop --seed --force
```

Expected: Problems, variants, shared test cases, and QuizProblem associations are created.

- [ ] **Step 2: Run backend tests**

Run:

```powershell
pytest -q
```

Expected: all pytest tests pass.

- [ ] **Step 3: Run Cypress tests**

Run:

```powershell
npx cypress run
```

Expected: all Cypress tests pass.

- [ ] **Step 4: Manual browser smoke**

Start app, then verify:

```text
/dashboard shows one row per Problem.
Clicking a row opens /problem/<id>?language=python.
Changing dashboard language dropdown opens /problem/<id>?language=c.
Problem runner loads shared test cases in both languages.
Submitting Python and C uses the same test cases.
Teacher creates one Problem with optional Python/C code fields.
Quiz shows the Problem once.
Any accepted variant marks the Problem complete.
No visible navigation points to /question/<question_id>.
```

---

## Self-Review

- Spec coverage: all user-confirmed decisions are represented in database shape, APIs, frontend routes, teacher flow, seed data, quiz migration, completion semantics, and tests.
- Placeholder scan: no placeholder task remains; each task names concrete files, commands, and expected outcomes.
- Type consistency: the plan consistently uses `Problem` as parent, `Question` as variant, `TestCase.problem_id`, `QuizProblem`, `/problem/<problem_id>`, and `POST /api/v1/problems/<problem_id>/submit`.
