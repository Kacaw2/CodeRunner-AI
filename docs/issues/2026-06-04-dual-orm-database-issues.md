# 双层 ORM 数据模型问题报告

**识别日期:** 2026-06-04
**状态:** 未解决(分析,未动代码)
**范围:** 数据持久层 —— Flask-SQLAlchemy 与 runtime-neutral SQLAlchemy 并存
**核验:** 关键结论已逐条核验到 file:line

---

## 一、问题根源:两套并存的 ORM 体系

项目里有两套独立的模型层,指向同一个 MySQL 库:

| | Flask 层 | Runtime 层 |
|---|---|---|
| 基类 | `db.Model`(Flask-SQLAlchemy) | `core.db.session.Base`(纯 SQLAlchemy 2.0) |
| 位置 | `app/models/*` | `core/db/models/*` |
| 引擎 | Flask 应用上下文的 engine | `core/db/session.py` 内 `create_engine(...)` 自建的 engine |
| URL 来源 | `app/core/config.py` 设 `SQLALCHEMY_DATABASE_URI` | `core/config.py` 的 `_build_database_url()` |

这不是"同一个 ORM 的两个模块",而是**两个引擎、两个连接池、两套事务作用域、两个独立的 URL 构造逻辑**,只是恰好连到同一个数据库。

---

## 二、具体危害(按严重程度排序)

### P1 — 跨层写操作没有原子性(数据一致性风险)

Flask 引擎和 core 引擎是两个连接池、两套事务。一次业务流程若同时写 Flask 表(如 `ai_messages`)和 core 表(如 `agent_trace_runs`),它们处在两个不同的事务里,无法一起 commit/rollback。一边成功一边失败时,数据库就处于不一致状态(例如对话记录写进去了但 trace 半截,或反之),且没有任何机制能自动修复。

### P1 — 两套 URL 构造逻辑 → 静默指向不同库

`app/core/config.py` 和 `core/config.py` 各自解析数据库地址。只要两边的环境变量读取顺序、默认值、回退逻辑稍有出入(目前 core 读 `DATABASE_URL`/`MYSQL_*`/`DB_*`,Flask 单独设 `SQLALCHEMY_DATABASE_URI`,测试态还会切 sqlite),就可能出现 Flask 写 A 库、core 写 B 库的情况,而且不会报错,只表现为"数据莫名其妙丢了/对不上"。

### P1 — Alembic 只能看见 Flask 元数据(迁移会误删 core 表)

`migrations/env.py` 的 `get_metadata()` 返回 `current_app.extensions['migrate'].db.metadata`,即**只有 Flask-SQLAlchemy 的 metadata**。core `Base` 注册的表对 autogenerate **完全不可见**:`agent_trace_runs`/`agent_trace_spans`/`agent_trace_events`/`agent_trace_artifacts`/`agent_trace_links`/`eval_case_runs`/`eval_case_grader_results`/`mcp_api_keys`/`mcp_tool_approvals`/`mcp_audit_logs` 等。后果:

- `flask db migrate` 自动生成迁移时看不到 core 表,误操作可能生成 `DROP TABLE` 这些 trace/eval 表的语句。
- core 表的任何 schema 变更 Alembic 都无法自动捕获,只能手写迁移。
- 这也是 `tests/test_migration_full_schema.py` 被标 `xfail` 的原因 —— 空库根本无法靠迁移链建出完整 schema。

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

### P2 — 跨层外键 + 依赖 create_all 的隐式建表顺序

core 的 `chat_task.py` 外键指向 `users.id`、`ai_conversations.id`、`ai_messages.id`;mcp 模型外键指向 `users.id`/`mcp_api_keys.id`。被引用的表分散在两套 metadata 里。因没有迁移基线,真正建表靠 `db.create_all()`,而它无法保证跨 metadata 的外键目标先于引用方创建 —— 空库初始化时容易因顺序问题建表失败或外键悬空。

### P1 — 没有迁移基线,真正的 schema 源头是 create_all()

迁移链的 base revision 是空 `pass`(不建任何 core 表);`app/__init__.py:70` 启动时调 `db.create_all()` 兜底补表。这意味着:

- 数据库 schema 的"事实源头"是运行时的 `create_all()`,不是迁移链。
- 无法从空库用 `flask db upgrade` 重建完整 schema → 部署、回滚、多人协作都不可靠。
- 这是上面所有问题的总放大器:只要靠 `create_all()`,两套 metadata 的差异、顺序、重复定义就都被"运行时凑合建出来"掩盖了。

---

## 三、一句话总结

两套 ORM 共用一个库,但**事务不互通、URL 各算各的、迁移只认 Flask 的一半表、还有 7 张表被定义两遍**;再加上没有迁移基线、靠 `create_all()` 兜底,导致一致性、可迁移性、可重建性三方面都不可靠。

---

## 四、治理方向(供后续决策,未动手)

真正的解法不是"修某个 bug",而是定清边界并收敛到单一事实源:

1. **先做迁移基线**:手写一个基线迁移,把两套 metadata 的全部表纳入,让 `flask db upgrade` 能从空库建出完整 schema,然后去掉 `create_all()`。收益最大,可一次性压住 P1(迁移)/ P2(建表顺序)/ P1(create_all 兜底)三条。
   **✅ 已完成**(`docs/plans/active/2026-06-04-dual-orm-single-schema-source-plan.md`):合并 metadata 后 autogenerate 出单条基线 `migrations/versions/e21895a59f7d_baseline_full_schema.py`(`down_revision=None`,35 表,空库 `upgrade head` 通过),`tests/test_migration_full_schema.py` 由 xfail 转为常态 PASS,`app/__init__.py` 启动期 `db.create_all()` 兜底已撤除。
   遗留:`workers/__main__.py:51` 仍有一处 worker 进程启动期的 `Base.metadata.create_all(engine)`(只建 core trace/eval 表)——属另一独立入口,基线已覆盖这些表,作为后续清理项,不在本次范围。
2. **统一引擎/URL**:让 core 复用 Flask 同一个 engine 和同一份 URL 配置(或反之),消除双池双事务。
   **⏸ 暂缓**:与架构升级路线图(runtime/Agent Host 要脱离 Flask 独立)方向相反,需先有路线决策再动 code。
3. **消除重复表定义**:每张表只保留一个 mapped class,另一层通过 repository/service 访问。
   **⏸ 暂缓**:与当前过渡态(Phase 4 计划硬性要求"加列两份模型同步改")冲突,属后续独立工作。
4. **归位 mcp 模型**:要么真正用 core `Base`,要么挪回 `app/models`,别在 core 下用 Flask db。
   **⏸ 暂缓**:与 Phase 4 T2(计划复用/扩展 `core/db/models/mcp_approval.py`)耦合,到那里一并决策。
5. **让 Alembic 看见全部 metadata**:`env.py` 的 target_metadata 合并两套(或统一后只剩一套)。
   **✅ 已完成**:`core/db/metadata.py` `build_target_metadata()`(Flask 定义在 7 张共享表上优先,core-only 表叠加),`migrations/env.py:get_metadata()` 改用之,`tests/test_combined_metadata.py` 守住。

---

## 五、证据索引(file:line)

- 两个引擎:`core/db/session.py`(自建 `create_engine`)vs Flask app engine
- 两套 URL:`core/config.py` `_build_database_url()` vs `app/core/config.py` `SQLALCHEMY_DATABASE_URI`
- Alembic 只认 Flask metadata:`migrations/env.py` `get_metadata()`
- 重复表定义:见第二节 P2 表格
- 边界 blur:`core/db/models/{mcp_api_key,mcp_approval,mcp_audit_log}.py` 用 Flask `db`
- 跨层外键:`core/db/models/chat_task.py`(FK → `users.id`/`ai_conversations.id`/`ai_messages.id`)
- 无基线 + 兜底:`app/__init__.py:70` `db.create_all()`;`tests/test_migration_full_schema.py` 标 `xfail`
