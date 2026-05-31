# CodeRunner 文档

> 最后更新：2026-06-01

CodeRunner 是一个面向编程教学的在线评测平台。本文档目录只保留当前有效入口；历史计划、状态快照和已完成方案统一放入 `archive/`。

## 文档导航

### 快速使用

| 文档 | 用途 |
|---|---|
| [guides/installation.md](guides/installation.md) | 本地启动、部署、配置、初始化和常见问题 |
| [guides/docker-containers.md](guides/docker-containers.md) | Docker 服务边界、镜像内容、端口、volume、重建策略 |
| [guides/docker-containers.zh-CN.md](guides/docker-containers.zh-CN.md) | Docker 容器说明中文版 |

### 架构

| 文档 | 用途 |
|---|---|
| [architecture/overview.md](architecture/overview.md) | 分层架构、请求流、领域模型、数据库结构 |
| [architecture/auth.md](architecture/auth.md) | JWT + Flask-Login、RBAC、密码与 token 设计 |
| [architecture/executor.md](architecture/executor.md) | 代码执行沙箱、本地/远程/Docker 模式、资源限制、状态码 |
| [architecture/ai-agents.md](architecture/ai-agents.md) | AI Agent 当前架构、接口、运行流程 |
| [architecture/mcp-runtime.md](architecture/mcp-runtime.md) | MCP 运行时架构、ToolRuntime 边界、gateway、guard 流水线 |

### API

| 文档 | 用途 |
|---|---|
| [api/rest-api.md](api/rest-api.md) | REST API 参考，配合运行时 `/swagger-ui` 使用 |
| [api/ai-api.md](api/ai-api.md) | AI API 端点、异步任务、SSE 事件协议、trace/eval 接口 |

### 验证

| 文档 | 用途 |
|---|---|
| [validation/testing.md](validation/testing.md) | Cypress E2E、pytest、测试套件结构与运行方式 |
| [validation/mcp-validation.md](validation/mcp-validation.md) | MCP 工具契约、权限矩阵、scope/RBAC、human gate 验证 |

### 当前计划

| 文档 | 用途 |
|---|---|
| [plans/active/2026-05-31-agent-improvement-plan.md](plans/active/2026-05-31-agent-improvement-plan.md) | Agent 改进计划：hook、tool loop、错误处理、限流、handoff 等 |
| [plans/active/2026-06-01-complete-traces-evals-plan.md](plans/active/2026-06-01-complete-traces-evals-plan.md) | 完整 traces 与 eval 平台目标态实施计划 |

### 历史归档

| 文档 | 用途 |
|---|---|
| [archive/README.md](archive/README.md) | 已完成计划、历史状态、旧审计报告和历史执行记录 |

## 推荐阅读顺序

- 快速跑起来：`guides/installation.md` -> 浏览器打开本地服务。
- 理解整体设计：`architecture/overview.md` -> `architecture/auth.md` -> `architecture/executor.md`。
- 理解 AI/MCP：`architecture/ai-agents.md` -> `architecture/mcp-runtime.md` -> `api/ai-api.md`。
- 调用 API：`api/rest-api.md` + 运行时 `/swagger-ui`。
- 做验证或回归：`validation/testing.md` -> `validation/mcp-validation.md`。
- 追踪历史方案：`archive/README.md`。
