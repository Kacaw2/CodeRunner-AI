# 2026-06-07 · CodeRunner-AI 架构 00｜文档索引

> 文档编号 00 ｜ 最后更新 2026-06-07 ｜ 范围: 架构文档总入口、编号约定、阅读顺序

本目录是 CodeRunner-AI 的架构权威文档集，按编号组织。所有文档统一标题格式：

```
# <更新日期> · CodeRunner-AI 架构 NN｜<主题>

> 文档编号 NN ｜ 最后更新 <日期> ｜ 范围: <一句话范围>
```

## 文档清单

| 编号 | 文档 | 范围 |
|---|---|---|
| 01 | [系统总览](overview.md) | 技术栈、分层结构、请求流、领域模型、配置真源、容器化 |
| 02 | [AI Agent 平台](ai-agents.md) | Agent 设计、运行时核心流程、Router/Orchestrator、工具与记忆集成、数据模型、API 与配置 |
| 03 | [数据、状态与记忆](data-state-memory.md) | 数据模型、会话与业务状态、短/中/长期记忆、RAG 状态、缓存限流降级 |
| 04 | [工具、MCP 与知识库](tools-mcp-rag.md) | Tool 调用体系、Tool Registry、MCP 边界与运行时、scope/identity、RAG、检索重排、工具权限 |
| 05 | [代码执行沙箱](executor.md) | 不可信代码隔离执行、资源限制、输出归一化、状态码映射 |
| 06 | [安全、认证与权限](security-permissions-reliability.md) | 认证（双轨装饰器/三源 token/JWT）、RBAC、数据隔离、工具权限、注入防护、限流审计 |
| 07 | [可观测性、评测与部署](eval-trace-observability-deployment.md) | Trace、Evaluation、Logging/Metrics、性能成本、服务拓扑、CI/CD、配置密钥 |

## 推荐阅读顺序

1. **整体设计**：01 系统总览 → 03 数据、状态与记忆 → 05 代码执行沙箱。
2. **AI 平台**：02 AI Agent 平台 → 04 工具、MCP 与知识库 → [../api/ai-api.md](../api/ai-api.md)。
3. **安全与运维**：06 安全、认证与权限 → 07 可观测性、评测与部署。

## 编号约定

- 编号一旦分配即稳定，不随内容更新而变化；新增文档取下一个未用编号。
- 文档合并时保留承载文档的编号，被合并文档的内容并入对应章节，并修正跨文档链接。
- 研究类、对比类、计划类材料不进入本编号体系，分别放在 [../research/](../research/) 与 [../plans/](../plans/)。
