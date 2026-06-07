# CodeRunner-AI 文档

最后更新：2026-06-03

本目录只保留当前有效文档入口。历史实现指南、旧计划和归档材料统一从对应分类入口进入，不在根索引里混放。

## 目录约定

| 目录 | 用途 |
|---|---|
| `guides/` | 安装、运行、Docker、本地开发等操作指南 |
| `architecture/` | 当前架构、边界、运行时设计和模块分析 |
| `api/` | REST API、AI API、SSE、trace/eval 接口说明 |
| `validation/` | 测试、验证、MCP 合约和权限验证方法 |
| `plans/` | 当前计划与历史计划的唯一入口 |
| `status/` | 状态报告、审计报告、成熟度评估和知识图谱 |
| `issues/` | 当前已知、尚未解决问题的唯一入口与跟踪清单 |
| `archive/` | 非计划类历史材料，例如已完成的旧实现指南 |

## 快速使用

| 文档 | 用途 |
|---|---|
| [guides/installation.md](guides/installation.md) | 本地启动、部署配置、初始化和常见问题 |
| [guides/docker-containers.md](guides/docker-containers.md) | Docker 服务边界、镜像内容、端口、volume 和重建策略 |
| [guides/docker-containers.zh-CN.md](guides/docker-containers.zh-CN.md) | Docker 容器说明中文版 |

## 架构

架构文档已按编号组织，入口见 [architecture/README.md](architecture/README.md)。

| 编号 | 文档 | 用途 |
|---|---|---|
| 00 | [architecture/README.md](architecture/README.md) | 架构文档索引与阅读顺序 |
| 01 | [architecture/overview.md](architecture/overview.md) | 系统总览：分层架构、请求流、领域模型、数据库结构 |
| 02 | [architecture/ai-agents.md](architecture/ai-agents.md) | AI Agent 平台：设计、运行时核心、Router/Orchestrator、工具与记忆 |
| 03 | [architecture/data-state-memory.md](architecture/data-state-memory.md) | 数据、状态与记忆：数据模型、短/中/长期记忆、RAG 状态 |
| 04 | [architecture/tools-mcp-rag.md](architecture/tools-mcp-rag.md) | 工具、MCP 与知识库：Tool 调用、MCP 边界、scope/identity、RAG、权限 |
| 05 | [architecture/executor.md](architecture/executor.md) | 代码执行沙箱：隔离执行、资源限制、状态码 |
| 06 | [architecture/security-permissions-reliability.md](architecture/security-permissions-reliability.md) | 安全、认证与权限：认证/JWT、RBAC、数据隔离、注入防护、限流审计 |
| 07 | [architecture/eval-trace-observability-deployment.md](architecture/eval-trace-observability-deployment.md) | 可观测性、评测与部署：Trace、Eval、metrics、服务拓扑、CI/CD |

> 研究类对比分析见 [research/2026-06-03-memory-module-comparison.md](research/2026-06-03-memory-module-comparison.md)。

## API

| 文档 | 用途 |
|---|---|
| [api/rest-api.md](api/rest-api.md) | REST API 参考，配合运行时 `/swagger-ui` 使用 |
| [api/ai-api.md](api/ai-api.md) | AI API 端点、异步任务、SSE 事件协议、trace/eval 接口 |

## 验证

| 文档 | 用途 |
|---|---|
| [validation/testing.md](validation/testing.md) | Cypress E2E、pytest、测试套件结构和运行方式 |
| [validation/mcp-validation.md](validation/mcp-validation.md) | MCP 工具契约、权限矩阵、scope/RBAC、human gate 验证 |

## 计划

计划只从 [plans/README.md](plans/README.md) 进入：

- 当前仍执行或仍作为目标状态依据的计划放在 `plans/active/`。
- 已完成、被替代、暂停或仅供追溯的计划放在 `plans/archive/`。
- 不再使用 `archive/plans/`，避免两个归档入口。

当前无活跃计划;历史计划见 [plans/README.md](plans/README.md) 的 Archive 段。

## 状态与评估

状态报告和审计报告只从 [status/README.md](status/README.md) 进入。这里包括生产成熟度评估、agent 模块审计、历史状态快照和知识图谱。

## 当前已知问题

尚未解决的问题清单从 [issues/README.md](issues/README.md) 进入。这里汇总当前需要跟踪/排期的 P1–P3 问题(含双层 ORM 数据模型、迁移基线缺失、E2E 未进 CI 等),并承接 status 报告里仍未解决的项。

## 历史材料

非计划类历史材料从 [archive/README.md](archive/README.md) 进入。归档材料不作为当前实现事实的来源；判断当前行为时以代码、运行时和本页列出的当前文档为准。

## 推荐阅读顺序

1. 快速跑起来：`guides/installation.md`
2. 理解整体设计：`architecture/overview.md` -> `architecture/security-permissions-reliability.md` -> `architecture/executor.md`
3. 理解 AI/MCP：`architecture/ai-agents.md` -> `architecture/tools-mcp-rag.md` -> `api/ai-api.md`
4. 调用 API：`api/rest-api.md` + 运行时 `/swagger-ui`
5. 做验证或回归：`validation/testing.md` -> `validation/mcp-validation.md`
6. 看计划：`plans/README.md`
7. 看状态和审计：`status/README.md`
