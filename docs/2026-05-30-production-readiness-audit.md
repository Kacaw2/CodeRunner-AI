# CodeRunner-AI 生产级架构评估报告

**评估日期:** 2026-05-30
**分支:** `codex/phase-1-architecture-unification`
**系统:** FastAPI + MCP 多智能体编程教学平台
**方法:** 12 层 Agent 架构审计 + 代码级取证(关键结论已逐条核验到 file:line)

> 说明:并行探查中有两处初判被读码纠正——(1) "scope 未强制"是**错的**,实际在 `tools/protocol/policies` 已代码级强制;(2) "X-MCP 头可被任意伪造"**不准确**,实际需持有共享内部令牌。报告以核验后的结论为准。

---

## 一、执行结论(Executive Verdict)

| 维度 | 完成度 | 生产就绪 |
|---|---|---|
| Host / 编排(graph) | 85% | ✅ 基本就绪 |
| MCP Server | 80% | ✅ 就绪 |
| MCP Transport | 75% | ⚠️ 默认 stdio,生产入口需固化 |
| MCP Client(内部 agent) | 70% | ⚠️ 共享令牌越权风险 |
| Tools | 90% | ✅ 就绪 |
| RAG / 知识库 | 70% | ⚠️ 运行时下模型、单机、init 易脆 |
| Prompt | 65% | ⚠️ 硬编码、未版本化 |
| Resources(MCP) | 0% | ❌ 未实现 |
| 可观测性(traces/metrics) | 50% | ❌ 无 metrics 导出/无健康检查/无成本 |
| 评测体系(evals) | 60% | ❌ 未接 CI、无基线、judge 未校准 |

**总体健康度:`MEDIUM RISK`。** 核心链路(编排→MCP→工具→RAG)是真实可运行、code-gated 的,不是 prompt 摆设——这点优于多数同类项目。但**对外暴露/多租户/敌对网络前**,有 3 个必须先修的硬伤:内部令牌越权、可观测性不可外接、评测无 CI 门禁。

**最紧急的一项:** 内部共享令牌可冒充任意用户/角色并绕过 scope(见 F1)。

---

## 二、按严重度排序的发现

### 🔴 CRITICAL

**F1 — 内部共享令牌 = 全量身份冒充 + scope 绕过**
- **机制:** 持有 `MCP_INTERNAL_AUTH_TOKEN`(单个静态共享密钥)的任何进程,可在 `X-MCP-*` 头里**自填** `user_id` / `role`(含 admin/teacher)/ `agent_type`,网关原样信任(`core.py:86-104`);且 `actor_type=="agent_host"` 在 `scopes.py:19-20` **直接跳过 scope 校验**,`call_via_runtime` 对 agent_host 也不传 `granted_scopes`(`core.py:157-167`)。
- **层:** Layer 6/7(工具鉴权)+ 内部信任边界
- **根因:** 内部信任用"单一静态密钥 + 未签名的自声明身份",且 scope 旁路只看 `actor_type` 字符串。
- **证据:** `mcp_gateway/middleware/core.py:76-124,157-167`、`tools/protocol/policies/scopes.py:19-20`
- **残余防护(已具备):** 需先持有该密钥;每请求身份隔离(`finally` 清理)正确;有内部限流。
- **修复:** 改为每 agent 独立密钥 + 请求 HMAC 签名(对 user_id/role/agent_type/timestamp 签名,网关校验);`role` 不可由 agent 自填越权;给 agent_host 也下发**最小必要 scope**,移除"actor_type 即放行"。

### 🟠 HIGH

**F2 — 可观测性无法对接任何监控栈,且无健康检查**
- 全部为自研 trace 落库(`core/observability/tracing.py`),**无 OpenTelemetry、无 Prometheus `/metrics`、无结构化日志 sink、无 `/health` `/live`**。token 已采集但**从未换算成本**。
- **影响:** 生产中无法被 Grafana/Datadog/K8s 探针接管;故障与成本不可观测。
- **证据:** `core/observability/tracing.py:1-159`、`app/api/public/metrics.py`(仅业务计数,非系统/agent 指标)
- **修复:** 加 `/health`+`/metrics`(Prometheus),agent loop 注入 OTel span,补成本换算。
- **正面:** trace 入库前已做密钥脱敏(`tracing.py:133-159`,`_redact_secrets`),这点是合格的。

**F3 — 无任何 CI:测试与评测都不在门禁内**
- `.github/` 仅 `CODEOWNERS`,**无 workflows**(已核实)。pytest 与 589 条 eval 用例全靠手动跑;agent 质量回归对生产不可见。
- **证据:** `.github/` 仅 `CODEOWNERS`;`evals/runner.py` 仅经 teacher-only API 触发
- **修复:** 加 `tests.yml` + `evals.yml`,PR 合并前强制;eval 设基线,低于基线即 fail。

**F4 — 代码执行存在双路径,可能绕过网关审计/审批**
- 生成器在本地直调 `execute_code_impl`,同时又有 agent→MCP 网关路径;本地路径会绕过网关的审批门与审计。
- **证据(中等置信,建议复核):** `agents/generator/agent.py` 内 `_validate_solution` 直调 vs `agents/base.py:_run_mcp_tool`
- **修复:** 统一所有代码执行走 MCP 网关单一边界。
- **正面:** 执行器本身是 fail-closed 的(沙箱不可用即返回 `EXECUTOR_UNAVAILABLE`,不回退到不安全的进程内执行,`app/services/executor_service.py:49-87`)——设计正确。

### 🟡 MEDIUM

**F5 — MCP Resources 完全未实现**
- 只有 tools,无 MCP `resources`(网关无 resource 注册)。文档/题目模板/提示等静态资源只能经工具中转,无法按 MCP 资源协议暴露。属能力缺口,非缺陷。
- **证据:** `mcp_gateway/` 无 `resource` 注册;`server.py` 仅注册生成的 tools

**F6 — RAG 运行时下载模型 + 单机 + init 易脆**
- `all-MiniLM-L6-v2` 首次调用时从 HuggingFace **运行时下载**(`knowledge/store.py:21`);ChromaDB 单机落盘无副本;init 失败 fail-fast(最近一次提交刚改成打全 traceback,说明此处确实踩过坑)。
- **修复:** 镜像内预置模型(离线缓存)、启动期健康校验、KB 不可用时的降级契约。
- **证据:** `knowledge/store.py:12-31,180-189`

**F7 — Prompt 硬编码、未版本化**
- 4 个 agent 的 system prompt 为模块级常量字符串,工具名/scope 硬编码进文案,无模板化、无版本/回滚。注入防护是 19 条正则(`core/security.py:6-28`)——能挡常见模式,但对混淆/同形字/编码绕过无覆盖。
- **修复:** prompt 外置 + 版本号 + 变更审计;注入防护补编码归一化。

**F8 — 审批执行处理器对新增高危工具会静默失败**
- `bootstrap.py:_execute_approved_tool` 仅硬编码 `execute_code`、`save_generated_problem` 两个;新增高危工具若不同步登记,审批通过后执行会失败。
- **证据:** `mcp_gateway/bootstrap.py:210-228`

**F9 — 跨 MCP 边界前缺输入值校验**
- 有 JSON Schema 类型校验(`runtime.py:209-220`),但无业务值域校验(如 `problem_id:-9999` 可穿透到 runtime)。

### 🟢 LOW
- `MAX_WORKFLOW_STEPS=10` 静默截断用户计划,无告警(`graph/engine.py:21`)。
- 工具/agent 层无独立限流(仅网关层有)。
- eval judge 阈值(描述≥50 字符、代码≤8 行等)为拍脑袋值,无人工校准/无 LLM-as-judge。

---

## 三、架构诊断

这套系统的**底子是扎实的**,和"prompt 里写了必须用工具、代码里却不强制"的典型烂摊子相反:

- **工具纪律是 code-gated 的真货** —— `runtime.py:127 → run_guard()` 按 `rbac → scope → risk` 顺序强制(`guard.py:32-36`),scope 不足抛 `MCPScopeDenied`,高危工具抛 `MCPApprovalRequired`。这是审计里最该有、却最常缺的一层,这里有。
- **调用方身份每请求隔离正确**,descriptor 驱动生成工具包装并自动剥离/注入 caller 字段(防 API key 持有者冒充他人 user_id),设计意识到位。
- **真正的薄弱点集中在"信任边界"和"运维面":** 内部信任用了过于粗糙的共享密钥+自声明身份(F1);而运维面(metrics/health/CI/eval 门禁)几乎空白——系统"能跑",但"跑坏了你不会知道,跑回归了 CI 不会拦"。

一句话:**功能完成度高(可发内测),运维与信任边界成熟度低(不可贸然对外/多租户)。**

---

## 四、有序修复计划(code-first)

| 序 | 目标 | 为何现在做 | 预期效果 |
|---|---|---|---|
| 1 | **F1** 内部令牌改 per-agent 密钥 + HMAC 签名,role 不可自升,agent_host 下发最小 scope | 唯一的越权/冒充通道 | 关闭关键信任边界 |
| 2 | **F3** 建 CI:`tests.yml` + `evals.yml`,eval 设基线门禁 | 没有它,后续所有修复都可能被回归悄悄推翻 | 锁住质量与回归 |
| 3 | **F2** 加 `/health`+`/metrics`(Prometheus)、OTel span、成本换算 | 上线前必须可观测 | 可被监控栈接管 |
| 4 | **F4** 统一代码执行走 MCP 单一边界 | 消除审计/审批旁路 | 单一可信执行路径 |
| 5 | **F6** 镜像预置 embedding 模型 + 启动期 KB 健康校验 | 消除运行时下载/单点 init 失败 | RAG 启动确定性 |
| 6 | **F8/F9** 审批处理器改为按 descriptor 动态分发 + 补值域校验 | 防新增高危工具静默失败 | 边界收敛 |
| 7 | **F7/F5** prompt 外置版本化;按需补 MCP resources | 可维护性/能力补全 | 长期演进 |

---

## 五、统一执行顺序(跨 plan 主干 · 2026-05-30 重排)

> 本节是全仓库所有活跃 plan 的**唯一执行主干**。已合并:本审计 F1–F9 + `2026-05-29-phase-2-rag-orchestration-detailed.md`(RAG/编排真 bug)。已完成的 Phase 0/1 详细方案见 `archive/plans/`;`2026-05-29-phase-1-4-architecture-hardening-plan.md` 的 Phase 3/4 已并入本表,不再单独执行。

```
【信任边界 — 已基本关闭】
S0  F1 内部令牌签名化 ............ ✅ 已完成(commit 12854c5),仅需补 Docker 双容器 smoke

【上线前必做 — 运维面空白(最高优先)】
S1  F3  建 CI: tests.yml + evals.yml + eval 基线门禁   ← 先做,后续修复的回归网
S2  F2  /metrics(Prometheus) + OTel span + 成本换算 + 健康探针固化
S3  F4  统一代码执行走 MCP 单一边界(消除 generator 本地直调旁路)

【产品质量 bug — 可与 S1–S3 并行(不碰 tools/protocol)】
S4  Phase2.1 RAG: 修语言过滤 bug(lang_ 布尔位)+ 删静默 except + owner 隔离  ← 清库重建
S5  Phase2.2 编排: handoff 传 context(RemoveMessage)+ critic 接入 engine + 修 REVIEW_TEMPLATE

【边界收敛 — 中危】
S6  F8 审批处理器按 descriptor 动态分发 + F9 跨边界值域校验
S7  Phase3.1 拆 execute_internal(MEDIUM)解执行死锁 + output_schema 校验

【长期演进 — 低优先】
S8  F6 镜像预置 embedding 模型 + 启动期 KB 健康校验
S9  F7 prompt 外置版本化 + 注入防护补编码归一化 / F5 MCP resources / Phase4.2 Agent 契约
```

**关键依赖**:S1(CI) 必须最先;S4 改 metadata 字段需清空 `data/knowledge_base/` 重建;S5 的 `RemoveMessage` 是最大回归点(LangGraph `add_messages` 叠加陷阱),单独提交配测试。
