# 系统架构

> 最后更新: 2026-05-28

CodeRunner 是一个面向编程教学的在线评测平台。本文档描述系统分层、请求流、领域模型与数据库结构。

---

## 一、技术栈

| 层 | 技术 | 版本 |
|---|---|---|
| Web 框架 | Flask | 3.1 |
| ORM | SQLAlchemy | 2.0 |
| 数据库 | MySQL | 8.0 |
| API 框架 | flask-smorest（OpenAPI 3.0.3 + Swagger UI） | 0.46 |
| 认证 | Flask-Login + PyJWT | - |
| 模板 | Jinja2 | 3.1 |
| 数据库迁移 | Flask-Migrate / Alembic | 4.1 |
| WSGI Server | Gunicorn（4 workers） | 21.2 |
| 容器 | Docker + docker-compose | - |
| 前端编辑器 | CodeMirror | 5.65 |
| E2E 测试 | Cypress | 13.17 |

后端零业务依赖第三方库（沙箱使用 `subprocess` + Python 标准库 `resource` 模块自实现）。

> **AI Agent 模块**（规划中）将引入 `anthropic` + `langgraph` + `redis` 实现多 Agent 编排，详见 [ai-agents.md](ai-agents.md)。

---

## 二、分层结构

```
┌────────────────────────────────────────────────────┐
│  Web (Jinja2 templates) │  REST API (flask-smorest) │
│  app/web/, app/templates│  app/api/v1, app/api/public│
├────────────────────────────────────────────────────┤
│              Auth Layer (decorators)                │
│  app/auth/decorators.py     (API: JSON 401/403)     │
│  app/auth/web_decorators.py (Web: redirect to login)│
├────────────────────────────────────────────────────┤
│                  Service Layer                      │
│  app/services/  (业务逻辑，不直接处理 HTTP)         │
├────────────────────────────────────────────────────┤
│           Data / Schema / Executor Layer            │
│  app/models/   (SQLAlchemy ORM)                     │
│  app/schemas/  (Marshmallow 校验)                   │
│  app/core/executor.py      (本地沙箱)               │
│  app/core/executor_client.py(远程沙箱)              │
├────────────────────────────────────────────────────┤
│                  AI Agent Layer                     │
│  agents/                (Tutor/Reviewer/Generator/Analytics) │
│  graph/                 (LangGraph 编排: engine/planner/runner) │
│  memory/                (短期/长期 + preference)    │
│  knowledge/             (RAG 向量库 store)          │
│  models/                (LLM router + providers)    │
│  tools/                 (业务工具实现 + protocol/ 协议层) │
│  mcp_gateway/           (FastMCP 对外服务)          │
│  workers/               (chat/batch/task_runner 守护进程) │
│  core/                  (config/db/auth/observability) │
└────────────────────────────────────────────────────┘
```

> 详细顶层目录布局见根目录 [README.md](../../README.md) 与 [ai-agents.md](ai-agents.md)。

### 模块职责

| 路径 | 职责 |
|---|---|
| `app/__init__.py` | App factory `create_app()`，按环境注入配置，注册所有蓝图 |
| `app/core/config.py` | 三套配置：Development / Production / Testing，从 env 读 DSN |
| `app/core/extensions.py` | SQLAlchemy / Migrate / Flask-Login / flask-smorest 初始化 |
| `app/core/executor.py` | 本地代码沙箱（subprocess + resource limits）|
| `app/core/executor_client.py` | 远程沙箱客户端（HTTP POST 到 `EXECUTOR_REMOTE_URL`）|
| `app/core/init_db.py` | 数据库 seed 脚本（admin / 3 teachers / 8 students / 5 classrooms）|
| `app/api/v1/*` | 受保护 REST API（auth / classrooms / quizzes / questions / submissions / grades / judge / profile / teacher_stats）|
| `app/api/public/*` | 公开 REST API（health / questions 浏览 / quizzes 公开列表）|
| `app/auth/decorators.py` | API 装饰器：`require_auth / require_role / require_teacher / require_student` |
| `app/auth/web_decorators.py` | Web 装饰器：`web_login_required / web_*_required`（未登录自动跳转）|
| `app/auth/utils.py` | 密码 hash + JWT 签发 / 校验 |
| `app/services/*` | 业务逻辑层（auth / classroom / quiz / question / submission / executor / profile / teacher_stats）|
| `app/models/*` | ORM 模型（user / classroom / quiz / question / submission）|
| `app/schemas/*` | Marshmallow 输入输出校验 schema |
| `app/web/*` | 前台 Jinja2 路由（main / auth / student / teacher / question / submissions）|
| `app/templates/*` | Jinja2 模板（按角色目录组织：public / auth / student / teacher）|
| `app/utils/pagination.py` | 通用分页工具 |

### 蓝图（Blueprint）注册

`app/__init__.py:register_blueprints()` 集中注册所有蓝图。当前共 **17 个蓝图**：

```
REST API（受保护）  : auth / classrooms / quizzes / questions / submissions
                     / grades / judge / teacher_stats / teacher_students
                     / user_profile
REST API（公开）    : public / public_quizzes / health / public_questions
Web                  : main / auth / student / teacher / question / submissions
```

---

## 三、请求流

### 1. Web 请求（HTML 页面）

```
Browser
  → GET /student/profile
  → @web_student_required (web_decorators.py)
      ├─ 检查 Flask-Login session
      ├─ 检查 Cookie auth_token (JWT)
      ├─ 检查 Authorization header (Bearer JWT)
      ├─ 任一通过 → g.current_user 注入
      └─ 全失败 → redirect /auth/login?next=/student/profile
  → app/web/student.py 路由处理
  → render_template('student/profile.html', user=g.current_user)
```

### 2. REST API 请求（JSON）

```
Client
  → POST /api/v1/quizzes
  → @blp.arguments(QuizCreateSchema)         # Marshmallow 入参校验
  → @require_teacher                          # decorators.py
      ├─ 同样三层认证检查（Session / Cookie / Header）
      ├─ 校验 role ∈ {teacher, admin}
      ├─ 失败 → JSON 401/403
      └─ 通过 → g.current_user 注入
  → app/api/v1/quizzes.py 路由
  → app/services/quiz_service.py 业务逻辑
  → app/models/quiz.py ORM 写库
  → @blp.response(201, QuizOutSchema)        # Marshmallow 出参序列化
  → JSON 201
```

### 3. 代码评测请求

```
Browser (CodeMirror)
  → POST /api/v1/judge/run  { code, language, input, expected_output, time_limit_sec }
  → CodeRunInputSchema 校验
  → app/services/executor_service.py: ExecutorService.run_code()
      ├─ 若 EXECUTOR_REMOTE_URL → executor_client.run_code_remote() (HTTP)
      └─ 否则 → app/core/executor.py: CodeExecutor.run_code()
              ├─ Python: subprocess.run([python3, main.py], timeout, preexec_fn=resource limits)
              └─ C:     gcc -std=c11 -O2 → ./main (同上)
  → 输出归一化（rstrip 行尾、去尾空行）→ 与 expected_output 比对
  → 状态：AC / WA / CE / RE / TLE / SYSTEM_ERROR
  → JSON 返回 { status, passed, stdout, stderr, time_ms, compile_log }
```

代码沙箱设计详见 [executor.md](executor.md)。

---

## 四、领域模型

### ER 关系图（文字版）

```
User (admin / teacher / student)
  ├── 1:N → Classroom (作为 teacher)
  ├── M:N → Classroom (作为 student，通过 Enrollment)
  ├── 1:N → Quiz (作为 creator)
  ├── 1:N → ClassroomQuiz (作为 assigner)
  ├── 1:N → QuizAttempt
  └── 1:N → Submission

Classroom
  ├── N:1 → User (teacher)
  ├── 1:N → Enrollment
  └── 1:N → ClassroomQuiz

Quiz
  ├── N:1 → User (creator)
  ├── 1:N → QuizProblem (有 order + 可覆盖默认 points)
  ├── 1:N → ClassroomQuiz (一份 quiz 可分配到多个班级)
  └── 1:N → QuizAttempt

Problem
  ├── 1:N → Question (Python/C 等语言变体)
  ├── 1:N → TestCase (input / expected_output / is_hidden / weight)
  └── 1:N → QuizProblem

Question
  └── 1:N → Submission

Submission
  ├── N:1 → User (student)
  ├── N:1 → Question
  └── 1:N → TestResult (passed / actual_output / execution_time)

ClassroomQuiz (作业分配，含 due_date / allow_late_submission)
  ├── N:1 → Classroom
  ├── N:1 → Quiz
  └── 1:N → QuizAttempt
```

### 关键设计决策

1. **关联表都是显式实体**（不是隐式 secondary）：`Enrollment / QuizProblem / ClassroomQuiz` 都有自己的 `id`、时间戳、附加字段（如 `QuizProblem.order/points` 可覆盖 `Problem` 默认值）。
2. **角色枚举**：`UserRole = STUDENT / TEACHER / ADMIN`，落库为 MySQL ENUM。
3. **唯一约束**：`(student_id, classroom_id)` 不重复入班、`(quiz_id, problem_id)` 不重复加题、`(problem_id, programming_language)` 不重复建同语种变体、`(classroom_id, quiz_id)` 不重复布置。
4. **级联删除**：`Classroom → Enrollment`、`Quiz → QuizProblem / ClassroomQuiz`、`Problem → Question / TestCase / QuizProblem`、`Submission → TestResult` 全部 `cascade='all, delete-orphan'`。
5. **测试用例隐藏**：`TestCase.is_hidden` 控制学生侧能否看到。`ProblemService.get_problem_detail()` 默认隐藏参考解，只有有提交记录时返回当前语言变体的 solution。
6. **评测状态字符串**：`Submission.status` 用 `pending / running / completed / error`；测试结果细分 `AC / WA / CE / RE / TLE`（来自 `TestResult` 与 executor 输出）。

### 数据表清单

| 表 | 主要字段 |
|---|---|
| `users` | id, username (unique), password (bcrypt), email, role, created_at |
| `classrooms` | id, name, code (unique 邀请码), description, teacher_id |
| `enrollments` | id, student_id, classroom_id, enrolled_at（unique student+classroom）|
| `quizzes` | id, title, description, created_by, duration_minutes, is_published |
| `quiz_problems` | id, quiz_id, problem_id, order, points（unique quiz+problem）|
| `classroom_quizzes` | id, classroom_id, quiz_id, due_date, allow_late_submission, assigned_by |
| `quiz_attempts` | id, quiz_id, student_id, classroom_quiz_id, started_at, completed_at, status, score, max_score |
| `problems` | id, slug, title, description, difficulty, points, order, created_by |
| `questions` | id, problem_id, programming_language, starter_code, solution, solution_explanation |
| `test_cases` | id, problem_id, input, expected_output, is_hidden, weight |
| `submissions` | id, student_id, question_id, code, score, status, error_message, execution_time, memory_used |
| `test_results` | id, submission_id, test_case_id, passed, actual_output, error_message, execution_time |

完整 schema 见 `migrations/versions/`（Alembic）和 `docker/init.sql`（容器引导）。

---

## 五、配置真源

### 环境变量入口

| 变量 | 用途 |
|---|---|
| `FLASK_ENV` | `development` / `production` / `testing` |
| `SECRET_KEY` | Flask session + JWT 签名密钥 |
| `DATABASE_URL` | 完整 DSN（优先）|
| `MYSQL_USER / MYSQL_PASSWORD / MYSQL_HOST / MYSQL_PORT / MYSQL_DATABASE` | 拼装 DSN（备选）|
| `EXECUTOR_REMOTE_URL` | 远程沙箱 URL；不设则走本地 |
| `EXECUTOR_API_TOKEN` | 远程沙箱 `X-EXECUTOR-TOKEN` |
| `EXECUTOR_TMP_DIR` | 沙箱临时目录（默认 `/tmp/executor`）|
| `EXECUTOR_MAX_MEMORY_MB` | 沙箱内存上限（默认 256）|
| `EXECUTOR_MAX_CPU_TIME` | 沙箱 CPU 时间上限（默认 10s）|
| `EXECUTOR_DEFAULT_TIMEOUT` | 沙箱默认 wall-clock 超时（默认 2.0s）|
| `EXECUTOR_MAX_STDOUT / STDERR` | 输出截断长度（10000 / 4000 字节）|

### 三套 Flask 配置

```python
DevelopmentConfig: DEBUG=True, SQLALCHEMY_ECHO=True
ProductionConfig:  DEBUG=False, SQLALCHEMY_ECHO=False
TestingConfig:     SQLite in-memory（用于 pytest）
```

连接池配置：`pool_size=10`、`pool_recycle=3600`、`pool_pre_ping=True`。

---

## 六、容器化

### 服务拓扑

```
docker-compose.yml
├── db        : mysql:8.0  (port 3306, volume mysql_data, init.sql 引导)
└── web       : 自构建      (port 9900, gunicorn 4 workers, healthcheck)
              ├── 依赖 db: condition: service_healthy
              ├── volume: app/ (ro mount), uploads/, logs/, /tmp/executor
              └── env: 从 ../.env 读取
```

### Dockerfile 关键点

- 基础镜像 `python:3.11-slim`
- 系统包：`gcc / g++ / make / build-essential / default-mysql-client`（沙箱要 gcc 编译 C 代码）
- 创建非 root `appuser` (uid 1000)，`gosu appuser` 启动 gunicorn
- HEALTHCHECK：`curl -f /health` 每 30s，超时 10s，失败 3 次降级
- 入口：`docker/entrypoint.sh` 处理初始化（等待 db、可选 seed）

---

## 七、目录速查

```
CodeRunner/
├── app/
│   ├── __init__.py            # create_app() + 蓝图注册
│   ├── core/                  # 配置、扩展、沙箱、初始化脚本
│   ├── auth/                  # 装饰器（API + Web）+ JWT/密码工具
│   ├── api/
│   │   ├── public/            # 公开 endpoints (health / questions / quizzes / metrics)
│   │   └── v1/                # 受保护 endpoints (10 个蓝图)
│   ├── models/                # ORM (user / classroom / quiz / question / submission)
│   ├── schemas/               # Marshmallow 输入输出校验
│   ├── services/              # 业务逻辑层 (8 个 service)
│   ├── web/                   # Jinja2 路由 (main / auth / student / teacher / question / submissions)
│   ├── templates/             # 按角色组织的 HTML 模板
│   ├── static/                # CSS + JS (CodeMirror)
│   └── utils/                 # 通用工具（分页等）
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── entrypoint.sh
│   └── init.sql
├── migrations/                # Alembic 迁移
├── tests/cypress/             # E2E 测试 (11 spec / 多 fixture)
├── docs/                      # 本文档
├── requirements.txt
├── package.json
├── run.py                     # gunicorn 入口
└── README.md
```

---

## 八、相关文档

- AI Agent 模块设计：[ai-agents.md](ai-agents.md)
- AI API 端点参考：[../api/ai-api.md](../api/ai-api.md)
- 认证机制详细设计：[auth.md](auth.md)
- 代码沙箱实现：[executor.md](executor.md)
- REST API 参考：[../api/rest-api.md](../api/rest-api.md)
- 部署：[../guides/installation.md](../guides/installation.md)
- 测试：[../validation/testing.md](../validation/testing.md)
## Current Problem Variant Model

The question bank is now grouped around a parent `Problem`:

- `Problem` is the public practice unit shown on the dashboard, quiz pages, teacher workspace, and `/problem/{problem_id}` runner.
- `Question` is an executable language variant for a parent problem. It owns `programming_language`, `starter_code`, `solution`, and `solution_explanation`.
- `TestCase` belongs to `Problem`, so Python and C variants share the same visible and hidden tests.
- `Submission` still belongs to `Question`, preserving language-specific history and executor routing.
- `QuizProblem` links quizzes to parent problems. Completion is problem-level: any accepted variant can mark the Problem complete.

Current core tables:

| Table | Primary role |
|---|---|
| `problems` | title, slug, description, difficulty, points, order, created_by |
| `questions` | problem_id, programming_language, starter_code, solution |
| `test_cases` | problem_id, input, expected_output, is_hidden, weight |
| `quiz_problems` | quiz_id, problem_id, order, points |
| `submissions` | student_id, question_id, code, score, status |
| `test_results` | submission_id, test_case_id, pass/fail detail |
