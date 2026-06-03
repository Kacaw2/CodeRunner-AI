# 阶段 2 — P2 RAG + 编排 · 详细落地方案 (改动细节)

> 本文是 `2026-05-29-phase-1-4-architecture-hardening-plan.md` 中「阶段 2」的展开版，逐文件给出 before/after、删除/新增清单、回归点与提交顺序。
> 状态：**规划，未执行修改。** 全部代码片段基于当前真实源码核对（2026-05-29）。
> 配套：阶段 1（架构合一）见 `2026-05-29-phase-1-architecture-unification-detailed.md`；Phase 0 安全三项见 `2026-05-29-0329-phase-0-security-hardening-plan.md`（已实现）。
> 依赖关系：阶段 2 的 **2.1（RAG）与 2.2（编排）彼此独立**，且都不依赖阶段 1，可与阶段 1 并行；但 2.1 换 embedder / 加 chunk 字段后**必须清库重建**。

---

## 0. 动手前必须知道的真实现状（阅读真实代码后）

下表纠正了规划概要里几处与真实源码的偏差，是本阶段所有改动的事实基础。

| # | 事实 | 证据 |
|---|------|------|
| A | **语言过滤从来没生效，而且是「静默失败」**。`index_problem` 写入的 metadata 字段名是 `languages`（逗号拼接字符串，如 `"python,java"`），但 `search_similar_problems` 查询用的是 `where={"language": language}`（单数 `language`，且期望精确等值）。字段名不一致 → Chroma 查不到 → 落入裸 `except` 分支**丢掉过滤条件重查**，返回全量结果而无任何报错。 | `store.py:42-47`（写 `languages`）、`store.py:56`（查 `language`）、`store.py:63-67`（静默 except 兜底） |
| B | **没有任何 chunking**。`index_problem` 把 `title\ndescription` 整段编码成**单个向量**；长题面会被 embedder 的上下文窗口截断，召回质量随题面长度劣化。`add_knowledge_point` 同样单向量。 | `store.py:35-36`、`store.py:89` |
| C | **没有任何 rerank**。三个 `search_*` 都是「向量近邻直接返回」，`n` 即最终条数。 | `store.py:50-84`、`103-138`、`151-177` |
| D | **`search_similar_problems` 完全没有 scope 隔离**，而 `search_knowledge` 有 `scope_filter`（`global` ∪ `owner_id`）。更关键：`index_problem` 的 metadata **根本没存 owner/created_by**，所以「加 owner 过滤」必须先在写入侧补字段，否则无字段可滤。 | `store.py:50-84`（无 scope）vs `store.py:103-114`（有 scope）；`store.py:42-47`（写入无 owner） |
| E | **`core/config.py` 没有任何 RAG 配置项**。embedder 模型名 `"all-MiniLM-L6-v2"`、相似度阈值 `0.8`、`n`/`top_k`、chunk 大小全是散落在 `store.py` / `handlers.py` 的字面量。 | `config.py` 全文无 `EMBED`/`RERANK`/`CHUNK`/`TOP_K`；阈值 `0.8` 硬编码于 `handlers.py:121`、`critic.py:76` |
| F | **Critic 没接进引擎**。`WorkflowCritic.validate_step` 存在，但 `engine.py._execute_step` 从不调用它（`engine.py` 未 import `critic`）。step 成功即落库，无质量门。 | `engine.py:359-369`（成功分支无 critic）、`critic.py:114` |
| G | **Critic 字段 + 路由双重错配**。① `validate_generation_output` 读 `output.get("response")`（`critic.py:22`），但生成步 handler 返回的是 `problem_data`（`handlers.py:57`）。② `validate_step` 按 `step_type=="agent_call" and agent_type=="generator"` 路由（`critic.py:116`），但 `GENERATION_TEMPLATE` 的步类型是 `generate_problem`（`planner.py:65`）。两处都对不上 → 即便接进引擎，生成步也会走空。 | `critic.py:22,116`、`handlers.py:57`、`planner.py:65` |
| H | **`REVIEW_TEMPLATE` 两个步定义有 bug**。step1 是 `tool_call` 但**缺 `tool_name`** → `_handle_tool_call` 用空串调 `runtime.call_sync("", ...)` 必失败（`handlers.py:66,82`）。step2 是 `validation` 但**缺 `validates_step`** → `_handle_validation` 的 `target_step` 为 `None`，校验对象退化为 `{}`（`handlers.py:98-99`）。 | `planner.py:114-129`、`handlers.py:61-87,90-99` |
| I | **handoff 不传 context，只换 agent_type**。`detect_handoff` 仅 set `handoff_to`/`handoff_reason` 并剥离标记（`handoff.py:69-72`）。agent invoke 结束时 `state["messages"] = messages`（含 system 残留 + 全部工具消息），下一 agent 再 `[SystemMessage] + list(state["messages"])`（`base.py:227`）→ 工具残骸与上一 agent 的 AIMessage 全量累积传给新 agent。 | `handoff.py:69-72`、`base.py:186-191,227`、`runner.py:160-163` |
| J | `AgentState`（`core/state.py`）已含 `handoff_to`/`handoff_reason`/`previous_agents`，**但无 `handoff_summary`**；`messages` 用 `add_messages` reducer（追加+按 id 去重，不会自动「替换整列」）。 | `core/state.py:1-24` |

---

## 2.1 RAG 修复（`knowledge/store.py` + `core/config.py`）

> **总目标**：让语言过滤真正生效、长文本可 chunk、检索后有 rerank、`search_similar_problems` 具备与 `search_knowledge` 对齐的 owner 隔离，全部可调参数外置到 config。
> **破坏性提示**：改 metadata 字段（语言布尔位、`parent_id`、`created_by`）或换 embedder 都要求**清空 `data/knowledge_base/` 后用 `index_all_problems()` 重建**，否则旧向量缺新字段，过滤会把它们全部漏掉。

### 2.1.0（前置）`core/config.py` 增加 RAG 配置段

在 `Settings` 类里新增一段（紧跟 `AGENT_RATE_LIMITS` 之后即可）：

```python
    # ── RAG / Knowledge Base ────────────────────────────────────
    RAG_EMBED_MODEL: str = os.environ.get("RAG_EMBED_MODEL", "all-MiniLM-L6-v2")
    RAG_RERANK_MODEL: str = os.environ.get(
        "RAG_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
    )
    RAG_RERANK_ENABLED: bool = os.environ.get("RAG_RERANK_ENABLED", "True").lower() in ("true", "1")
    RAG_CHUNK_SIZE: int = int(os.environ.get("RAG_CHUNK_SIZE", "512"))
    RAG_CHUNK_OVERLAP: int = int(os.environ.get("RAG_CHUNK_OVERLAP", "64"))
    RAG_CANDIDATE_K: int = int(os.environ.get("RAG_CANDIDATE_K", "20"))   # rerank 前候选数
    RAG_FINAL_K: int = int(os.environ.get("RAG_FINAL_K", "5"))            # rerank 后返回数
    RAG_DEDUP_THRESHOLD: float = float(os.environ.get("RAG_DEDUP_THRESHOLD", "0.8"))
```
- `KnowledgeBase.__init__` 用 `get_settings().RAG_EMBED_MODEL` 取代字面量 `"all-MiniLM-L6-v2"`（`store.py:21`）。
- `handlers.py:121` / `critic.py:76` 的 `0.8` 改读 `RAG_DEDUP_THRESHOLD`。

### 2.1.1 修语言过滤 bug（事实 A）—— 写布尔位 + 删静默兜底

**写入侧** `index_problem`（`store.py:33-48`）。before：
```python
        languages = [v.programming_language for v in problem.variants] if problem.variants else []
        self.questions.upsert(
            ids=[f"problem_{problem.id}"],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{
                "problem_id": problem.id,
                "languages": ",".join(languages),
                "title": problem.title or "",
                "difficulty": problem.difficulty or "easy",
            }],
        )
```
after（加 `lang_<x>: True` 布尔位；保留 `languages` 字符串供展示；补 `created_by` 见 2.1.4）：
```python
        languages = [v.programming_language for v in problem.variants] if problem.variants else []
        metadata = {
            "problem_id": problem.id,
            "languages": ",".join(languages),
            "title": problem.title or "",
            "difficulty": problem.difficulty or "easy",
            "created_by": getattr(problem, "created_by", 0) or 0,   # 2.1.4
        }
        for lang in languages:
            metadata[f"lang_{lang}"] = True
        self.questions.upsert(
            ids=[f"problem_{problem.id}"],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata],
        )
```

**查询侧** `search_similar_problems`（`store.py:50-67`）。before：
```python
        embedding = self.embedder.encode(query).tolist()
        where = {"language": language} if language else None
        try:
            results = self.questions.query(
                query_embeddings=[embedding],
                n_results=min(n, self.questions.count()),
                where=where,
            )
        except Exception:
            results = self.questions.query(
                query_embeddings=[embedding],
                n_results=min(n, self.questions.count()),
            )
```
after（用布尔位精确过滤；**删掉静默 except**，过滤失败不再悄悄返回全量）：
```python
        embedding = self.embedder.encode(query).tolist()
        clauses = []
        if language:
            clauses.append({f"lang_{language}": True})
        # owner 隔离见 2.1.4
        where = clauses[0] if len(clauses) == 1 else ({"$and": clauses} if clauses else None)
        results = self.questions.query(
            query_embeddings=[embedding],
            n_results=min(n, self.questions.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
```
> 删静默兜底是关键：原 `except` 把「过滤字段不存在」掩盖成「无过滤的成功返回」，正是语言过滤长期失效却无人发现的根因。删除后若 `where` 写错会**显式抛错**，回归阶段立刻暴露。

### 2.1.2 Chunking（事实 B）

新增 `_split_text`（langchain splitter 优先，纯 Python 兜底，参数取自 config）：
```python
    def _split_text(self, text: str) -> list[str]:
        cfg = get_settings()
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=cfg.RAG_CHUNK_SIZE, chunk_overlap=cfg.RAG_CHUNK_OVERLAP,
            )
            return splitter.split_text(text) or [text]
        except Exception:
            size, overlap = cfg.RAG_CHUNK_SIZE, cfg.RAG_CHUNK_OVERLAP
            if len(text) <= size:
                return [text]
            step = max(1, size - overlap)
            return [text[i:i + size] for i in range(0, len(text), step)] or [text]
```
`index_problem` 改为多 chunk upsert，每个 chunk 带 `parent_id`：
```python
        chunks = self._split_text(text)
        embeddings = self.embedder.encode(chunks)
        ids = [f"problem_{problem.id}_chunk_{i}" for i in range(len(chunks))]
        metadatas = []
        for i in range(len(chunks)):
            m = dict(metadata)              # 复用 2.1.1 的 metadata（含 lang_* / created_by）
            m["parent_id"] = f"problem_{problem.id}"
            m["chunk_index"] = i
            metadatas.append(m)
        self.questions.upsert(ids=ids, embeddings=[e.tolist() for e in embeddings],
                              documents=chunks, metadatas=metadatas)
```
检索后**按 `parent_id` 聚合取最高分**（在 2.1.3 rerank 之前先折叠 chunk）：同一 `parent_id` 的多个 chunk 命中只保留分数最高的一条，避免一道题因多 chunk 占满 top_k。

> 注意：`search_similar_problems` 现按 `problem_id` 去重输出；chunk 化后必须改为按 `parent_id` 去重，且 `n_results` 要放大到 `RAG_CANDIDATE_K`（因为一道题会产生多条 chunk 候选）。

### 2.1.3 Rerank（事实 C）

新增 `_rerank`（CrossEncoder；不可用或关闭时按向量 score 退化）：
```python
    def _rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        cfg = get_settings()
        if not cfg.RAG_RERANK_ENABLED or not candidates:
            return candidates
        try:
            if not hasattr(self, "_reranker"):
                from sentence_transformers import CrossEncoder
                self._reranker = CrossEncoder(cfg.RAG_RERANK_MODEL)
            pairs = [(query, c.get("content") or c.get("text_preview", "")) for c in candidates]
            scores = self._reranker.predict(pairs)
            for c, s in zip(candidates, scores):
                c["rerank_score"] = float(s)
            return sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)
        except Exception as e:
            logger.warning("Rerank unavailable, falling back to vector score: %s", e)
            return sorted(candidates, key=lambda c: c.get("score", 0), reverse=True)
```
检索流程改为：`query(n=RAG_CANDIDATE_K)` → 按 `parent_id` 折叠 → `_rerank` → 截 `RAG_FINAL_K`。`search_knowledge` 同样接入（topic+content 作为候选文本）。`sentence-transformers` 已在依赖（`store.py:14` 已 import），不引新依赖。

### 2.1.4 `search_similar_problems` 的 owner 隔离（事实 D）

前提：2.1.1 已在 `index_problem` metadata 写入 `created_by`。
- **先验证** `Problem` 模型确有 `created_by` 字段（`app/models/problem.py`）；若字段名不同（如 `author_id`/`teacher_id`）以真实为准，否则 `getattr(..., 0)` 会恒为 0、过滤失效。
- 给 `search_similar_problems` 增加 `owner_id: int | None = None` 形参，与 `search_knowledge` 对齐：
```python
    def search_similar_problems(self, query, n=5, language=None, owner_id=None):
        ...
        clauses = []
        if language:
            clauses.append({f"lang_{language}": True})
        if owner_id:
            clauses.append({"$or": [{"created_by": owner_id}, {"created_by": 0}]})  # 0 = 公共题库
        where = clauses[0] if len(clauses) == 1 else ({"$and": clauses} if clauses else None)
```
- 调用方 `handlers.py:_handle_dedup_check`（`handlers.py:116-120`）补传 `owner_id=context.get("user_id")`（去重应只查本人题库 + 公共库）。

### 2.1 测试连带 / 新增
- 新增 `tests/test_rag_filter.py`：① 索引两道题分别 `python`/`java`，`search_similar_problems(q, language="python")` 只返回 python；② 不传 language 返回全部；③ owner A 的题不出现在 owner B（无 0）的检索里。
- 新增 `tests/test_rag_chunk_rerank.py`：长题面切多 chunk 后仍按 `parent_id` 去重；rerank 关闭/异常时退化排序不报错。
- 现有依赖 `search_similar_problems` 的测试若断言「返回全量」要按真实过滤语义改写。

---

## 2.2 编排修复（`graph/`）

### 2.2.1 Critic 接入 `engine.py`（事实 F + G）

**先修字段/路由错配（事实 G），否则接进去也走空。**

`critic.py:19-22` `validate_generation_output` before：
```python
    def validate_generation_output(self, output: dict) -> dict:
        issues = []
        problem = output.get("response", "")
```
after（兼容 `problem_data` 与 `response`）：
```python
    def validate_generation_output(self, output: dict) -> dict:
        issues = []
        problem = output.get("problem_data") or output.get("response", "")
```

`critic.py:114-124` `validate_step` before：
```python
        if step_type == "agent_call" and agent_type == "generator":
            return self.validate_generation_output(output)
        if step_type == "agent_call" and agent_type == "reviewer":
            return self.validate_review_output(output)
```
after（把模板用的 `generate_problem`/`quality_review` 步类型也纳入路由）：
```python
        if agent_type == "generator" or step_type == "generate_problem":
            return self.validate_generation_output(output)
        if agent_type == "reviewer" or step_type in ("agent_call", "quality_review"):
            return self.validate_review_output(output)
```

**再接进引擎。** `engine.py._execute_step` 成功分支（`engine.py:359-369`）before：
```python
                db_step.status = "completed"
                db_step.output_data = output
                db_step.completed_at = now_china()
                session.commit()

                state["step_outputs"][db_step.step_index] = output
                self._emit("step_completed", {...})
                return True
```
after（成功后过 critic；不过则消耗一次 retry 并把反馈注入 context 供下一 attempt 用）：
```python
                from graph.critic import WorkflowCritic
                criteria = step_def.get("validation_criteria", "")
                verdict = WorkflowCritic().validate_step(
                    step_type, db_step.agent_type, output, criteria)

                if not verdict.get("passed", True) and attempt < max_attempts - 1:
                    last_error = "; ".join(verdict.get("issues", [])) or "critic rejected output"
                    context["critic_feedback"] = last_error      # 下一 attempt 的 handler 可读取
                    logger.info("Step %d rejected by critic (attempt %d): %s",
                                db_step.step_index, attempt + 1, last_error)
                    self._emit("step_critic_rejected", {
                        "step_index": db_step.step_index, "issues": verdict.get("issues", [])})
                    continue   # 进入下一次 attempt

                db_step.status = "completed"
                db_step.output_data = {**output, "critic": verdict}
                db_step.completed_at = now_china()
                session.commit()
                state["step_outputs"][db_step.step_index] = output
                self._emit("step_completed", {"step_index": db_step.step_index,
                                              "latency_ms": latency,
                                              "critic_score": verdict.get("score")})
                return True
```
- retry 耗尽仍不过：保持现有「成功落库」语义但带上 `critic` 结果（不强制 fail，避免把「质量一般」误判成「执行失败」）。是否升级为硬失败留作策略开关，先观测。
- `critic_feedback` 的消费：生成步 handler `_handle_generate_problem`（`handlers.py:17`）可在 `system_parts` 里追加 `context.get("critic_feedback")`，让重试带着上一轮缺陷提示。

### 2.2.2 修 `REVIEW_TEMPLATE`（事实 H）

`planner.py:105-130` before：
```python
REVIEW_TEMPLATE: list[WorkflowStepDef] = [
    { "step_index": 0, "step_type": "agent_call", "agent_type": "reviewer",
      "instruction": "Perform code review and identify issues",
      "risk_level": "low", "requires_approval": False },
    { "step_index": 1, "step_type": "tool_call", "agent_type": "reviewer",
      "instruction": "Execute code to verify it runs correctly",
      "risk_level": "medium", "requires_approval": False },
    { "step_index": 2, "step_type": "validation", "agent_type": "reviewer",
      "instruction": "Validate review completeness and scoring",
      "risk_level": "low", "requires_approval": False },
]
```
after（step1 缺 `tool_name` → 改 `agent_call`；step2 缺 `validates_step` → 补）：
```python
REVIEW_TEMPLATE: list[WorkflowStepDef] = [
    { "step_index": 0, "step_type": "agent_call", "agent_type": "reviewer",
      "instruction": "Perform code review and identify issues",
      "risk_level": "low", "requires_approval": False },
    { "step_index": 1, "step_type": "agent_call", "agent_type": "reviewer",
      "instruction": "Execute the code to verify it runs and report failures",
      "risk_level": "medium", "requires_approval": False },
    { "step_index": 2, "step_type": "validation", "agent_type": "reviewer",
      "instruction": "Validate review completeness and scoring",
      "validates_step": 0,
      "risk_level": "low", "requires_approval": False },
]
```
> 备选：若确实想让 step1 跑真工具，则保留 `tool_call` 并补 `"tool_name": "coderunner.code.execute_internal"` + `tool_args`。但 reviewer 经 agent 内部已能调执行工具，改 `agent_call` 更简单且无审批阻塞（`execute` 是 HIGH）。
> `validates_step` 已被 `_handle_validation` 读取（`handlers.py:98`），是 `WorkflowStepDef` 的扩展字段；如要类型严格，可在 `state.py:WorkflowStepDef` 增加 `validates_step: int` 与 `validation_criteria: str`（`total=False` 不影响旧步）。

### 2.2.3 handoff 传 context（事实 I + J）

**目标**：handoff 切 agent 时，丢弃上一 agent 的工具残骸与中间 AIMessage，只把「原始用户问题 + 上一 agent 结论摘要」交给新 agent。

**改动 1** `state.py`：`AgentState` 增加字段
```python
    handoff_summary: str
```

**改动 2** `handoff.py`：`detect_handoff` 命中后生成摘要
在 `handoff.py:69-72` set `handoff_to` 之后追加：
```python
    state["handoff_to"] = target
    state["handoff_reason"] = reason
    cleaned = HANDOFF_PATTERN.sub("", response).rstrip()
    state["final_response"] = cleaned
    # 结论摘要：上一 agent 的可见回答（剥离 handoff 标记），截断防爆长
    state["handoff_summary"] = cleaned[:1500]
```

**改动 3** `runner.py`：切 agent 前重建 messages
`_check_handoff`（`runner.py:160-163`）当前只换 `agent_type`。改为在 reroute 前重置 `messages`：
```python
    from langchain_core.messages import HumanMessage, RemoveMessage
    # 找回最初的用户问题（messages 里第一条 Human）
    original = next((m for m in state.get("messages", [])
                     if isinstance(m, HumanMessage)), None)
    summary = state.get("handoff_summary", "")
    rebuilt = []
    if original is not None:
        rebuilt.append(original)
    if summary:
        rebuilt.append(HumanMessage(
            content=f"[上一助手({current_agent})的结论摘要]\n{summary}\n\n请基于此继续处理用户的原始请求。"))

    # add_messages 是「追加+按 id 去重」，不会自动替换整列：
    # 先用 RemoveMessage 清空旧消息，再写入重建后的列表
    removals = [RemoveMessage(id=m.id) for m in state.get("messages", []) if getattr(m, "id", None)]
    state["messages"] = removals + rebuilt

    state["agent_type"] = handoff_to
    state["handoff_to"] = None
    state["handoff_reason"] = None
    state["handoff_summary"] = None
    return handoff_to
```
> **`add_messages` 叠加陷阱（事实 J）**：直接 `state["messages"] = rebuilt` 在 LangGraph 里**不会替换**旧消息，reducer 会把 `rebuilt` 追加到既有列表后 → 工具残骸照样留着。必须用 `RemoveMessage(id=...)` 显式删除旧消息（需保证消息带 `id`；LangChain 消息默认有，自造的 HumanMessage 也会补）。这是本改动最易踩的回归点，务必单测验证「新 agent 收到的 messages 长度==重建后的条数」。
> 流式路径 `_stream_with_mcp_tools`（`base.py:303-309`）也会 `detect_handoff`，但实际 reroute 仍由 `runner._check_handoff` 统一处理，重建逻辑只需放在 runner 一处。

### 2.2 测试连带 / 新增
- `tests/test_agent_features.py:308-350` 的 `detect_handoff` 用例：补断言命中后 `state["handoff_summary"]` 非空且不含 `[HANDOFF:` 标记。
- 新增 `tests/test_handoff_context.py`：构造「tutor 跑完带工具消息 → 触发 handoff 到 reviewer」，断言 reviewer 收到的 `messages` 只含 [原始 Human + 摘要 Human]，不含 ToolMessage / 上一 AIMessage。
- 新增 `tests/test_workflow_critic.py`：① 生成步返回缺 `test_cases` 的 `problem_data` → critic 判 `passed=False` 并消耗 retry；② `REVIEW_TEMPLATE` 端到端跑通（step1 不再因空 tool_name 失败、step2 validates_step=0 拿到真实对象）。

---

## 3. 回归验证步骤

1. **RAG 重建**：清空 `data/knowledge_base/`，跑 `index_all_problems()`，确认无异常、metadata 含 `lang_*` / `parent_id` / `created_by`。
2. **语言过滤**：`pytest tests/test_rag_filter.py -x`，重点验证「删静默 except 后，`where` 写错会显式抛错」而非悄悄返回全量。
3. **chunk + rerank**：`pytest tests/test_rag_chunk_rerank.py -x`；关闭 `RAG_RERANK_ENABLED` 跑一遍确认退化路径不报错。
4. **去重门**：跑一轮 generation 工作流，制造一道与库中高相似题，断言 `dedup_check` 命中 `is_duplicate=True` 且只在本人/公共题库范围内查。
5. **Critic 门**：`pytest tests/test_workflow_critic.py -x`；观察 `step_critic_rejected` 事件在缺字段时出现、补全后消失。
6. **REVIEW 模板**：用 review 类目标跑 `create_plan` → `WorkflowEngine.execute`，三步全部 `completed`（旧版 step1/step2 会 failed/走空）。
7. **handoff 上下文**：`pytest tests/test_handoff_context.py -x`，断言新 agent 的 `messages` 条数 == 重建条数（验证 `RemoveMessage` 生效、无残骸累积）。
8. **端到端冒烟**：经 `task_runner` 跑 tutor→reviewer 的真实 handoff 一轮，人工确认 reviewer 回答未被上一轮工具输出污染。

---

## 4. 建议提交顺序（每步可独立回滚）

```
C1  2.1.0 config RAG 段 + embedder/阈值改读 config        （纯新增，行为不变）
C2  2.1.1 语言过滤 bug：写布尔位 + 删静默兜底 + 单测       （需清库重建）
C3  2.1.4 owner 隔离（依赖 C2 的 created_by 写入）+ 单测
C4  2.1.2 chunking + 2.1.3 rerank（依赖 C2 的写入改造）   （需清库重建）
C5  2.2.2 REVIEW_TEMPLATE 修复（独立、低风险，先合）
C6  2.2.1 critic 字段/路由修复 + 接入 engine + 单测
C7  2.2.3 handoff 上下文重建（state/handoff/runner）+ 单测（RemoveMessage 回归点）
```

**关键依赖**：
- C2 必须先于 C3/C4（owner 与 chunk 字段都写在 `index_problem`，且都要求清库重建——C2、C4 各自重建一次，或合并重建）。
- C6 的「接入 engine」必须在「字段/路由修复」之后，否则生成步 critic 恒走空。
- C7 的 `RemoveMessage` 行为是最大回归点，单独提交并配 `test_handoff_context.py`。

**最高 ROI**：2.1.1（语言过滤）+ 2.2.3（handoff 上下文）——前者修一个「静默失效、召回长期被污染」的隐性 bug，后者消除「跨 agent 上下文污染」这一最影响多 agent 协作质量的问题。2.2.2 改动最小、可最先合入热身。

**与阶段 1 的并行**：2.1 / 2.2 都不碰 `tools/protocol` 与 `mcp_gateway`，可与阶段 1 的合一改造并行开发；唯一交叉点是 `handlers.py:_handle_tool_call` 经 `runtime.call_sync`——若阶段 1 改了 scope/校验，跑 REVIEW/generation 工作流回归时一并验证即可。
