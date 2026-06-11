# Agent Loop 深度审查报告

**审查日期:** 2026-06-08
**范围:** `ai/agents/runtime.py`(`run`/`stream`)、`ai/agents/executor.py`、`ai/agents/llm_runner.py`、`ai/agents/config.py`、`core/exceptions.py` 的重试装饰器、`ai/memory/service.py` 的 `compact_messages`
**目标:** 聚焦 agent 执行循环本身,找出缺点、不足,并对标 Codex / Claude Code 的能力差距

> 本报告所有论断均逐行核验上述源码。它是 `2026-06-08-sandbox-and-harness-review.md` 中 Harness 部分的深化,专门下钻到循环骨架。

---

## 一、循环骨架的结构性缺陷

agent loop 有 `run()`(同步,`ai/agents/runtime.py:143`)和 `stream()`(流式,`ai/agents/runtime.py:215`)**两份几乎平行的实现**,逻辑重复又有细微不一致,是后续问题的放大器。

| # | 严重度 | 问题 | 证据 |
|---|---|---|---|
| L-1 | P1 | **工具调用纯串行,无并行调度**:`for tc in response.tool_calls` 逐个执行,即使多个工具互不依赖也串行,跑完整批才进下一轮 LLM。结构上无任何并发原语 | `runtime.py:185`、`runtime.py:306` |
| L-2 | P1 | **无单工具超时**:`executor.run()` → `call_tool()` 无 timeout 包裹,工具/网关卡住则整个 trace 无限阻塞,流式无 keep-alive | `runtime.py:190/309`、`executor.py:63` |
| L-3 | P2 | **LLM 中途失败被静默吞掉并伪装成功**:非首轮 `LLMError` 直接 `break`,随后用上一轮 `response.content` 当 `final_response` 返回且 `finalize_trace(status="completed")`。用户拿到被截断却标记"成功"的回答,trace 状态失真。这是正确性 bug | `runtime.py:162-165`、`runtime.py:206`;流式 `runtime.py:267` |
| L-4 | P2 | **流式/非流式 limit 判定不一致**:`run()` 循环耗尽时 `limit_exceeded = bool(response and response.tool_calls)`;`stream()` 则无条件 `True`。同一对话刚好用满迭代时,两条路径给出相反结论(一个正常返回、一个报 `AgentExecutionLimitError`) | `runtime.py:194-195` vs `runtime.py:315-316` |

---

## 二、循环对上下文预算完全无感知

| # | 严重度 | 问题 | 证据 |
|---|---|---|---|
| L-5 | P1(最致命) | **循环无 token 预算概念**:迭代上限只有消息轮数(`max_tool_iterations` 默认 5)和 LLM 调用次数(`MAX_LLM_CALLS_PER_TRACE=12`),无任何 token 维度。`extract_usage` 在调用后才拿 token,纯统计、不参与决策。压缩仅在入口做一次,循环内消息只增不减(每轮 append response + 每工具 append ToolMessage),一个大 JSON 工具结果即可撑爆上下文而循环毫不知情 | `config.py:18`、`llm_runner.py:35`、`runtime.py:120/173/192` |
| L-6 | P2 | **工具结果不摘要/不截断直接回灌**:`json.dumps(data)` 把工具完整输出塞回 messages,无大小上限。配合 L-5 是上下文炸弹直接来源 | `executor.py:84` |

**对标:** Codex/Claude Code 的循环核心即 token 预算驱动(实时统计、临界自动压缩、工具大结果落盘后按需重读)。本项目是"轮数驱动",属架构代差,也是最该补的一项。

---

## 三、循环内被退化掉的能力

| # | 严重度 | 问题 | 证据 |
|---|---|---|---|
| L-7 | P2 | **压缩一次性、有损、可能更糟**:`compact_messages` 仅循环外触发一次;LLM 压成 max 200 字摘要,失败则退化为每条截前 100 字符拼接,丢工具 id/中间结构。固定窗口 `messages[1:-20]`,所有 agent 同值,无 per-agent 调节 | `memory/service.py:151-196`、`runtime.py:120` |
| L-8 | P3 | **重试用字符串匹配判定**:`retry_on_llm_error` 靠 `str(e).lower()` 含 `timeout/502/rate_limit` 等关键词决定是否重试;provider 改措辞即漏判。仅重试 2 次、退避 ~2-4s,不读 `Retry-After`、无 jitter、不区分 429/503 | `core/exceptions.py:75-110` |
| L-9 | P3 | **工具报错后循环无策略**:失败返回错误 envelope,循环照常继续,完全交给 LLM 自处理。无 error budget、无 fail-fast、无"同工具连续失败即停" | `executor.py:92-97` |
| L-10 | P3 | **approval_required 不暂停循环**:审批信息被当普通 ToolMessage 喂回,循环继续。无"挂起-等人工-恢复"机制,审批语义靠模型自觉 | `executor.py:85-91` |

---

## 四、与 Codex / Claude Code 的差距汇总

| 循环能力 | 本项目 | Codex / Claude Code | 差距 |
|---|---|---|---|
| 并行工具调用 | 无,纯串行 | 默认并行无依赖调用 | **代差** |
| Token 预算驱动 | 无,仅轮数/调用次数 | 实时 token 预算 + 临界压缩 | **代差** |
| 单工具超时/取消 | 无 | 每调用独立超时 + 取消 | **大** |
| 大工具结果处理 | 全量回灌 | 落盘 + 按需重读 | **大** |
| 失败语义正确性 | 静默吞掉伪装成功(L-3) | 明确错误 + 可恢复 | **大** |
| 循环内动态压缩 | 仅入口一次性有损压缩 | 循环内持续治理 | **中-大** |
| 重试策略 | 字符串匹配 2 次 | 结构化错误码 + Retry-After + jitter | 中 |
| 子任务隔离上下文 | handoff 只传摘要 | 子 agent 独立上下文回传 | 中-大 |
| 流式/非流式一致性 | 两份实现有行为分叉(L-4) | 单一循环 | 中 |

---

## 五、按性价比排序的修复建议

1. **统一两份循环**:把 `run`/`stream` 收敛成一个核心生成器循环,消除 L-4 分叉与重复维护。
2. **引入 token 预算**(最高价值):每轮调用前用 `extract_usage` 累计值估算剩余预算,临界时循环内压缩或停止,补上 L-5/L-6 代差。
3. **工具层加超时 + 并发**:`call_tool` 包 timeout;无依赖 tool_calls 用线程池/异步并发(L-1/L-2)。
4. **修静默失败**:L-3 中途 LLM 失败必须 `status="failed"` 或显式 partial 标记,绝不标 `completed`。
5. **工具结果摘要/截断 + 失败预算**(L-6/L-9):大结果折叠,连续失败 fail-fast。
6. 重试改结构化错误判定 + 读 `Retry-After`(L-8)。

---

## 六、总评

这个 loop 是**功能正确但朴素的 ReAct 串行循环**:能跑通 happy path,但缺现代 agent harness 三大核心(token 预算驱动、工具并行、可恢复失败语义)。其中 **L-3(静默失败伪装成功)是正确性 bug**,**L-1/L-5 是与 Codex/Claude Code 的真正代差**,应优先处理。
