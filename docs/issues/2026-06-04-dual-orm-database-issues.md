# 双层 ORM 数据模型问题报告

**识别日期:** 2026-06-04
**状态:** 部分解决(2026-06-05 更新:迁移基线、Alembic 全量 metadata、生产 `create_all()` 兜底已关闭;双 engine/双事务/重复映射仍保留为后续架构债)
**范围:** 数据持久层 —— Flask-SQLAlchemy 与 runtime-neutral SQLAlchemy 并存
**核验:** 已按当前代码和 `docs/plans/archive/2026-06-04-dual-orm-single-schema-source-plan.md` 更新

---

## 一、当前结论

本报告最初识别了两类问题:

1. **部署/迁移 P1 问题**:无完整 migration baseline、Alembic 看不见 core 表、生产启动靠 `db.create_all()` 补表。
2. **架构边界问题**:Flask-SQLAlchemy 与 runtime-neutral SQLAlchemy 仍是两套 engine/session/model registry,部分表重复映射。

截至 2026-06-05,第 1 类已经关闭:

- `migrations/versions/e21895a59f7d_baseline_full_schema.py` 是单条完整 schema baseline,`down_revision=None`。
- `migrations/env.py` 改为通过 `core/db/metadata.py:build_target_metadata()` 暴露合并 metadata。
- `tests/test_migration_full_schema.py` 不再 xfail,用于证明空库 `upgrade head` 可建完整 schema。
- `app/__init__.py` 的 `_ensure_tables()` 只做 schema 检查并提示 `flask db upgrade head`,不再调用 `db.create_all()`。

第 2 类仍未最终收敛,但它不再是"空库不可部署"级别的问题,而是后续架构债:是否统一 engine/URL、是否消除重复 mapped class、MCP 模型是否归位。

## 二、仍存在的问题:两套并存的 ORM 体系

项目里仍有两套独立的模型层,指向同一个 MySQL 库:

| | Flask 层 | Runtime 层 |
|---|---|---|
| 基类 | `db.Model`(Flask-SQLAlchemy) | `core.db.session.Base`(纯 SQLAlchemy 2.0) |
| 位置 | `app/models/*` | `core/db/models/*` |
| 引擎 | Flask 应用上下文的 engine | `core/db/session.py` 内 `create_engine(...)` 自建的 engine |
| URL 来源 | `app/core/config.py` 设 `SQLALCHEMY_DATABASE_URI` | `core/config.py` 的 `_build_database_url()` |

这不是"同一个 ORM 的两个模块",而是**两个引擎、两个连接池、两套事务作用域、两个独立的 URL 构造逻辑**,只是恰好连到同一个数据库。

---

## 三、具体危害(按当前严重程度排序)

### P2 — 跨层写操作没有原子性(数据一致性风险)

Flask 引擎和 core 引擎是两个连接池、两套事务。一次业务流程若同时写 Flask 表(如 `ai_messages`)和 core 表(如 `agent_trace_runs`),它们处在两个不同的事务里,无法一起 commit/rollback。一边成功一边失败时,数据库就处于不一致状态(例如对话记录写进去了但 trace 半截,或反之),且没有任何机制能自动修复。

### P2 — 两套 URL 构造逻辑 → 静默指向不同库

`app/core/config.py` 和 `core/config.py` 各自解析数据库地址。只要两边的环境变量读取顺序、默认值、回退逻辑稍有出入(目前 core 读 `DATABASE_URL`/`MYSQL_*`/`DB_*`,Flask 单独设 `SQLALCHEMY_DATABASE_URI`,测试态还会切 sqlite),就可能出现 Flask 写 A 库、core 写 B 库的情况,而且不会报错,只表现为"数据莫名其妙丢了/对不上"。

### ✅ 已关闭 — Alembic 只能看见 Flask 元数据(迁移会误删 core 表)

原问题:`migrations/env.py` 的 `get_metadata()` 只返回 Flask-SQLAlchemy metadata,core `Base` 注册的表对 autogenerate 不可见。

当前状态:已关闭。`migrations/env.py:get_metadata()` 现在调用 `core/db/metadata.py:build_target_metadata()`,将 Flask metadata 与 core-only 表合并;共享表名以 Flask 定义为准,防止重复表冲突。`tests/test_combined_metadata.py` 守住这一点。

原后果已不再成立:autogenerate 不再只看 Flask 一半表,空库重建也不再依赖旧 xfail 占位。

### P2 — 同一张表在两个 registry 里各定义一遍(映射冲突)

以下表在**两套 metadata 里都有定义**:

| 表名 | Flask 层 | Runtime 层 |
|---|---|---|
| `ai_conversations` | `app/models/ai_conversation.py:6` | `core/db/models/ai_conversation.py:22` |
| `ai_messages` | `app/models/ai_conversation.py:26` | `core/db/models/ai_conversation.py:43` |
| `chat_tasks` | `app/models/chat_task.py:11` | `core/db/models/chat_task.py:23` |
| `workflow_runs` | `app/models/workflow.py:9` | `core/db/models/workflow.py:23` |
| `workflow_steps` | `app/models/workflow.py:67` | `core/db/models/workflow.py:84` |
| `eval_runs` | `app/models/eval_run.py:7` | `core/db/models/agent_trace.py:150` |
| `users` | `app/models/user.py:14` | `core/db/models/agent_user.py:10` |

同一张物理表对应**两个 mapped class**,带来:

- identity map 不互通:Flask 查出来的 `AiMessage` 和 core 查出来的不是同一对象、不在同一 session,容易脏读/覆盖写。
- `create_all()` 谁先建谁后建顺序不确定;两套定义若字段/索引/约束有细微差异,以先建者为准,另一套静默失效。
- 同名 `eval_runs` 两边字段不一致时,问题尤其隐蔽。

### P2 — 边界被打破:core 目录下却用 Flask 的 db

`core/db/models/mcp_api_key.py`(`mcp_api_keys`)、`mcp_approval.py`(`mcp_tool_approvals`)、`mcp_audit_log.py`(`mcp_audit_logs`)物理上放在 `core/`(本应 runtime-neutral),但内部用的是 Flask 的 `db.Column`/`db.ForeignKey`,不是 core `Base`。这让"core 不依赖 Flask"的分层假设名存实亡,也意味着这几个表实际归属于 Flask 元数据,边界更难讲清。

### ✅ 已关闭 — 跨层外键 + 依赖 create_all 的隐式建表顺序

原问题:core 的 `chat_task.py` 外键指向 `users.id`、`ai_conversations.id`、`ai_messages.id`;mcp 模型外键指向 `users.id`/`mcp_api_keys.id`。被引用的表分散在两套 metadata 里,且空库建表依赖 `db.create_all()`,存在顺序风险。

当前状态:迁移基线已经成为空库建表事实源,不再依赖跨 metadata 的运行时 `create_all()` 顺序。重复映射仍是上面的 P2 架构债,但建表顺序问题已关闭。

### ✅ 已关闭 — 没有迁移基线,真正的 schema 源头是 create_all()

原问题:迁移链 base revision 为空,`app/__init__.py` 启动时调 `db.create_all()` 兜底补表。

当前状态:已关闭。

- `migrations/versions/e21895a59f7d_baseline_full_schema.py` 可以从空库建立完整 schema。
- `app/__init__.py:_ensure_tables()` 只检查必要表是否存在,缺失时记录错误并提示运行 `flask db upgrade head`。
- `tests/test_migration_full_schema.py` 是常态测试。

剩余注意:`evals/ci.py` 与测试 fixture 里仍有测试/CI 场景用 `create_all()` 构造临时库,这不是生产 schema 源头。

---

## 四、一句话总结

迁移和可重建性 P1 已关闭;剩下的真实问题是**两套 ORM 共用一个库,但事务不互通、URL 各算各的、还有 7 张表被定义两遍**。这会影响一致性和长期可维护性,但不再阻止空库部署或 migration baseline。

---

## 五、治理方向(当前状态)

真正的解法不是"修某个 bug",而是定清边界并收敛到单一事实源:

1. **先做迁移基线**:
   **✅ 已完成**(`docs/plans/archive/2026-06-04-dual-orm-single-schema-source-plan.md`):合并 metadata 后 autogenerate 出单条基线 `migrations/versions/e21895a59f7d_baseline_full_schema.py`(`down_revision=None`,完整 schema,空库 `upgrade head` 通过),`tests/test_migration_full_schema.py` 由 xfail 转为常态 PASS,`app/__init__.py` 启动期 `db.create_all()` 兜底已撤除。
   遗留:`evals/ci.py` 与测试 fixture 的 `create_all()` 属测试/CI 临时库构造;若后续要彻底统一测试 schema,另开专项。
2. **统一引擎/URL**:让 core 复用 Flask 同一个 engine 和同一份 URL 配置(或反之),消除双池双事务。
   **⏸ 暂缓**:与架构升级路线图(runtime/Agent Host 要脱离 Flask 独立)方向相反,需先有路线决策再动 code。
3. **消除重复表定义**:每张表只保留一个 mapped class,另一层通过 repository/service 访问。
   **⏸ 暂缓**:与当前过渡态(Phase 4 计划硬性要求"加列两份模型同步改")冲突,属后续独立工作。
4. **归位 mcp 模型**:要么真正用 core `Base`,要么挪回 `app/models`,别在 core 下用 Flask db。
   **⏸ 暂缓**:与 Phase 4 T2(计划复用/扩展 `core/db/models/mcp_approval.py`)耦合,到那里一并决策。
5. **让 Alembic 看见全部 metadata**:`env.py` 的 target_metadata 合并两套(或统一后只剩一套)。
   **✅ 已完成**:`core/db/metadata.py` `build_target_metadata()`(Flask 定义在 7 张共享表上优先,core-only 表叠加),`migrations/env.py:get_metadata()` 改用之,`tests/test_combined_metadata.py` 守住。

---

## 六、证据索引(file:line)

- 两个引擎:`core/db/session.py`(自建 `create_engine`)vs Flask app engine
- 两套 URL:`core/config.py` `_build_database_url()` vs `app/core/config.py` `SQLALCHEMY_DATABASE_URI`
- Alembic 全量 metadata:`migrations/env.py` `get_metadata()` → `core/db/metadata.py` `build_target_metadata()`
- 重复表定义:见第二节 P2 表格
- 边界 blur:`core/db/models/{mcp_api_key,mcp_approval,mcp_audit_log}.py` 用 Flask `db`
- 跨层外键:`core/db/models/chat_task.py`(FK → `users.id`/`ai_conversations.id`/`ai_messages.id`)
- 完整基线:`migrations/versions/e21895a59f7d_baseline_full_schema.py`;`tests/test_migration_full_schema.py`
- 生产启动 schema check:`app/__init__.py` `_ensure_tables()`
