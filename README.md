# CodeRunner-AI

> AI-Enhanced Online Code Assessment Platform

面向编程教学的智能在线评测平台。在 CodeRunner 代码评测引擎基础上，集成 AI Agent 能力 —— 智能辅导（AI Tutor）、代码审查（AI Code Review）、自动出题（AI Question Generator）与学习分析（AI Analytics），为学生提供个性化编程学习体验，为教师减负增效。

基于 UNSW COMP9900 CodeRunner 项目演进，融合 LangGraph + LLM 构建多 Agent 系统。

---

## 工程亮点

| 子系统 | 关键实现 |
|---|---|
| **代码沙箱** | 三档 fallback（远程 HTTP / 本地 native / 旧 Docker 兼容）；Linux `RLIMIT_CPU/AS/FSIZE` 资源约束；wall-clock + CPU 双层超时；输出归一化（行尾 / 转义 / 尾空行）；标准 OJ 状态码 `AC/WA/CE/RE/TLE/SYSTEM_ERROR`。详见 [docs/EXECUTOR.md](docs/EXECUTOR.md) |
| **双轨认证** | 同一套登录态服务网页（Flask-Login session）和 API（JWT in Cookie + Authorization header），三源 token 解析（session → header → cookie），未认证时网页 302 / API 401 区分响应。详见 [docs/AUTH.md](docs/AUTH.md) |
| **RBAC** | 5 个细粒度装饰器（`require_auth / require_role / require_teacher / require_student / require_admin`）配合 Web 镜像版（`web_*_required`），权限层叠（teacher 可访问 student 接口）|
| **领域模型** | Problem 作为公开练习单元，Question 作为语言变体；显式关联实体（`Enrollment / QuizProblem / ClassroomQuiz` 各自带主键与附加字段）/ 全表级联删除策略 / 唯一约束防重复入班、重复加题、重复布置 |
| **REST API 设计** | flask-smorest 自动生成 OpenAPI 3.0.3 + Swagger UI；Marshmallow schema 双向校验；按 `/api/v1` (受保护) 与 `/api/public` (公开) 分层；17 个蓝图集中注册 |
| **容器化部署** | docker-compose 双容器（Flask + MySQL）；非 root `appuser` 启动 gunicorn 4 workers；HEALTHCHECK 自愈；MySQL 健康依赖；卷分离（数据 / 日志 / 上传 / 沙箱临时）|
| **E2E 测试** | Cypress 11 个 spec 覆盖游客 / 学生 / 教师全流程；happy path + 失败场景（500 兜底、认证守卫、表单校验、CSV 导出失败、删除重试）；fixture 与 mock 分层。详见 [docs/TESTING.md](docs/TESTING.md) |

---

## 技术栈

| 类别 | 技术 |
|---|---|
| 后端 | Flask 3.1 + SQLAlchemy 2.0 + flask-smorest（OpenAPI）+ Flask-Login + PyJWT + Marshmallow + Flask-Migrate (Alembic) |
| 数据库 | MySQL 8.0（utf8mb4，`pool_size=10`、`pool_pre_ping=True`）|
| WSGI | Gunicorn 21.2，4 workers，120s timeout |
| 前端 | Jinja2 + HTML5 + CSS3 + Vanilla JS + CodeMirror 5.65 |
| 容器 | Docker 24+ / docker-compose v2 / Python 3.11-slim |
| 测试 | Cypress 13.17 (E2E) + Faker.js fixture |
| 部署目标 | 本地 docker-compose；远程沙箱可选（如 Render） |

后端**零业务依赖外部库**：沙箱完全用 `subprocess` + Python 标准库 `resource` 模块自实现，未引入第三方 OJ 框架。

---

## 项目规模

- **10,262 行 Python / 65 文件**
- 17 蓝图（10 受保护 API + 4 公开 API + 6 Web 路由）
- 11 张数据表
- 11 个 Cypress spec + 多份 fixture
- 8 service 层模块 / 5 ORM 模型 / 8 schema 模块

---

## 快速开始

```bash
# 1. 启动（首次会构建镜像）
docker compose up -d --build
sleep 30

# 2. 初始化数据库 + 注入示例数据
docker compose exec web \
  python -m app.core.init_db --drop --seed

# 3. 打开浏览器
open http://localhost:9900
```

默认账号：

```
教师：teacher1 / admin123    （teacher1-3）
学生：student1 / admin123    （student1-8）
```

完整部署 / 配置 / 故障排查见 [docs/INSTALLATION.md](docs/INSTALLATION.md)。

---

## 关键路径

| URL | 用途 |
|---|---|
| http://localhost:9900 | 主页 |
| http://localhost:9900/auth/login | 登录 |
| http://localhost:9900/dashboard | 用户 dashboard |
| http://localhost:9900/teacher/questions/create | 教师题库 / Problem 创建与管理入口 |
| http://localhost:9900/teacher/classrooms | 教师班级 |
| http://localhost:9900/swagger-ui | API 交互文档 |
| http://localhost:9900/health | 健康检查 |

---

## 项目结构

```
CodeRunner/
├── compose.yaml
├── app/
│   ├── __init__.py            # create_app() 工厂 + 17 蓝图注册
│   ├── core/                  # config / extensions / executor / executor_client / init_db
│   ├── auth/                  # decorators (API/Web 双轨) + utils (JWT/密码)
│   ├── api/
│   │   ├── public/            # 公开 API（health / quizzes / metrics）
│   │   └── v1/                # 受保护 API（auth / classrooms / quizzes / problems /
│   │                          #              submissions / grades / judge / profile /
│   │                          #              teacher_stats / teacher_students / user_profile）
│   ├── models/                # ORM (user / classroom / quiz / problem / question / submission)
│   ├── schemas/               # Marshmallow 8 个 schema 模块
│   ├── services/              # 业务逻辑层（auth / classroom / quiz / problem / question /
│   │                          #              submission / executor / profile / teacher_stats）
│   ├── web/                   # Jinja2 路由（main / auth / student / teacher /
│   │                          #              question / submissions）
│   ├── templates/             # 按角色组织的 HTML 模板
│   ├── static/                # CSS + JS（CodeMirror）
│   └── utils/                 # 通用工具（pagination 等）
├── docker/
│   ├── Dockerfile
│   ├── entrypoint.sh
│   └── init.sql
├── migrations/                # Alembic 迁移
├── tests/cypress/             # E2E 测试
├── docs/                      # 架构 / 认证 / 沙箱 / API / 部署 / 测试 文档
├── requirements.txt
├── package.json
├── run.py
└── README.md
```

---

## 文档

| 文档 | 内容 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 分层架构、请求流、领域模型、数据库结构 |
| [docs/AUTH.md](docs/AUTH.md) | 双轨认证、JWT 设计、RBAC、密码存储 |
| [docs/EXECUTOR.md](docs/EXECUTOR.md) | 代码沙箱设计、resource limits、状态码 |
| [docs/API.md](docs/API.md) | REST API 参考（按模块） |
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | 部署 / 配置 / 数据库 / 故障排查 |
| [docs/TESTING.md](docs/TESTING.md) | Cypress 套件结构与运行 |

---

## 当前已知限制

- 沙箱不阻断网络（仅在远程 executor 部署模式下通过 VPC 隔离）
- 没有 syscall 级过滤（seccomp / AppArmor），fork bomb 仅靠 wall-clock 兜底
- 一次评测仅支持单文件源码，无多文件 / Makefile 项目
- 注册接口允许直接选择 `teacher` 角色（教学环境约定，生产场景需改邀请码 / 审批流）
- Cookie `secure=False` 默认；生产部署必须改 `True` 并跑在 HTTPS 后

详细分析见 [docs/EXECUTOR.md](docs/EXECUTOR.md) 与 [docs/AUTH.md](docs/AUTH.md) 的"已知限制"章节。

---

## 后续方向

- Boss 级题目类型（多文件 / 多语言 / 性能基准）
- 沙箱迁移到 Firecracker / gVisor 实现强隔离
- 实时协作（多人同 quiz）
- 抄袭检测（MOSS 集成）
- 更多语言（Java / C++ / Rust）
- 高级分析 dashboard（题目难度自动调整 / 学生学习轨迹）

---

## 团队与致谢

UNSW COMP9900 25T3 capstone 项目（Project ID 10）。

- **客户**：Henry Hickman, UNSW CSE
- **参考**：原版 [CodeRunner](https://coderunner.org.nz/) Moodle 插件、[codeWOF](https://codewof.co.nz/)

---

## License

学术作业项目，MIT License（见 LICENSE）。
