# 沙箱与 Agent Harness 审查报告

**审查日期:** 2026-06-08
**范围:** 代码执行沙箱、AI Agent 工具沙箱(MCP 权限)、Agent Harness(执行引擎/编排循环)
**目标:** 找出缺点、不足,并对标 Codex / Claude Code 的能力差距

> 本报告是某个时间点的审查结论。关键论断已逐行核验代码;其余从模块级走查得出,标注了证据位置。未解决项请同步回 `README.md` 索引表。

---

## 一、代码执行沙箱(学生提交代码)

**职责:** 运行不可信的学生 C/Python 代码并判题,是真正面对恶意代码的边界。

### 已有隔离(已核实)

容器层加固在 `compose.yaml:153-183` 的 `executor` 服务:

| 控制项 | 配置 | 证据 |
|---|---|---|
| 网络完全隔离 | `executor_network` + `internal: true` | `compose.yaml:325` |
| 只读根文件系统 | `read_only: true` | `compose.yaml:167` |
| 非 root 运行 | `user: "4000:4000"` | `compose.yaml:166` |
| 内存上限 512m | `mem_limit: 512m` | `compose.yaml:170` |
| 进程数上限 128 | `pids_limit: 128` | `compose.yaml:171` |
| 能力清空 | `cap_drop: ALL` | `compose.yaml:172` |
| 禁止提权 | `no-new-privileges:true` | `compose.yaml:174` |
| 临时内存盘 | `tmpfs /tmp size=128m` | `compose.yaml:168` |

进程层 RLIMIT 在 `app/core/executor.py:91-124`:CPU 时间、`RLIMIT_AS` 虚拟内存、`RLIMIT_FSIZE` 文件大小 + `subprocess` 超时。fail-closed 设计良好:web 容器默认不设 `EXECUTOR_ALLOW_NATIVE`,本地原生执行默认拒绝;远端不可用返回 `EXECUTOR_UNAVAILABLE` 而非降级裸跑。

### 不足

| # | 严重度 | 问题 | 证据 |
|---|---|---|---|
| S-1 | P2 | **无 seccomp / AppArmor**(全项目无配置)。`cap_drop: ALL` 挡能力但不收窄 syscall 攻击面,内核 0-day 提权面未收敛。这是本沙箱最该补的一项 | `compose.yaml` 无 `security_opt: seccomp=` |
| S-2 | P3 | `RLIMIT_NPROC` 被移除("防止 fork 失败"),fork 炸弹仅靠 `pids_limit:128` 兜底。建议设合理上限而非完全去掉 | `app/core/executor.py:120` |
| S-3 | P3 | gcc 编译器直接对学生代码运行,编译阶段先于 RLIMIT 生效,存在编译器漏洞利用面(实际风险低) | `app/core/executor.py:220-223` |

**评级:B+** —— 容器隔离 + 断网 + fail-closed 已达生产级判题沙箱合格线,主要短板是缺 seccomp。

---

## 二、AI Agent 工具沙箱(MCP 权限系统)

**职责:** 约束四个 agent 能调用哪些工具。威胁模型是"LLM 被诱导越权",非"运行恶意机器码"。

### 已有纵深防御

1. 声明式白名单:每 agent 的 `allowed_tools` 写死在 `core/definitions.py`;`generator` 仅 teacher/admin、risk=high、速率 5/min。
2. In-process Hook 拦截:`ToolAllowlistHook` 在 `BEFORE_TOOL_CALL` 跨 MCP 边界前拒绝表外工具(`ai/agents/hooks.py`)。
3. RBAC + Scope + Risk 三道 guard(`ai/tools/protocol/policies/`):高危工具要求 teacher 审批,中危工具对 student 拒绝。
4. 身份字段净化:`_sanitize_args` 剥离 LLM 自带 `user_id/role/student_id`,按真实身份回填。
5. 能力令牌:mcp_gateway 用 Ed25519 公钥验证内部 capability token,网关只验不签(`compose.yaml:201-204`),配置泄露也无法伪造调用者。
6. 错误不外泄:runtime 异常只回通用错误码,堆栈进日志不进 envelope。

### 不足

| # | 严重度 | 问题 |
|---|---|---|
| A-1 | P2 | 白名单纯静态(硬编码 Python dataclass),改策略需重新部署,无运行时策略引擎,无法按会话收紧 |
| A-2 | P2 | 缺强制审计日志:Hook 仅失败时记日志,无"全部工具调用(含参数)"的不可变审计流,事后取证困难 |
| A-3 | P3 | 审批仅靠统一过期时间,无法按工具配置时长 |

### 关键交叉点

两套沙箱共用同一底层执行器:agent 的 `code.execute_internal` 和学生的 `code.execute` 最终都走 `ExecutorService.run_code` → 远端 executor 容器。维护统一,但 executor 任何 bug 会同时影响两个威胁模型。

**评级:B** —— 纵深防御与身份净化到位,差运行时策略 + 审计日志。

---

## 三、Agent Harness(执行引擎)

> 更正:此前曾有"没有真正用 LangGraph"的说法,经核验**不成立**。`ai/graph/runner.py:215-245` 有真实 `StateGraph`(route→agent→respond,带 handoff/retry 条件边并 `compile()`),`ai/workers/generation_pipeline.py` 也是真 StateGraph。真正问题是**双轨编排并存**(见 H-7)。

### 核心循环已核实的硬伤

核心循环在 `ai/agents/runtime.py:143-213`,是规范 ReAct 迭代,但:

| # | 严重度 | 问题 | 证据 |
|---|---|---|---|
| H-1 | P2 | **工具调用纯串行**:即使 LLM 一次返回多个 tool_calls 也逐个执行,本轮全跑完才重新调 LLM,无并行 | `ai/agents/runtime.py:185` |
| H-2 | P2 | **无单工具超时**:`self._executor.run(tc, ...)` 无 per-call timeout,工具卡住拖垮整轮 | `ai/agents/runtime.py:190` |
| H-3 | P2 | **LLM 失败静默截断**:第 0 轮失败才抛出,之后任意轮失败直接 `break`,把半成品当最终结果返回,用户看不出被截断 | `ai/agents/runtime.py:162-165` |
| H-4 | P3 | 迭代上限双重写死(`max_tool_iterations` 默认 5 + `MAX_LLM_CALLS_PER_TRACE=12`),命中即返回固定错误,无压缩后重试的降级 | `ai/agents/config.py` |
| H-5 | P3 | 工具报错不影响循环:错误 envelope 照样 append 继续,无 error budget、无 fail-fast | `ai/agents/executor.py:74-97` |

### 与 Codex / Claude Code 的差距

| 维度 | 本项目 | Codex / Claude Code | 差距 |
|---|---|---|---|
| 上下文管理 | 固定 20 条后整段 LLM 摘要,失败截前 100 字符;**调用前无 token 计数**;所有 agent 同阈值 | 实时 token 预算、自动 compaction、工具结果按需折叠/重读 | **大** |
| 工具结果处理 | 完整 JSON 直接塞回 messages,无摘要无截断,大输出污染上下文 | 大结果落盘/分页,按需 grep/read | **大** |
| 并行 & 子 agent | 工具串行;handoff `MAX_HANDOFFS=2` 且只传"原始问题+摘要",中间工具结果不传递 | 并行工具、可派发并行子 agent、独立上下文回传 | **大** |
| 错误恢复 | LLM 重试仅 2 次指数退避;无熔断;无单工具超时;流式不可取消 | 细粒度超时、可取消、工具级重试、熔断 | 中 |
| 流式 | token 流式 OK,但工具执行阻塞流,无 keep-alive,工具进度不可见 | 工具调用/结果实时穿插,长任务有心跳 | 中 |
| 提示词 | 各 agent 自建 system prompt,无统一模板;无 few-shot;**无 prompt caching** | 结构化系统提示 + prompt caching | 中-大 |
| 可观测 & 成本 | trace 收集 token 但**不算钱**;handoff 链路**无父子 span 关联** | 端到端 span、跨 agent 关联、实时成本核算 | 中 |
| 规划 | supervisor + planner,但 `should_use_workflow()` 是关键词硬匹配("生成/批量/然后"),脆弱 | 模型自主规划 + 动态 todo + 自我修正 | 中 |

### 两个结构性问题

- **H-6(上下文是最大短板):** 整个 harness 无"调用前 token 预算"概念。Codex/Claude Code 的核心竞争力恰在上下文工程(动态压缩、工具结果按需重读、子 agent 隔离上下文)。本项目"20 条 + 整段摘要"粗粒度方案,长对话/大工具输出下快速劣化。**拉开差距第一位。** 证据:`ai/memory/service.py:151-196`、`ai/agents/runtime.py:120`。
- **H-7(双轨编排,职责不清):** LangGraph 路径 `ai/graph/runner.py` `AgentOrchestrator`(非流式 invoke)与命令式路径 `ai/graph/handoff.py` `stream_with_handoffs`(流式 while + `MAX_HANDOFFS`)并存,路由/handoff 语义/状态重建各写一份,易行为不一致、难维护。

---

## 四、按性价比排序的改进建议

1. **上下文工程**(最高优先):引入调用前 token 预算 + 工具结果摘要/折叠,替换"20 条硬阈值"。(对应 H-6、A 区上下文)
2. **加 prompt caching**:DeepSeek 兼容接口支持,系统提示+记忆缓存可直接省钱降延迟。(H 提示词)
3. **并行工具调用 + 单工具超时**:改 `ai/agents/runtime.py:185` 循环,无依赖 tool_calls 并发跑。(H-1、H-2)
4. **修静默截断**:`ai/agents/runtime.py:162-165` 中途失败给用户明确信号。(H-3)
5. **给 executor 容器加 seccomp profile + 给 NPROC 设上限**。(S-1、S-2)
6. **补全工具调用结构化审计日志 + 收敛双轨编排 + 跨 agent span 关联 + 成本核算**。(A-2、H-7)

---

## 五、总评

- 代码执行沙箱:**B+**(差 seccomp)
- Agent 工具沙箱:**B**(差运行时策略 + 审计日志)
- 安全/权限/审批层比执行引擎成熟;与 Codex/Claude Code 的差距集中在**上下文工程、并行化、prompt caching** 三项,其中上下文管理是决定性短板。
