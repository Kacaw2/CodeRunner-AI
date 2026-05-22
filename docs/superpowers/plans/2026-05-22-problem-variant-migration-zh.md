# Problem 语言版本迁移中文执行方案

> **给执行 agent 的要求：** 实施本方案时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项执行。每个步骤使用 checkbox（`- [ ]`）跟踪状态。

**目标：** 将 CodeRunner-AI 的题库从“一个语言版本一条 Question”改造成 LeetCode 风格的“一个 Problem 下挂 Python/C 多个语言版本”，并让 Python 和 C 共用同一套测试用例。

**架构：** 新增 `Problem` 作为公开展示、Dashboard、Quiz、完成状态统计的主实体；保留 `Question` 作为具体可执行语言版本，用于保存 `programming_language`、starter code、solution，并继续作为提交记录的语言定位句柄。测试用例移动到 `Problem` 层，Quiz 关系从 `quiz_questions` 迁移到 `quiz_problems`，用户做题入口统一改成 `/problem/<problem_id>?language=python|c`。

**技术栈：** Flask、Flask-Smorest、SQLAlchemy、Alembic、当前项目已有的 MySQL/SQLite ORM 模式、Jinja 模板、原生 JavaScript、Bootstrap、CodeMirror、pytest、Cypress。

---

## 已确认需求

- 清除并重建旧 seed 数据，把现有 `Add Two Numbers` / `Add Two Numbers (C)` 这类题合并成同一个 `Problem`。
- 语言版本允许缺失，但初始 seed 中每道题都创建 Python 和 C 两个版本。
- Quiz 升级为挂 `Problem`，新增 `quiz_problems`，不再使用 `quiz_questions.question_id`。
- 测试用例存储在 `Problem` 层，Python 和 C 共用一份。
- 用户进入 `/problem/<problem_id>`，页面内选择 Python/C。
- 默认语言是 Python：Dashboard 点击整行时进入 `/problem/<problem_id>?language=python`。
- Dashboard 的语言展示使用下拉选择，而不是多个按钮。
- 不保留旧的用户可见 `/question/<question_id>` URL，前端链接全部改成 `/problem/<problem_id>`。
- 教师端一次创建一个 `Problem`，同时填写 Python/C 两套 starter code 和 solution，允许某个语言版本代码留空。
- 不允许语言版本拥有额外测试用例；测试用例只能属于 Problem。
- 完成状态按 `Problem` 统计，任一语言版本 AC 即算这道题完成。
- `questions` 表只保留语言版本字段，`title`、`description`、`difficulty`、`points`、`order`、`created_by` 迁移到 `problems`。
- `test_cases` 表只保留 `problem_id`，彻底删除 `question_id`。

## 最终数据库结构

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

`submissions.question_id` 继续保留，因为一次提交必须能定位到具体语言版本。区别是这个 ID 不再暴露为用户做题 URL。

## 需要创建或修改的文件

- 新建 `app/models/problem.py`：定义 `Problem` 模型，维护 variants、test cases、quiz associations。
- 修改 `app/models/question.py`：把 `Question` 改成语言版本模型，把 `TestCase.question_id` 改成 `TestCase.problem_id`。
- 修改 `app/models/quiz.py`：用 `QuizProblem` 替换 `QuizQuestion`，更新 `question_count` 和 `total_points`。
- 修改 `app/models/__init__.py`：导出 `Problem` 和 `QuizProblem`，移除 `QuizQuestion`。
- 新建 `migrations/versions/20260522_problem_variant_schema.py`：执行彻底 schema 迁移、旧数据合并、旧字段删除。
- 修改 `app/schemas/questions_schema.py`：新增 `ProblemVariantOut`、`ProblemListItemOut`、`ProblemListResponse`、`ProblemCreateIn`、`ProblemSubmitIn`。
- 修改 `app/schemas/quiz_schema.py`：将 quiz question schema 改为 quiz problem schema。
- 新建 `app/services/problem_service.py`：负责 Problem 查询、创建、语言版本选择、共享测试用例、完成状态计算。
- 修改 `app/services/question_service.py`：移除前端使用的 question 级 CRUD，保留仍被内部 AI 或提交逻辑调用的 variant helper。
- 修改 `app/services/submission_service.py`：新增按 `problem_id + language` 提交流程，用 `question.problem_id` 查询共享 test cases。
- 修改 `app/services/quiz_service.py`：改用 `QuizProblem`。
- 新建 `app/api/v1/problems.py`：提供 Problem 列表、详情、创建、提交等接口。
- 修改 `app/api/v1/questions.py`：移除公开和教师列表/创建路径上的 Question 级行为。
- 修改 `app/api/v1/quizzes.py`：quiz 添加/移除题目改为 problem 级。
- 修改 `app/api/public/metrics.py`：题目数统计 `Problem`，不是 `Question`。
- 修改 `app/web/question.py`：删除 `/question/<question_id>`，新增 `/problem/<problem_id>`。
- 新建 `app/templates/problem_runner.html`：从现有 runner 迁移，改成 Problem 页面。
- 修改 `app/static/js/question_runner.js`：改为加载 `/api/v1/problems/<problem_id>`，提交到 `/api/v1/problems/<problem_id>/submit`，支持语言切换。
- 修改 `app/templates/dashboard.html` 和 `app/static/js/dashboard.js`：改为 Problem 列表和语言下拉。
- 修改 `app/templates/teacher/teacher_questions_create.html` 和 `app/static/js/teacher_questions_create.js`：一次创建 Problem 和 Python/C 两个可选版本。
- 修改 `app/templates/teacher/teacher_questions_manage.html` 和 `app/static/js/teacher_questions_manage.js`：管理 Problem 公共信息、共享测试用例、语言版本代码。
- 修改 `app/static/js/student_quizzes.js`、`app/static/js/quizzes.js`、`app/static/js/teacher_profile.js`、`app/static/js/submissions.js` 等依赖题目 URL 或题目列表的前端。
- 修改 `app/agents/tools/question_query.py`、AI generator 发布逻辑、`GeneratedQuestionDraft` 发布字段，让 AI 生成题也落到 Problem + variants。
- 修改 `app/core/init_db.py`：将平铺 `questions_data` 改成 grouped `problems_data`。
- 修改 `tests/cypress/fixtures/**`：fixture 使用 Problem + variants 结构。
- 修改 `tests/**` pytest：测试数据先创建 Problem，再创建 Question variant 和共享 TestCase。
- 更新 `docs/API.md`、`docs/ARCHITECTURE.md`、`docs/TESTING.md`。

---

## Task 1：新增 Problem 模型和 ORM 关系

**文件：**
- 新建：`app/models/problem.py`
- 修改：`app/models/question.py`
- 修改：`app/models/quiz.py`
- 修改：`app/models/__init__.py`
- 测试：`tests/test_problem_models.py`

- [ ] **Step 1：写失败测试**

新建 `tests/test_problem_models.py`：

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

- [ ] **Step 2：运行测试确认失败**

```powershell
pytest tests/test_problem_models.py -q
```

预期：失败，因为 `Problem` 和 `QuizProblem` 还不存在。

- [ ] **Step 3：创建 `Problem` 模型**

新建 `app/models/problem.py`：

```python
from datetime import datetime

from app.core.extensions import db


class Problem(db.Model):
    """Dashboard、Quiz 和做题页展示的父级题目。"""

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

- [ ] **Step 4：修改 `Question` 和 `TestCase`**

将 `app/models/question.py` 改成：

```python
from datetime import datetime

from app.core.extensions import db


class Question(db.Model):
    """Problem 的某个语言版本。"""

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
    """Problem 级共享测试用例。"""

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

- [ ] **Step 5：用 `QuizProblem` 替换 `QuizQuestion`**

在 `app/models/quiz.py` 中，将 `quiz_questions` relationship 替换为：

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

新增：

```python
class QuizProblem(db.Model):
    """Quiz 与 Problem 的关联表。"""

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
```

- [ ] **Step 6：更新模型导出**

在 `app/models/__init__.py` 中导出：

```python
from .problem import Problem
from .quiz import Quiz, QuizProblem, ClassroomQuiz, QuizAttempt
from .question import Question, TestCase
```

移除 `QuizQuestion`。

- [ ] **Step 7：运行模型测试**

```powershell
pytest tests/test_problem_models.py -q
```

预期：全部通过。

---

## Task 2：执行彻底数据库迁移

**文件：**
- 新建：`migrations/versions/20260522_problem_variant_schema.py`

- [ ] **Step 1：创建新表和临时迁移列**

迁移文件中创建：

```python
from alembic import op
import sqlalchemy as sa


revision = "20260522_problem_variant_schema"
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
```

- [ ] **Step 2：回填并合并旧数据**

在 migration 中用 `op.get_bind()` 查询旧 `questions`。

标题归一规则：

```python
def canonical_title(title):
    title = (title or "").strip()
    for suffix in (" (C)", " (c)", " - C", " - c"):
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title
```

迁移规则：

- 同一 canonical title 创建一个 `Problem`。
- 使用该组第一条旧 Question 的 `description`、`points`、`order`、`created_by`。
- Python/C 旧 Question 都更新到同一个 `problem_id`。
- 测试用例优先使用 Python 版本旧测试用例；如果没有 Python，则使用该组第一条 Question 的测试用例。
- 被选中的测试用例更新 `problem_id`。
- 非选中语言版本的旧测试用例删除，避免共用测试用例重复。
- 旧 `quiz_questions` 按 `(quiz_id, problem_id)` 去重插入 `quiz_problems`。

slug 生成：

```python
import re


def slugify(title, fallback_id):
    base = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return base or f"problem-{fallback_id}"
```

- [ ] **Step 3：删除旧字段和旧表**

回填后执行：

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

- [ ] **Step 4：运行迁移**

```powershell
flask db upgrade
```

预期：数据库结构升级完成；旧 `questions` 字段、`test_cases.question_id` 和 `quiz_questions` 已不存在。

---

## Task 3：新增 Problem Schema 和服务层

**文件：**
- 新建：`app/services/problem_service.py`
- 修改：`app/schemas/questions_schema.py`
- 测试：`tests/test_problem_service.py`

- [ ] **Step 1：新增 schema**

在 `app/schemas/questions_schema.py` 增加：

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

- [ ] **Step 2：实现 `ProblemService`**

新建 `app/services/problem_service.py`，至少实现：

```python
class ProblemService:
    @staticmethod
    def list_public_problems(limit=100, offset=0, quiz_id=None, user_id=None):
        ...

    @staticmethod
    def get_problem_detail(problem_id, language="python", user_id=None):
        ...

    @staticmethod
    def create_problem(teacher_id, payload):
        ...

    @staticmethod
    def is_problem_completed(student_id, problem_id):
        ...
```

要求：

- `list_public_problems()` 返回一行一个 Problem。
- `default_language` 优先为 Python；没有 Python 时用第一个可用 variant。
- `completed` 通过该 Problem 下所有 variant 的提交记录计算。
- `get_problem_detail()` 根据 `language` 返回对应 starter code、solution 和共享测试用例。
- `create_problem()` 一次创建 Problem、可选 Python variant、可选 C variant、可选 quiz association。

- [ ] **Step 3：测试服务层**

```powershell
pytest tests/test_problem_service.py -q
```

预期：Problem 列表、默认语言、完成状态判断通过。

---

## Task 4：改造提交与判题流程

**文件：**
- 修改：`app/services/submission_service.py`
- 修改：`app/api/v1/submissions.py`
- 测试：`tests/test_problem_submission.py`

- [ ] **Step 1：新增 Problem 级提交方法**

在 `SubmissionService` 中添加：

```python
@staticmethod
def submit_problem_code(student_id, problem_id, language, code, time_limit_sec=2.0):
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

- [ ] **Step 2：改共享测试用例读取**

在 `submit_code()` 中，把旧逻辑：

```python
TestCase.query.filter_by(question_id=question_id)
```

改成：

```python
TestCase.query.filter_by(problem_id=question.problem_id).order_by(TestCase.id).all()
```

- [ ] **Step 3：新增 Problem 提交 API**

在 `app/api/v1/submissions.py` 中新增：

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

- [ ] **Step 4：运行提交测试**

```powershell
pytest tests/test_problem_submission.py -q
```

预期：提交 C/Python 都使用同一套 `Problem.test_cases`，但 submission 仍记录具体 `question_id`。

---

## Task 5：新增 Problem API

**文件：**
- 新建：`app/api/v1/problems.py`
- 修改：`app/__init__.py`
- 修改：`app/api/public/metrics.py`
- 测试：`tests/test_api_problems.py`

- [ ] **Step 1：创建 Problem API**

新建 `app/api/v1/problems.py`：

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

- [ ] **Step 2：注册 blueprint**

在 `app/__init__.py` 中注册：

```python
from app.api.v1.problems import blp as problems_blp
api.register_blueprint(problems_blp)
```

- [ ] **Step 3：更新 metrics**

`app/api/public/metrics.py` 中题目数量使用：

```python
Problem.query.count()
```

而不是 `Question.query.count()`。

- [ ] **Step 4：运行 API 测试**

```powershell
pytest tests/test_api_problems.py -q
```

预期：`GET /api/v1/problems` 返回 Problem 列表和 variants，`GET /api/v1/problems/<id>?language=c` 返回 C 版本 starter code。

---

## Task 6：改造 Dashboard

**文件：**
- 修改：`app/templates/dashboard.html`
- 修改：`app/static/js/dashboard.js`
- 修改：`app/static/css/dashboard.css`
- 测试：`tests/cypress/e2e/dashboard_problems.cy.js`

- [ ] **Step 1：Dashboard API 改成 Problem**

在 `app/static/js/dashboard.js` 中将：

```javascript
let apiUrl = `${API_PUBLIC}/questions?limit=1000&offset=0`;
```

改成：

```javascript
let apiUrl = `${API_PUBLIC}/problems?limit=1000&offset=0`;
```

- [ ] **Step 2：一行渲染一个 Problem**

渲染规则：

- 标题显示 `problem.title`。
- 难度显示 `problem.difficulty`。
- 语言列渲染 `<select>`。
- 行点击进入 `/problem/<id>?language=python`。
- 语言下拉选择后进入 `/problem/<id>?language=<selected>`。

核心代码：

```javascript
tr.dataset.problemRow = String(problem.id);
tr.onclick = (event) => {
    if (event.target.closest('select')) return;
    window.location.href = `/problem/${problem.id}?language=python`;
};
```

语言下拉：

```javascript
<select class="form-select form-select-sm problem-language-select" data-problem-language="${problem.id}">
  ${options}
</select>
```

- [ ] **Step 3：更新 Dashboard 测试**

新增或修改 Cypress 测试，确认：

```text
Dashboard 只显示一行 Add Two Numbers。
语言下拉默认 Python。
点击整行进入 /problem/1?language=python。
选择 C 进入 /problem/1?language=c。
```

- [ ] **Step 4：运行 Cypress**

```powershell
npx cypress run --spec tests/cypress/e2e/dashboard_problems.cy.js
```

---

## Task 7：用 Problem Runner 替换 Question Runner

**文件：**
- 修改：`app/web/question.py`
- 新建：`app/templates/problem_runner.html`
- 修改：`app/static/js/question_runner.js`
- 修改所有前端 `/question/` 链接
- 测试：`tests/cypress/e2e/student/question_runner.cy.js`

- [ ] **Step 1：替换路由**

`app/web/question.py`：

```python
from flask import Blueprint, abort, render_template, request

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

不要再定义 `/question/<int:question_id>`。

- [ ] **Step 2：新建 `problem_runner.html`**

从当前 `question_runner.html` 迁移布局，关键数据改为：

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
></textarea>
```

- [ ] **Step 3：修改 runner JS**

将上下文改成：

```javascript
const PROBLEM_ID = Number(codeEl?.dataset?.problemId || 0);
let LANG = String(codeEl?.dataset?.language || "python").toLowerCase();

const API_SUBMIT = (id) => `/api/v1/problems/${id}/submit`;
const API_PROBLEM = (id, language) => `/api/v1/problems/${id}?language=${encodeURIComponent(language)}`;
```

提交 payload：

```javascript
const payload = {
  code: code,
  language: LANG,
  time_limit_sec: tlimit
};
```

语言切换：

```javascript
document.getElementById("problemLanguageSelect").addEventListener("change", (e) => {
  window.location.href = `/problem/${PROBLEM_ID}?language=${encodeURIComponent(e.target.value || "python")}`;
});
```

- [ ] **Step 4：更新链接**

把所有：

```text
/question/<id>
```

改成：

```text
/problem/<problem_id>?language=python
```

提交历史中带语言：

```javascript
`/problem/${item.problem_id}?language=${encodeURIComponent(item.language || 'python')}`
```

- [ ] **Step 5：运行 runner 测试**

```powershell
npx cypress run --spec tests/cypress/e2e/student/question_runner.cy.js
```

---

## Task 8：重写初始化数据

**文件：**
- 修改：`app/core/init_db.py`

- [ ] **Step 1：替换 import**

```python
from app.models.problem import Problem
from app.models.quiz import Quiz, QuizProblem, ClassroomQuiz
from app.models.question import Question, TestCase
```

- [ ] **Step 2：将 `questions_data` 改成 `problems_data`**

结构：

```python
problems_data = [
    {
        "quiz": quizzes[0],
        "slug": "add-two-numbers",
        "title": "Add Two Numbers",
        "description": "Read two integers from input and output their sum.",
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
                "solution_explanation": "Use scanf to read two integers and print their sum.",
            },
        },
    },
]
```

- [ ] **Step 3：按 Problem 创建数据**

创建顺序：

```text
Problem
QuizProblem
TestCase(problem_id)
Question(problem_id, language)
```

核心循环：

```python
for p_data in problems_data:
    problem = Problem(...)
    db.session.add(problem)
    db.session.flush()

    db.session.add(QuizProblem(...))

    for input_data, expected, is_hidden, weight in p_data["test_cases"]:
        db.session.add(TestCase(problem_id=problem.id, ...))

    for language, variant_data in p_data["variants"].items():
        db.session.add(Question(problem_id=problem.id, programming_language=language, ...))
```

- [ ] **Step 4：更新 seed 验证输出**

输出：

```text
Problems
Language variants
QuizProblem associations
Shared test cases
```

- [ ] **Step 5：运行 seed**

```powershell
python -m app.core.init_db --drop --seed --force
```

预期：旧数据被清空，新数据按 Problem + Python/C variants 创建。

---

## Task 9：改造教师端创建与管理

**文件：**
- 修改：`app/templates/teacher/teacher_questions_create.html`
- 修改：`app/static/js/teacher_questions_create.js`
- 修改：`app/templates/teacher/teacher_questions_manage.html`
- 修改：`app/static/js/teacher_questions_manage.js`
- 修改：`app/web/teacher.py`
- 测试：`tests/cypress/e2e/teacher/questions.cy.js`

- [ ] **Step 1：教师端创建页改成 Problem 创建**

保留 `/teacher/questions/create` 作为导航入口，但页面语义改成创建 Problem。

表单包含：

```text
Problem title
description
difficulty
points
order
quiz
Python starter code
Python solution
Python solution explanation
C starter code
C solution
C solution explanation
```

Python/C 代码字段可以为空。

- [ ] **Step 2：创建 payload**

`teacher_questions_create.js` 提交：

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
```

提交到：

```javascript
`${API_BASE}/problems`
```

- [ ] **Step 3：管理页改成 Problem 管理**

管理页路由：

```text
/teacher/problems/<problem_id>/manage
```

页面结构：

```text
左侧：Problem 公共信息
中间/右侧：Python/C 语言 tab，编辑 starter code 和 solution
右侧：共享测试用例列表和添加表单
```

测试用例 API 必须是 Problem 级：

```text
POST /api/v1/problems/<problem_id>/test-cases
DELETE /api/v1/test-cases/<tc_id>
```

- [ ] **Step 4：运行教师端测试**

```powershell
npx cypress run --spec tests/cypress/e2e/teacher/questions.cy.js
```

---

## Task 10：改造 Quiz 和学生 Quiz 视图

**文件：**
- 修改：`app/services/quiz_service.py`
- 修改：`app/api/v1/quizzes.py`
- 修改：`app/schemas/quiz_schema.py`
- 修改：`app/static/js/quizzes.js`
- 修改：`app/static/js/student_quizzes.js`

- [ ] **Step 1：Quiz 服务改成 Problem**

新增：

```python
add_problem_to_quiz(quiz_id, problem_id, order=None, points=10)
remove_problem_from_quiz(quiz_id, problem_id)
update_quiz_problem(quiz_id, problem_id, order=None, points=None)
```

全部使用 `QuizProblem`。

- [ ] **Step 2：Quiz detail 返回 `problems`**

返回结构：

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

- [ ] **Step 3：完成状态按 Problem 计算**

某个 Problem 下任一 variant 有 `status == "completed"` 且 `score >= 100`，该 Problem 完成。

- [ ] **Step 4：更新前端**

学生 Quiz 页面按钮：

```javascript
<a href="/problem/${problem.id}?language=python">
```

教师 Quiz 管理接口：

```text
POST /api/v1/quizzes/<quiz_id>/problems
DELETE /api/v1/quizzes/<quiz_id>/problems/<problem_id>
```

- [ ] **Step 5：运行 Quiz 测试**

```powershell
npx cypress run --spec tests/cypress/e2e/teacher/quizzes.cy.js,tests/cypress/e2e/student/quizzes.cy.js
```

---

## Task 11：更新 AI 工具和生成题发布

**文件：**
- 修改：`app/agents/tools/question_query.py`
- 修改：`app/agents/agents/generator.py`
- 修改：`app/api/v1/ai.py`
- 修改：`app/models/generated_question_draft.py`
- 测试：`tests/test_tools.py`
- 测试：`tests/test_agents.py`
- 测试：`tests/test_api_ai.py`

- [ ] **Step 1：question query tool 解析 parent problem**

旧的 `question_id` 作为 variant ID 使用：

```python
q = Question.query.get(question_id)
problem = q.problem if q else None
cases = TestCase.query.filter_by(problem_id=problem.id, is_hidden=False).all()
```

返回：

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

- [ ] **Step 2：AI 生成题发布为 Problem**

生成题发布逻辑改成：

```text
Problem
Question variant
Problem-level TestCase
```

如果 AI 只生成一个语言版本，就只创建一个 variant；如果生成 Python/C 两个版本，则创建两个 variant。

- [ ] **Step 3：更新 GeneratedQuestionDraft**

保留 `published_question_id` 指向默认发布 variant，并新增：

```text
published_problem_id
```

用于 review queue 跳转 `/problem/<problem_id>`。

- [ ] **Step 4：运行 AI 相关测试**

```powershell
pytest tests/test_tools.py tests/test_agents.py tests/test_api_ai.py -q
```

---

## Task 12：更新提交列表、Profile、Grades 和统计

**文件：**
- 修改：`app/services/submission_service.py`
- 修改：`app/api/v1/grades.py`
- 修改：`app/services/teacher_stats_service.py`
- 修改：`app/static/js/submissions.js`
- 修改：`app/static/js/submission_detail.js`
- 修改：`app/static/js/student_profile.js`
- 修改：`app/static/js/teacher_profile.js`

- [ ] **Step 1：提交列表返回 problem metadata**

`SubmissionService.get_student_submissions()` 返回：

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

- [ ] **Step 2：前端链接改成 Problem**

```javascript
`/problem/${item.problem_id}?language=${encodeURIComponent(item.language || 'python')}`
```

- [ ] **Step 3：教师统计按 Problem 统计**

```python
Problem.query.filter_by(created_by=teacher_id).count()
```

- [ ] **Step 4：成绩筛选按 Problem**

后端将 `problem_id` 映射到 variants：

```python
variant_ids = select(Question.id).where(Question.problem_id == problem_id)
query = query.filter(Submission.question_id.in_(variant_ids))
```

- [ ] **Step 5：运行相关 Cypress**

```powershell
npx cypress run --spec tests/cypress/e2e/student/profile.cy.js,tests/cypress/e2e/teacher/profile.cy.js,tests/cypress/e2e/teacher/grades.cy.js
```

---

## Task 13：更新 Cypress fixtures 和 E2E

**文件：**
- 修改：`tests/cypress/fixtures/student/*.json`
- 修改：`tests/cypress/fixtures/teacher/*.json`
- 修改：`tests/cypress/e2e/**/*.cy.js`

- [ ] **Step 1：fixture 改成 Problem 结构**

示例：

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

- [ ] **Step 2：路由断言更新**

把 `/question/` 断言改成：

```javascript
cy.location("pathname").should("match", /^\/problem\/\d+$/);
```

- [ ] **Step 3：完成状态断言更新**

Quiz 和 Dashboard 都按 Problem 完成状态断言，任一语言通过即完成。

- [ ] **Step 4：运行完整 Cypress**

```powershell
npx cypress run
```

---

## Task 14：更新项目文档

**文件：**
- 修改：`docs/API.md`
- 修改：`docs/ARCHITECTURE.md`
- 修改：`docs/TESTING.md`
- 修改：`README.md`

- [ ] **Step 1：更新架构说明**

写清楚：

```text
Problem 是公开练习单位。
Question 是可执行语言版本。
TestCase 属于 Problem，并被所有语言版本共享。
Submission 属于 Question，用于保留语言维度。
QuizProblem 连接 Quiz 和 Problem。
```

- [ ] **Step 2：更新 API 文档**

新增：

```text
GET /api/v1/problems
GET /api/v1/problems/{problem_id}?language=python
POST /api/v1/problems/{problem_id}/submit
POST /api/v1/problems
PATCH /api/v1/problems/{problem_id}
POST /api/v1/problems/{problem_id}/test-cases
```

删除用户可见 `/question/<question_id>` 说明。

- [ ] **Step 3：更新测试说明**

记录 seed 命令：

```powershell
python -m app.core.init_db --drop --seed --force
```

并说明 seed 创建的是 grouped Problem + Python/C variants。

---

## Task 15：完整验证

- [ ] **Step 1：重建并初始化数据库**

```powershell
python -m app.core.init_db --drop --seed --force
```

预期：

```text
Problems 创建成功
Python/C variants 创建成功
共享 TestCases 创建成功
QuizProblem associations 创建成功
```

- [ ] **Step 2：运行后端测试**

```powershell
pytest -q
```

预期：全部通过。

- [ ] **Step 3：运行 Cypress**

```powershell
npx cypress run
```

预期：全部通过。

- [ ] **Step 4：手工浏览器验收**

验收点：

```text
/dashboard 一行显示一道 Problem。
Dashboard 语言下拉默认 Python。
点击 Dashboard 行进入 /problem/<id>?language=python。
选择 C 进入 /problem/<id>?language=c。
Problem Runner 两个语言使用同一套测试用例。
提交 Python 或 C 都能记录到对应 variant。
任一语言 AC 后，该 Problem 算完成。
教师端一次创建 Problem，并可填写 Python/C 两套代码。
Quiz 中同一道 Problem 只出现一次。
前端没有可见 /question/<question_id> 链接。
```

---

## 自查结论

- 覆盖范围：数据库、模型、迁移、API、Dashboard、Problem Runner、教师端、Quiz、AI 工具、seed、测试和文档都已覆盖。
- 决策一致性：文档严格采用“彻底迁移、不保留旧 URL、不保留旧 test_cases.question_id、不保留 quiz_questions、Problem 级测试用例”的方案。
- 执行边界：本文件是执行方案，不包含实际业务代码改动；真正实施时应逐 Task 执行并在每个阶段跑对应测试。

