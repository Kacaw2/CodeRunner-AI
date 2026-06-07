# 2026-06-07 · CodeRunner-AI 架构 07｜可观测性、评测与部署

> 文档编号 07 ｜ 最后更新 2026-06-07 ｜ 范围: Trace、Evaluation、Logging/Metrics、性能成本、服务拓扑、CI/CD、配置密钥

本章描述 CodeRunner 作为**教育类多 Agent 平台**如何上线、监控与持续优化：每次执行如何被追踪（Trace）、答案质量如何被量化（Evaluation）、运行态如何被观测（Logging / Metrics / Monitoring）、性能与成本如何被计量，以及系统的服务拓扑、CI/CD 流水线与配置/密钥管理。

整章贯穿三条设计原则：

| 原则 | 含义 | 实现位置 |
|---|---|---|
| **可观测优先于可中断** | 观测代码绝不破坏 Agent 主路径——metrics/costing/trace 落库全部 best-effort、异常吞掉 | `tracing.py:_emit_metrics()`、`save()` 的 try/except |
| **运行时中立** | Trace / Eval 落库不依赖 Flask app context，Worker、MCP 网关、Eval harness、CI 均可写入 | `core/observability/trace_schema.py`、`core/db/session.py` |
| **不静默放行** | 未实现/不可用的判分器返回显式失败而非默默 pass，质量门禁宁可误报不漏报 | `ai/evals/graders/base.py:error_result()` |

相关章节：Agent 运行时见 [ai-agents.md](ai-agents.md)，数据落库见 [data-state-memory.md](data-state-memory.md)，工具与 RAG 见 [tools-mcp-rag.md](tools-mcp-rag.md)，安全红线见 [security-permissions-reliability.md](security-permissions-reliability.md)。

---

## 6.1 Agent Trace 设计

### 渐进式单 Trace 模型

CodeRunner 不为每个 Agent 各开一条 trace，而是**一次逻辑执行（一个 chat task / workflow run / eval case / handoff 链）= 一条 trace**。`core/observability/tracing.py` 用 `ContextVar` 维护"当前 trace"：

```
_current_trace: ContextVar  ->  当前执行上下文绑定的 TraceCollector
```

- `acquire_trace()`：若 harness 已绑定环境 trace，则复用并返回 `owns_trace=False`（Agent 只贡献 span/token，不覆盖 owner 的输入字段）；否则新建一条自有 trace。
- `finalize_trace()`：owner 负责唯一一次落库；非 owner 仅记录 `pending_status`，让拥有整条链的 harness 写出正确的终态，避免子 Agent 误报 `completed`。

这套机制让 handoff 链（如 tutor → reviewer）在同一条 trace 下连续记录，而直接 `agent.invoke()`、旧版 eval runner、单测等无环境 trace 的场景自动回退到"自有并落库"。

### Trace 数据模型

Schema 与 ORM 分离，保证运行时中立：

| 层 | 文件 | 形态 |
|---|---|---|
| Schema（纯数据） | `core/observability/trace_schema.py` | dataclass，无 ORM、无 Flask |
| ORM（落库） | `core/db/models/agent_trace.py` | 纯 SQLAlchemy 2.0，按 `trace_id` 建索引 |
| 持久化入口 | `core/observability/trace_store.py:TraceStore.save_run()` | 单事务写完整 trace 树 |

一条 trace 由五张表组成：

| 表 | dataclass | 记录内容 |
|---|---|---|
| `agent_trace_runs` | `TraceRunRecord` | 主运行记录：身份、状态、输入/输出预览、错误、token、成本、延迟拆分 |
| `agent_trace_spans` | `TraceSpanRecord` | 单步 span：`span_type` ∈ `llm` / `tool` / `step`，含 sequence、延迟、token |
| `agent_trace_events` | `TraceEventRecord` | 离散事件 + payload |
| `agent_trace_artifacts` | `TraceArtifactRecord` | 产物（代码/日志/数据），含 `storage_uri` / `mime_type` |
| `agent_trace_links` | `TraceLinkRecord` | 跨表引用：指向 `chat_tasks` / `workflow_runs` / `ai_conversations` / `ai_messages` / `eval_runs` |

### 一次请求记录了什么

`trace_id` 即 run 的 `uuid4`（`TraceCollector.__init__` 中 `self.run_id = str(uuid4())`），落库时同时写入 `trace_id` 列，全链可由它聚合。每次执行记录：

| 需求 | 记录字段 / 位置 |
|---|---|
| **trace_id** | `run_id = uuid4()`，贯穿 runs/spans/events/links |
| **用户输入** | `input_message` → `input_preview`（截断 2000 字符）；`input_context` 入 `metadata_json` |
| **路由到哪个 Agent** | `agent_type` 字段；handoff 链经 `agent_trace_links` 串联 |
| **调用了哪些工具** | `trace_tool_call()` 上下文管理器记录 `tool_name` / `tool_input` / `tool_output` / `tool_success` / `latency_ms`，落为 `tool` span |
| **模型输入输出** | `trace_llm_call()` 记录每步 `prompt_tokens` / `completion_tokens`；run 级聚合 `tokens_input` / `tokens_output` |
| **耗时** | `total_latency_ms`（wall-clock）+ `llm_latency_ms` / `tool_latency_ms` / `mcp_latency_ms` / `sandbox_latency_ms` 分项，span 级 `latency_ms` |
| **错误** | `error_type`（异常类名）+ `error_message`（截断 500 字符）；失败 span 标 `status="failed"` |
| **成本** | `cost_cny`（Numeric(12,6)），见 [6.4](#64-性能指标) |

> **检索文档（RAG）的现状**：`agent_trace_artifacts` 表已就绪，但当前 Agent 尚未把"检索到哪些文档"作为 artifact 显式记录——RAG 命中信息暂存于 Agent 上下文而非 trace。这是已知缺口，artifact schema 正是为此预留。

时间戳统一用东八区（`tracing.py:_now_china()`，写库时去掉 tzinfo），与 MySQL `default-time-zone=+08:00` 对齐。

### 落库前脱敏（安全红线）

trace 持久化前对所有输入/输出递归脱敏，避免用户在代码或对话里粘贴的密钥落入 trace 表。`tracing.py:_redact_secrets()` 用正则把命中内容替换为 `[REDACTED]`：

```python
_SECRET_PATTERNS = [
    r"sk-[A-Za-z0-9]{20,}",                                  # OpenAI/DeepSeek key
    r"Bearer\s+[A-Za-z0-9._\-]{8,}",                          # bearer token
    r"(?i)(api[_-]?key|secret|token|password|passwd|pwd)\s*[=:]\s*\S+",
    r"eyJ[...]\.[...]\.[...]",                                # JWT
]
```

`input_message` / `response` / `input_context` / 每个 span 的 `tool_input` / `tool_output` 都过这一道。

### Trace 查询接口

- **API** `app/api/v1/agents/traces.py`：`GET /api/traces`（按 agent_type / status / source / eval_run_id / conversation_id / chat_task_id / 时间范围 / 全文检索过滤）、`GET /api/traces/{run_id}`（取单条含全部 span/event/artifact/link）。
- **查询服务** `app/services/trace_query_service.py`：只读，`Decimal → float`、`datetime → ISO8601` 脱形；并做**基于角色的可见性收敛**——学生只能看自己的 trace 且 I/O 被 `redact_io` 置空（详见安全章 5.3）。

---

## 6.2 Evaluation 评测体系

评测体系是当前分支（`complete-traces-evals-plan`）的核心，按 Phase 5–8 分层落地，每条 eval case 都**绑定一条 trace**，质量问题可下钻到具体执行。

### 数据集与用例

`ai/evals/datasets/schema.py` 定义规范化用例，按 `case_type` 分目录存 JSON（`ai/evals/datasets/<case_type>/<suite>.json`）：

| case_type | 用途 |
|---|---|
| `golden` | 必过的黄金集（回归基准） |
| `hidden` | 隐藏集（防止针对性过拟合） |
| `regression` | 历史回归用例 |
| `production_failure` | 线上真实失败回灌 |

`EvalCase` 含 `input`（message / user_id / user_role / agent_type / context）、`graders`（判分器列表）、`budget`、`expected_behavior`。默认预算 `DEFAULT_BUDGET`：

```
max_tokens=2048, max_tool_calls=5, timeout_seconds=90, max_cost_cny=0.25
```

加载由 `ai/evals/datasets/store.py:DatasetStore.load_cases(selector)` 完成，selector 支持 `all` / `<case_type>` / `<case_type>:<suite>`，并兼容旧 `ai/evals/cases/*` 的 legacy shim。

### 判分器（Grader）体系

`ai/evals/graders/base.py:run_grader()` 按 `<family>.<name>` 命名分发到家族实现：

| 家族 | 状态 | 实现 |
|---|---|---|
| `deterministic` | **已实现** | `graders/deterministic.py`，包装 `ai/evals/judges/judges.py:JUDGE_REGISTRY`（18 个确定性 judge） |
| `static_checks` | 预留（Phase 6） | 占位，代码静态检查 |
| `unit_tests` | 预留（Phase 6） | 占位，需沙箱；无沙箱时 `skipped_result()` |
| `llm_judge` | 预留（Phase 6） | 占位，LLM 评分（答案质量/相关性/安全/幻觉） |

`GraderResult` 统一返回 `passed` / `score` / `reason` / `latency_ms` / `cost_cny` / `trace_id`。两种特殊结果区分清晰：`error_result()`（判分器不可用 → 显式失败，阻断用例）与 `skipped_result()`（已知判分器但本次不适用，如无沙箱 → `score=None`，不计入分母也不阻断）。

### 八类质量指标如何对应到判分器

需求中的八项质量指标，当前落地情况如下（确定性 judge 已实现，质量/语义类待 `llm_judge`）：

| 指标 | 当前实现 |
|---|---|
| **回答准确率** | `contains_any` / `response_structure` / `json_schema`（结构与关键词），语义准确率待 `llm_judge` |
| **RAG 命中率** | 暂无专用 judge（trace 未记录检索文档，见 6.1 缺口），规划中 |
| **引用正确率** | 暂无专用 judge，规划入 `llm_judge` |
| **题目生成质量** | `test_case_count` / `has_visible_and_hidden_tests` / `difficulty_appropriate` / `description_quality` / `json_schema(question_schema)` / `solution_length` |
| **代码批改准确率** | `json_schema(review_schema)`（校验 overall_score/summary/issues/strengths 结构），语义正确性待 `llm_judge` |
| **工具调用成功率** | trace 的 `tool_success` + Prometheus `agent_tool_calls_total`，可由 trace 聚合 |
| **幻觉率** | 暂无专用 judge，规划入 `llm_judge` |
| **安全违规率** | `answer_leak` / `no_hidden_test_leak` / `no_system_prompt_leak` / `encouragement_tone`（已实现，对应安全红线） |

> 诚实标注：当前**确定性**（结构/泄露/格式）类已硬覆盖，**语义/质量/幻觉**类依赖尚未接线的 `llm_judge`，故这些维度暂以"显式失败/规划中"占位，不会静默虚高通过率。

### Eval Harness 与失败分类

`ai/evals/harness/eval_harness.py:EvalHarness.run()` 批量驱动：建 `EvalRun` → 每个 case 经 `AgentHarness` 跑出一条 trace（把 `eval_run_id` / `eval_case_id` 绑进 case 的 trace context）→ 回读 trace 的 token/cost/latency → 跑判分器 → 落 `EvalCaseRun` + `EvalCaseGraderResult`。

**软预算**（plan DP-A）：预算在跑完后检查、绝不中断 Agent 循环。`_classify()` 给出 `(status, passed, failure_type)`：

```
agent_error      -> Agent 抛错 / 状态 failed
budget_exceeded  -> tokens 超 max_tokens 或 cost 超 max_cost_cny
timeout          -> duration 超 timeout_seconds
no_graders       -> 用例没配判分器（视为失败，不放行）
grader_failed    -> 有判分器但未全通过
(全通过)          -> passed=True
```

落库统一走 `core.db.session`，无 Flask 依赖，CI 可在临时 SQLite 上跑。

### 报告与回归检测

`ai/evals/reports/generator.py:ReportGenerator.build()` 从持久化的 `EvalRun` / `EvalCaseRun` / `EvalCaseGraderResult` 聚合出 `EvalReport`：

- 质量：`pass_rate`、各判分家族通过率（`grader_pass_rates`，跳过项不计入分母）
- 成本：`total` / `avg` / `p95`（CNY）
- 延迟：`avg` / `p50` / `p95`（ms，最近秩百分位 `_percentile`）
- token：input/output 总量与均值
- 失败画像：`failure_types` 直方图、`top_failed_cases`（含 trace_id 可下钻）
- 回归：给 `compare_to_eval_run_id` 时做 case 级 `detect_regressions` / `detect_new_failures`

`to_markdown()` 产出人读报告，`to_dict()` 供 API/CI 消费。

---

## 6.3 日志与监控

### 日志

- **格式**：核心模块统一 `logger = logging.getLogger(__name__)`；FastAPI Agent Host 在 lifespan 里 `basicConfig`，格式 `%(asctime)s [%(levelname)s] %(name)s: %(message)s`，级别随 `DEBUG` 在 DEBUG/INFO 间切换。
- **关键日志锚点**：trace 落库成功打 `TRACE_SAVE_OK`、失败打 `TRACE_SAVE_FAIL`（ERROR + 堆栈）、成本估算打 `TRACE_COST`（INFO）。
- **审计日志**：`core/observability/audit.py:log_tool_call()` 把工具调用落 `McpAuditLog` 表（与安全章的工具权限审计共用）。
- **落盘**：Docker 下 Flask 日志写 `./logs`（卷挂载 `/app/logs`），Worker 日志走 stdout（Uvicorn ASGI）。

### Metrics（Prometheus）

`core/observability/metrics.py` 是对 `prometheus_client` 的薄封装——**依赖缺失即整体降级为 no-op**，`/metrics` 返回 501，导入该模块永不破坏应用。暴露五条序列：

```
agent_runs_total{agent_type,status}          counter
agent_run_latency_seconds{agent_type}        histogram
agent_tokens_total{agent_type,direction}     counter  (direction=input|output)
agent_cost_cny_total{agent_type,model}       counter
agent_tool_calls_total{agent_type}           counter
```

由 `TraceCollector._emit_metrics()` 在每次 run 结束时经 `record_agent_run()` 推送，独立于 trace 落库（metrics 失败不丢 trace）。用专属 `CollectorRegistry` 隔离全局默认，重复导入（测试）安全。

### 健康检查与监控端点

| 进程 | 端点 | 语义 |
|---|---|---|
| Flask web | `GET /live` | 存活探针，恒 200 |
| Flask web | `GET /health` | 就绪探针：DB 不通 → 503；KB 降级仅上报、**不翻 503**（RAG 退化为空结果，平台仍留在负载均衡内） |
| Flask web | `GET /metrics` | Prometheus 抓取 |
| FastAPI Agent Host | `GET /api/health` | `{status, service, redis, knowledge_base}` |
| FastAPI Agent Host | `GET /live` / `GET /metrics` | 存活 / 指标 |

Compose 中每个服务都配了 healthcheck（mysqladmin ping / redis-cli ping / curl /health / TCP 探测），依赖方用 `condition: service_healthy` 等待。

### 分布式追踪（可选）

`core/observability/otel.py` 提供可选 OpenTelemetry，默认关闭（`OTEL_ENABLED=false`）。开启需装 `opentelemetry-sdk` + `opentelemetry-exporter-otlp`（requirements 中注释）；`init_otel()` 幂等，缺包则告警并返回 False，默认路径零导入成本。

---

## 6.4 性能指标

### Token 与成本计量

trace 的 run 级与 span 级都带 `tokens_input` / `tokens_output` / `cost_cny`。成本由 `core/observability/cost.py:compute_cost_cny()` 按 DeepSeek 每百万 token 定价折算（CNY）：

| 模型 | cached_input | uncached_input | output |
|---|---|---|---|
| `deepseek-v4-flash` | 0.02 | 1.00 | 2.00 |
| `deepseek-v4-pro` | 0.10 | 12.00 | 24.00 |
| `deepseek-v4-pro_discounted` | 0.025 | 3.00 | 6.00 |

要点：

- 定价**配置驱动**，`LLM_PRICING_OVERRIDE`（JSON）可热改而无需改码；坏 JSON 仅告警丢弃，不破坏 tracing。
- 当前 API usage 不总能区分 cache 命中，未知时**全按 uncached 计**（保守偏高），保留 `cached_input_tokens` 参数待 API 暴露明细。
- 别名兼容：`deepseek-chat → deepseek-v4-flash`、`deepseek-reasoner → deepseek-v4-pro`（与 `AIConfig.MODEL` 默认对齐）。
- 未知模型返回 `None`（跳过计费而非给误导数字）。

### 延迟拆分

`total_latency_ms`（`time.monotonic()` 墙钟）下钻为 `llm_latency_ms` / `tool_latency_ms` / `mcp_latency_ms` / `sandbox_latency_ms`，span 级各带 `latency_ms`。聚合后经 Prometheus `agent_run_latency_seconds` histogram 导出，可接 Grafana / 告警。

### 模型分层

`ai/agents/config.py:AIConfig.get_llm(tier)` 委托 ModelRouter 做分层选型（BALANCED / FAST / POWER），不同 tier 的 temperature、max_tokens、限流不同——成本与质量在路由层就可权衡。

---

## 6.5 部署架构

系统是**拆分服务**（非单体），`compose.yaml` 定义 7 个容器，分属两个网络。

| 服务 | 镜像 / 构建 | 端口 | 职责 |
|---|---|---|---|
| `db` | mysql:8.0 | 3306 | 业务 + 长期记忆 + 运行数据（utf8mb4，时区 +08:00） |
| `redis` | redis:7-alpine | 6379 | 缓存 / 限流 / SSE 缓冲 |
| `chroma` | chromadb/chroma:1.5.9 | 8000 | RAG 向量库（关匿名遥测） |
| `web` | `docker/Dockerfile`（Flask） | 9900 | 主应用：Web 页面 + REST API |
| `executor` | `docker/Dockerfile.executor` | 8300 | 代码沙箱（强隔离，见下） |
| `workers` | `docker/Dockerfile.workers`（FastAPI） | 8100 | Agent Host：后台 chat/batch 执行 |
| `mcp_gateway` | `docker/Dockerfile.workers` | 8200 | FastMCP 网关，统一工具调用入口 |

对应需求中的部署清单：`frontend`/`backend-api`（=`web`，Flask 同时渲染页面与 API）、`agent-service`（=`workers`）、`worker`（=`workers` 内的 task_runner 守护）、`database`（=`db`）、`redis`、`vector-db`（=`chroma`）、`object-storage`（当前用卷挂载 `uploads` 卷，未引入独立对象存储）、`monitoring`（=各进程 `/metrics` 暴露的 Prometheus 端点，外部 Prometheus/Grafana 自接）。

### 服务拓扑与信任边界

```
              ┌─────────── educode_network (bridge) ───────────┐
   浏览器 ───▶ web:9900 ──▶ workers:8100 ──▶ mcp_gateway:8200    │
              │   │            │  (EdDSA 签名 capability token)   │
              │   ├──▶ db:3306 ├──▶ redis:6379 ├──▶ chroma:8000   │
              └────────────────────────────────────────────────┘
                                  │
                  executor_network (bridge, internal:true)
                                  ▼
                           executor:8300  ← 仅内网可达，外部不可路由
```

- **沙箱强隔离**：`executor` 跑在 `internal: true` 的独立网络（外部无法路由），并 `read_only` 根文件系统、`cap_drop: ALL`、`no-new-privileges`、非 root（uid 4000）、`mem_limit 512m`、`pids_limit 128`、tmpfs `/tmp`。
- **内部身份**：`workers` 用 Ed25519 私钥（`MCP_INTERNAL_SIGNING_KEY`）对每次工具调用签短时 capability token，`mcp_gateway` 用公钥（`MCP_INTERNAL_VERIFY_KEY`）校验且从不签发——泄露网关配置也无法伪造调用方（详见安全章 5.4）。
- **工具传输**：`MCP_AGENT_TRANSPORT` 默认 `streamable-http`（跨 MCP 走网关），本地可设 `inproc` 在进程内跑工具。

### 镜像加固

`docker/Dockerfile` 基于 `python:3.11-slim`，运行用非 root `appuser`（uid 1000）；HuggingFace 嵌入/重排模型**预打包**进 `/opt/models` 并 `HF_HUB_OFFLINE=1` 强制离线，杜绝运行时下载带来的非确定性与外网依赖。

---

## 6.6 CI/CD 流程

两条 GitHub Actions 流水线，按"是否需要真实 LLM"分工：

### tests.yml —— 每 PR 必过门禁

```
触发：每个 PR + push 到 main/master/develop
环境：内存 SQLite + mock LLM/Redis（conftest），无需任何 secret
步骤：node --check 前端 JS（traces.js / evals.js）→ pytest -q
特性：concurrency 取消同 ref 旧跑；30 分钟超时
```

因为零 secret、确定性、快，适合设为合并的必需状态检查。`FLASK_ENV=testing` 满足 `SECRET_KEY` 启动门禁而不外泄真密钥。

### evals.yml —— 夜间质量/回归门禁

```
触发：每日 02:00 UTC + 手动 workflow_dispatch
环境：真实 DeepSeek API（DEEPSEEK_API_KEY secret，缺失即 fail-fast）
       throwaway SQLite（eval_ci.db），--bootstrap-schema 每次现建 schema
步骤：python -m ai.evals.ci --use-harness --bootstrap-schema \
        --db-url sqlite:///eval_ci.db --selector all \
        --tolerance 0.05 --report-out eval-report.json
产物：eval-report.json / eval-report.md / eval-regressions.json（always 上传）
```

它**不是** PR 必需检查（要花 token）。门禁逻辑在 `ai/evals/ci.py:_run_harness_mode()`：跑 harness → `ReportGenerator` 出报告 → 两条失败条件任一触发即退非零：

1. 存在 case 级回归（`regressions` 非空）；
2. 整体 `pass_rate` 跌破 `baseline - tolerance`（基线 `ai/evals/baseline.json` 按 suite key 存 `min_pass_rate`，默认容忍 5pp）。

基线由 `workflow_dispatch` 带 `update_baseline=true`（→ `--update-baseline`）自校准重写。CI 用 `_bootstrap_eval_schema()` 在单引擎上同时建 Flask `db` 与 core `Base` 两套元数据（镜像 `tests/conftest.py`）——仅 CI/测试便利，生产 schema 由 Alembic 拥有。

---

## 6.7 配置与密钥管理

### 配置体系

| 类 | 文件 | 职责 |
|---|---|---|
| `Settings` | `core/config.py` | 运行时中立配置，`get_settings()` 经 `lru_cache` 单例；`load_dotenv()` 读 `.env`；构造 `DATABASE_URL`（`MYSQL_*` / `DB_*` / `DATABASE_URL` 优先级） |
| `AIConfig` | `ai/agents/config.py` | LLM 配置：`DEEPSEEK_API_KEY` / `MODEL` / `MAX_TOKENS` / `TEMPERATURE` / 限流；`validate()` 校验 key、`get_llm(tier)` 出 LLM 实例 |

关键 env（节选）：

```
认证      SECRET_KEY（生产必设、非默认值）、JWT_SECRET_KEY（HS256，独立于 SECRET_KEY）
数据库    DATABASE_URL 或 MYSQL_*；DB_POOL_SIZE=5、DB_POOL_RECYCLE=3600
LLM      DEEPSEEK_API_KEY、AI_MODEL(deepseek-chat)、AI_MAX_TOKENS=2048、AI_RATE_LIMIT=20、LLM_PRICING_OVERRIDE
可观测    LOG_LEVEL、LOG_FILE、OTEL_ENABLED=false
RAG/向量  CHROMA_MODE=http、CHROMA_HOST、RAG_RERANK_ENABLED=false
Worker   AGENT_HOST_PORT=8100、WORKER_MAX_THREADS=4、MCP_AGENT_TRANSPORT
MCP      MCP_INTERNAL_SIGNING_KEY / MCP_INTERNAL_VERIFY_KEY（Ed25519）、MCP_GATEWAY_URL
```

### 启动门禁（P0）

非 DEBUG 模式下 `SECRET_KEY` 必须设置且非默认占位（`app/__init__.py` / `core/config.py`），否则启动直接 `RuntimeError`——杜绝带默认密钥上生产。

### 密钥管理

- **来源分层**：`.env` 仅供本地/测试（占位值）；生产由环境注入（K8s secret / 环境变量），真密钥不入仓。
- **非对称内部身份**：MCP 内部信任用 Ed25519 私/公钥分离（签发方 `workers` 持私钥、校验方 `mcp_gateway` 持公钥），单边泄露不可伪造。
- **落库脱敏**：见 6.1，所有 trace I/O 落库前过 `_redact_secrets()`，用户误粘的 `sk-` / Bearer / JWT / `password=` 永不进 trace 表。

### 生产加固待办

| 当前 | 建议 |
|---|---|
| Cookie `secure=False` 默认 | 生产置 `secure=True` 跑在 HTTPS 后（见安全章 5.1） |
| JWT 用对称 HS256 | 服务分离后改 RS256 + 公钥分发 |
| `object-storage` 用本地卷 | 上量后引入独立对象存储（S3 兼容） |
| `monitoring` 仅暴露 `/metrics` | 接入外部 Prometheus + Grafana + 告警规则 |
| `llm_judge` / RAG 命中 / 引用 / 幻觉判分未接线 | Phase 6 接 LLM 判分，补齐语义质量维度 |
