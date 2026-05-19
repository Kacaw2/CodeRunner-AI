# CodeRunner 文档

CodeRunner 是一个面向编程教学的在线评测平台，由 UNSW COMP9900 25T3 capstone 团队开发，客户为 UNSW CSE Henry Hickman。

## 文档导航

| 文档 | 用途 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 分层架构、请求流、领域模型、数据库结构 |
| [AUTH.md](AUTH.md) | 双轨认证（JWT + Flask-Login）、RBAC 装饰器、密码与 token 设计 |
| [EXECUTOR.md](EXECUTOR.md) | 代码沙箱：本地 / 远程 / Docker 三模式、resource limits、状态码 |
| [API.md](API.md) | REST API 参考（按模块组织，配合 `/swagger-ui` 交互文档使用）|
| [INSTALLATION.md](INSTALLATION.md) | 部署、配置、初始化、常见问题 |
| [TESTING.md](TESTING.md) | Cypress E2E 测试套件结构与运行 |

## 阅读顺序建议

- **想快速跑起来**：[INSTALLATION.md](INSTALLATION.md) → 浏览器打开 http://localhost:9900
- **想理解整体设计**：[ARCHITECTURE.md](ARCHITECTURE.md) → [AUTH.md](AUTH.md) → [EXECUTOR.md](EXECUTOR.md)
- **想集成 / 调用 API**：[API.md](API.md) + 运行时 `/swagger-ui`
- **想加测试 / 跑回归**：[TESTING.md](TESTING.md)
