# Docker 容器说明

> 最后更新：2026-06-01
> 信息来源：仓库根目录的 `compose.yaml`

本文记录本地 CodeRunner-AI 运行时使用的 Docker 服务、每个容器负责的功能，以及它们对应的仓库模块。

## 当前服务列表

在仓库根目录执行下面命令，可以核对当前 compose 定义和实际运行状态：

```powershell
docker compose config --services
docker compose ps
```

根目录 `compose.yaml` 定义了 6 个服务：

| 服务 | 容器名 | 作用 | 主要端口 |
|---|---|---|---|
| `db` | `educode_db` | MySQL 应用数据库 | `${MYSQL_PORT:-3306}:3306` |
| `redis` | `educode_redis` | Redis 缓存 / 协调后端 | `${REDIS_PORT:-6379}:6379` |
| `executor` | `educode_executor` | 隔离代码执行沙箱 | 容器内部 `8300` |
| `mcp_gateway` | `educode_mcp_gateway` | 基于 streamable HTTP 的 MCP 工具网关 | `${MCP_PORT:-8200}:8200` |
| `web` | `educode_web` | Flask 主业务应用和对外 API | `${WEB_PORT:-9900}:9900` |
| `workers` | `educode_workers` | FastAPI Agent Host / 异步 agent worker 运行时 | `${AGENT_HOST_PORT:-8100}:8100` |

在这台 Windows 机器上，`9900` 可能落在系统保留端口范围内。
如果 Docker 无法绑定 `9900`，本地 `.env` 里应使用：

```text
WEB_PORT=19900
```

此时浏览器入口为：

```text
http://localhost:19900
```

## 运行时拓扑

```text
Browser / API client
  -> web (Flask 主应用，容器内部 :9900)
      -> db (MySQL)
      -> redis
      -> executor (代码沙箱 HTTP 服务，内部 :8300)
      -> workers (Agent Host，内部 :8100)
          -> mcp_gateway (MCP transport，内部/外部 :8200)
              -> tool runtime modules
```

关键边界如下：

- `web` 负责用户可见路由、认证、业务 API、请求校验和持久化。
- `workers` 负责 agent 运行时执行和异步 agent 工作流。
- `mcp_gateway` 负责 MCP 工具传输、能力 token 校验和工具访问控制。
- `executor` 负责运行不可信代码，并和主应用网络隔离。

## 容器职责

### `db` / `educode_db`

**用途：** 主应用的持久化 MySQL 数据库。

**职责：**

- 存储用户、认证状态、题目、提交记录、对话、agent task 记录和其他关系型业务数据。
- MySQL volume 第一次创建时，通过 `docker/init.sql` 初始化 schema seed SQL。
- 为 `web`、`workers`、`mcp_gateway` 提供数据库后端。

**Compose 细节：**

- 镜像：`mysql:8.0`
- 数据卷：`mysql_data:/var/lib/mysql`
- 初始化挂载：`./docker/init.sql:/docker-entrypoint-initdb.d/init.sql:ro`
- 网络：`educode_network`
- 健康检查：`mysqladmin ping`

**关联仓库模块：**

- `app/models/`
- `app/services/`
- `workers/`
- `mcp_gateway/`

### `redis` / `educode_redis`

**用途：** 运行时共享 Redis 服务。

**职责：**

- 为应用和 worker 路径提供缓存、协调和状态存储。
- 给 `web`、`workers`、`mcp_gateway` 提供 `REDIS_URL=redis://redis:6379/0`。

**Compose 细节：**

- 镜像：`redis:7-alpine`
- 数据卷：`redis_data:/data`
- 网络：`educode_network`
- 健康检查：`redis-cli ping`

**关联仓库模块：**

- `app/`
- `workers/`
- `mcp_gateway/`

### `executor` / `educode_executor`

**用途：** 用于运行提交代码的隔离沙箱服务。

**职责：**

- 通过 `http://executor:8300/run` 接收代码执行请求。
- 执行内存、超时、stdout/stderr 大小、PID 数量、只读根文件系统、Linux capability drop、`no-new-privileges` 等限制。
- 将不可信代码执行从主 Flask 容器中隔离出来。

**Compose 细节：**

- 构建文件：`docker/Dockerfile.executor`
- 镜像内复制的源码：
  - `app/core/executor.py`
  - `docker/executor_server.py`
- 内部服务端口：`8300`
- 网络：`executor_network`
- `executor_network` 标记为 `internal: true`
- `web` 通过 `EXECUTOR_REMOTE_URL=http://executor:8300/run` 调用它。

**关联仓库模块：**

- `app/core/executor.py`
- `app/services/executor_service.py`
- `docker/executor_server.py`

### `web` / `educode_web`

**用途：** 主 Flask 应用和用户可见后端。

**职责：**

- 提供主应用、页面和对外 API 路由。
- 处理认证、RBAC、session、题目 API、提交 API、AI API endpoint 和健康检查。
- 当 `USE_AGENT_HOST_PROXY=true` 时，在代理到 Agent Host 前执行 Flask 侧请求校验。
- 调用 `executor` 服务执行代码。
- 调用 `http://workers:8100` 执行异步 / agent 工作流。
- 加载知识库健康探针，并通过 `kb_data` 共享向量库数据。

**Compose 细节：**

- 构建文件：`docker/Dockerfile`
- 容器内部应用端口：`9900`
- 本机访问端口：`${WEB_PORT:-9900}`。这台机器建议使用 `WEB_PORT=19900`。
- 健康检查入口：`http://localhost:<WEB_PORT>/health`
- 网络：
  - `educode_network`
  - `executor_network`
- 依赖以下服务 healthy 后启动：
  - `db`
  - `redis`
  - `executor`

**bind mount 的源码模块：**

`web` 服务以只读方式 bind mount 这些路径，因此很多纯代码改动可以通过 recreate 或 restart `web` 生效，不一定需要重建镜像：

- `app/`
- `core/`
- `tools/`
- `agents/`
- `graph/`
- `memory/`
- `knowledge/`
- `models/`
- `workers/`
- `mcp_gateway/`
- `scripts/`

**可写 / 运行时挂载：**

- `./uploads:/app/uploads`
- `./logs:/app/logs`
- `executor_tmp:/tmp/executor`
- `kb_data:/app/data/knowledge_base`
- `hf_cache:/app/.hf_cache`

**主要负责或服务的仓库模块：**

- `app/`
- `core/`
- `tools/`
- `agents/`
- `graph/`
- `knowledge/`
- `memory/`
- `models/`

### `workers` / `educode_workers`

**用途：** FastAPI Agent Host 和异步 agent 运行时。

**职责：**

- 在端口 `8100` 运行 agent worker API。
- 执行由 `web` 发起的异步 AI chat / task 工作流。
- 加载 agent runtime 模块，并通过 `FLASK_BASE_URL=http://web:9900` 回连 Flask 应用。
- 当 `MCP_AGENT_TRANSPORT=streamable-http` 时，通过 MCP transport 调用工具。
- 使用 `MCP_INTERNAL_SIGNING_KEY` 签发短生命周期的内部 MCP capability token。
- 调用 `http://mcp_gateway:8200/mcp` 访问 MCP gateway。

**Compose 细节：**

- 构建文件：`docker/Dockerfile.workers`
- 内部和默认本地端口：`${AGENT_HOST_PORT:-8100}:8100`
- 健康检查入口：`http://localhost:<AGENT_HOST_PORT>/api/health`
- 网络：`educode_network`
- 依赖以下服务 healthy 后启动：
  - `db`
  - `redis`
  - `web`
  - `mcp_gateway`

**`docker/Dockerfile.workers` 复制进镜像的源码：**

- `app/`
- `core/`
- `tools/`
- `agents/`
- `graph/`
- `memory/`
- `knowledge/`
- `models/`
- `workers/`
- `mcp_gateway/`

因为这些路径会被复制进 `workers` 镜像，所以如果修改了 `agents/`、`workers/`、`tools/`、`graph/`、`core/` 或 `mcp_gateway/`，通常需要 rebuild 或 recreate 这个服务。除非额外增加开发用 override，把这些目录改成 bind mount。

**主要负责或执行的仓库模块：**

- `workers/`
- `agents/`
- `graph/`
- `core/`
- `tools/`
- `knowledge/`
- `memory/`

### `mcp_gateway` / `educode_mcp_gateway`

**用途：** agent 工具调用的 MCP gateway 服务。

**职责：**

- 运行 `python -m mcp_gateway --transport streamable-http --host 0.0.0.0 --port 8200`。
- 暴露给 Agent Host 使用的 MCP HTTP endpoint。
- 使用 `MCP_INTERNAL_VERIFY_KEY` 校验内部 capability token。
- 将工具调用连接到数据库、Redis、知识库持久化和 tool runtime 模块。
- 作为工具权限、scope、risk policy 和审计能力的运行时边界。

**Compose 细节：**

- 构建文件：`docker/Dockerfile.workers`
- 使用自定义 entrypoint 覆盖默认 worker 启动命令。
- 内部和默认本地端口：`${MCP_PORT:-8200}:8200`
- 网络：`educode_network`
- 依赖以下服务 healthy 后启动：
  - `db`
  - `redis`
- 健康检查：socket 连接 `localhost:8200`

**数据卷：**

- `kb_data:/app/data/knowledge_base`
- `hf_cache:/app/.hf_cache`

**主要负责或执行的仓库模块：**

- `mcp_gateway/`
- `tools/`
- `core/`
- `knowledge/`
- `models/`

## 数据卷

| 数据卷 | 使用方 | 用途 |
|---|---|---|
| `mysql_data` | `db` | MySQL 持久化数据 |
| `redis_data` | `redis` | Redis 持久化数据 |
| `executor_tmp` | `web` | 挂载到 `/tmp/executor` 的临时执行目录 |
| `kb_data` | `web`, `mcp_gateway` | Chroma / 知识库向量持久化 |
| `hf_cache` | `web`, `workers`, `mcp_gateway` | HuggingFace / 模型缓存 |

不要删除 `mysql_data`，除非你明确想重置数据库。
删除 `kb_data` 只会重置本地向量索引，不会删除 MySQL 里的题目和业务源数据。

## 常用本地命令

启动或重新创建完整服务栈：

```powershell
docker compose up -d
docker compose ps
```

修改宿主机端口设置后，只重新创建用户可见的 `web`：

```powershell
docker compose up -d --force-recreate web
docker compose ps web
docker port educode_web
```

修改了复制进镜像的 agent / runtime 代码后，重建相关服务：

```powershell
docker compose up -d --build workers mcp_gateway
```

当代码是 bind mount 且不需要重建镜像时，直接重启服务：

```powershell
docker compose restart web
```

查看日志：

```powershell
docker compose logs -f web
docker compose logs -f workers
docker compose logs -f mcp_gateway
```

检查健康状态：

```powershell
Invoke-RestMethod http://localhost:19900/health
Invoke-RestMethod http://localhost:8100/api/health
```

## 本地排障备注

- 如果 Docker 在 Windows 上报告 `0.0.0.0:9900` 的 `ports are not available`，先检查系统排除端口范围：

  ```powershell
  netsh interface ipv4 show excludedportrange protocol=tcp
  ```

  如果 `9900` 落在 excluded range 里，在本地 `.env` 设置 `WEB_PORT=19900`，然后重新创建 `web`。

- `docker compose restart web` 只会重启已有容器，不会应用新的端口映射。修改 `.env` 端口值后，要执行：

  ```powershell
  docker compose up -d --force-recreate web
  ```

- 如果健康检查返回 `knowledge_base: degraded: '_type'`，说明 `kb_data` 里的 Chroma vector-store 数据和当前 ChromaDB 库格式不兼容。Flask 应用仍可 healthy，但 RAG / 知识库功能可能降级，直到重置或迁移向量索引。
