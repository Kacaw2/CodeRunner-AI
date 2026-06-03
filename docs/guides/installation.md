# 部署指南

> 最后更新: 2026-05-28

## 系统要求

| 项 | 最低 | 推荐 |
|---|---|---|
| CPU | 2 核 | 4 核+ |
| 内存 | 4 GB | 8 GB |
| 磁盘 | 10 GB | 20 GB |
| Docker | 20.10+ | 24.0+ |
| Docker Compose | 2.0+ | 2.0+ |

支持的操作系统：macOS 10.15+ / Ubuntu 20.04+ / Debian 11+ / Fedora 35+ / Windows 10+ (WSL2)。

```bash
docker --version
docker compose version
docker ps
```

---

## 快速启动

```bash
# 1. 启动全部服务（Flask + Workers + MCP Gateway + MySQL + Redis）
docker compose up -d --build

# 2. 等待 30 秒服务初始化
sleep 30

# 3. 初始化数据库 + 注入示例数据
docker compose exec web \
  python -m app.core.init_db --drop --seed
```

验证：
```bash
curl http://localhost:9900/health       # Flask Web
curl http://localhost:8100/api/health   # Workers (Agent Host)
curl http://localhost:8200/sse          # MCP Gateway (SSE transport)
```

### 服务启动顺序

`docker compose` 通过 `depends_on` + `healthcheck` 自动保证：

```
db (MySQL:3306) → redis (:6379) → web (Flask:9900) → workers (FastAPI:8100) → mcp_gateway (MCP:8200)
```

Workers 守护进程通过 HTTP adapter 调用 Flask 后端执行 agent 任务，MCP Gateway 提供工具协议层对外服务，三者共享同一 MySQL + Redis。

### 默认账号

```
教师：teacher1 / admin123    （teacher1-3）
学生：student1 / admin123    （student1-8）
```

`init_db --seed` 创建：

- 12 用户（1 admin / 3 教师 / 8 学生）
- 5 班级（PY101A / PY201A / C101A / C201A / WS101）
- 15 编程题目（Python + C）+ 测试用例
- 8 quiz 与班级分配
- 29 学生入班记录

---

## 配置

`.env` 文件（项目根，不提交到 git）：

```env
# Flask
FLASK_ENV=production
SECRET_KEY=<32 字节随机串>
JWT_SECRET_KEY=<32 字节随机串>

# MySQL
MYSQL_USER=educode
MYSQL_APP_PASSWORD=<应用账号密码>
MYSQL_PASSWORD=<root 密码>
MYSQL_DATABASE=coderunner

# Redis
REDIS_URL=redis://redis:6379/0

# 端口
WEB_PORT=9900
AGENT_HOST_PORT=8100    # Workers daemon
MCP_PORT=8200           # MCP Gateway
MYSQL_PORT=3306
REDIS_PORT=6379

# AI（DeepSeek）
DEEPSEEK_API_KEY=<your-api-key>
AI_MODEL=deepseek-chat
AI_MAX_TOKENS=2048
AI_TEMPERATURE=0.7

# 沙箱（详见 docs/architecture/executor.md）
EXECUTOR_TMP_DIR=/tmp/executor
EXECUTOR_MAX_MEMORY_MB=256
EXECUTOR_DEFAULT_TIMEOUT=2.0
USE_DOCKER=false
# EXECUTOR_REMOTE_URL=https://executor.example.com/run    # 可选：远程沙箱
# EXECUTOR_API_TOKEN=<token>
```

> **重要**：`SECRET_KEY` 必须在 Flask 和 Workers 间保持一致，否则 JWT 令牌无法互认。

生成 SECRET_KEY：`python -c "import secrets; print(secrets.token_urlsafe(32))"`

---

## 数据库初始化选项

```bash
# 仅建表（空库）
docker compose exec web python -m app.core.init_db

# 建表 + seed
docker compose exec web python -m app.core.init_db --seed

# 推荐：清库重建 + seed
docker compose exec web python -m app.core.init_db --drop --seed

# 跳过确认
docker compose exec web python -m app.core.init_db --drop --seed --force
```

迁移管理（Alembic）：

```bash
# 生成迁移
docker compose exec web flask db migrate -m "add foo column"

# 应用迁移
docker compose exec web flask db upgrade
```

---

## 常用运维命令

```bash
# 查看日志
docker compose logs -f web           # Flask 主服务
docker compose logs -f workers       # Workers (Agent Host daemon)
docker compose logs -f mcp_gateway   # MCP Gateway
docker compose logs -f db            # MySQL

# 重启单个服务
docker compose restart web
docker compose restart workers
docker compose restart mcp_gateway

docker compose up --build web workers mcp_gateway -d

# 仅重建 Workers（修改 workers/ 或 agents/ 或 graph/ 后）
docker compose up --build workers -d

# 仅重建 MCP Gateway（修改 mcp_gateway/ 或 tools/ 后）
docker compose up --build mcp_gateway -d

# 停止（保留数据）
docker compose stop

# 停止 + 删除容器（保留 volume）
docker compose down

# 完全清理（包括数据卷）
docker compose down -v

# 重新构建全部（代码变更后）
docker compose up -d --build
```

### Makefile 快捷方式

项目根的 `Makefile`（如已配置）：

```bash
make start      # up -d --build
make stop       # down
make restart    # restart
make logs       # logs -f web
make init-db    # init_db --drop --seed --force
make clean      # down -v
make health     # curl /health
make status     # ps
```

---

## 端口映射

| 端口 | 服务 | 容器名 |
|---|---|---|
| 9900 | Flask Web 应用 | educode_web |
| 8100 | FastAPI Workers (Agent Host) | educode_workers |
| 8200 | MCP Gateway | educode_mcp_gateway |
| 3306 | MySQL | educode_db |
| 6379 | Redis | educode_redis |

URL 速查：

| URL | 用途 |
|---|---|
| http://localhost:9900 | 主页 |
| http://localhost:9900/auth/login | 登录 |
| http://localhost:9900/dashboard | 用户 dashboard |
| http://localhost:9900/student/profile | 学生侧 |
| http://localhost:9900/teacher/questions | 教师题库管理 |
| http://localhost:9900/teacher/classrooms | 教师班级管理 |
| http://localhost:9900/swagger-ui | API 文档 |
| http://localhost:9900/health | Flask 健康检查 |
| http://localhost:8100/api/health | Workers 健康检查 |
| http://localhost:8200/sse | MCP Gateway (SSE transport) |

---

## 常见问题

### 端口被占用

```bash
lsof -i :9900       # 找出占用进程
# 或修改 .env 中的 WEB_PORT=8080
```

### 容器起不来

```bash
docker compose logs        # 看错误
docker compose down -v      # 清理后重建
docker compose up -d --build
```

### 数据库连接失败

通常是初始化没完成。等 30 秒后再试：

```bash
docker compose ps db
# STATE 应显示 healthy
```

如仍失败，检查 `.env` 中 `MYSQL_*` 与 `compose.yaml` 是否一致。

### 验证数据库

```bash
docker compose exec web python -c "
from app import create_app
from app.models.user import User
app = create_app()
with app.app_context():
    print(f'Total users: {User.query.count()}')
"
# 期望：Total users: 12
```

### 健康检查异常

```bash
curl http://localhost:9900/health       # Flask
curl http://localhost:8100/api/health   # Workers
curl http://localhost:8200/sse          # MCP Gateway
```

Flask 返回 503 通常意味着 DB 连接出问题。Workers 返回错误检查 Redis 和 Flask 连通性：

```bash
docker compose logs workers --tail=30
docker compose logs mcp_gateway --tail=30
```

---

## API 调用示例

```bash
# 登录获取 token
curl -X POST http://localhost:9900/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"student1","password":"admin123"}'
# 响应 { "token": "...", "user": {...} } 同时下发 Cookie

# 用 token 调受保护 API
curl http://localhost:9900/api/v1/auth/me \
  -H "Authorization: Bearer <TOKEN>"
```

完整 API 文档见 [../api/rest-api.md](../api/rest-api.md) 或运行时的 `/swagger-ui`。
