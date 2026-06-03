# 工具与知识模块：Tools、MCP、RAG

最后更新：2026-06-03

本文按当前真实代码状态说明 CodeRunner-AI 的工具调用、MCP gateway、RAG 知识库、文档处理、向量检索和权限控制。判断依据以源码为准，重点入口包括 `core/definitions.py`、`agents/base.py`、`agents/executor.py`、`tools/protocol/`、`mcp_gateway/`、`knowledge/store.py`、`tools/knowledge_search/search.py`、`app/api/v1/ai.py` 和根目录 `compose.yaml`。

## 3.1 Tool 调用体系

当前工具调用已经是 MCP-native 边界：Agent 不直接 import 业务工具实现，也不直接执行 `ToolRuntime`。真实链路是：

```text
LLM
  -> OpenAI-compatible function schema
  -> Agent BaseAgent tool loop
  -> ToolCallExecutor
  -> MCPToolClient
  -> MCP transport（生产）或 InProcessMCPToolClient（本地/测试）
  -> mcp_gateway FastMCP wrapper
  -> ToolRuntime
  -> guard pipeline
  -> LocalTransport handler
  -> app/service/tool implementation
```

同步和流式 Agent 都走 `BaseAgent._invoke_with_mcp_tools()` / `_stream_with_mcp_tools()`。`BaseAgent` 先从 `ToolRuntime.list_tools(names=...)` 取当前 Agent 白名单对应的 descriptor，再用 `tools/protocol/adapters/tool_to_llm.py` 转成 LLM 可见的 function schema。模型最多进行 `MAX_TOOL_ITERATIONS = 5` 轮工具调用；每条工具调用都会进入 `ToolCallExecutor`。

`agents/base.py` 还兼容旧式 `<function>...</function>` 文本工具调用，但只在解析出的工具名能映射到当前 Agent 白名单时才转换成真实 tool call。这个逻辑是为了兼容模型输出形态，不是新的授权入口。

### 当前 canonical tools

| 工具类别 | Canonical tool | 主要用途 | 当前实现入口 |
|---|---|---|---|
| Problem | `coderunner.problem.get_detail` | 查询题目详情和测试用例 | `tools/problems/queries.py` |
| Submission | `coderunner.submission.list_for_student` | 查询学生近期提交 | `app.services.submission_service` |
| Submission | `coderunner.submission.get_detail` | 查询单次提交详情 | `app.services.submission_service` |
| Student | `coderunner.student.get_summary` | 查询学生画像和统计摘要 | `tools/students/summary.py` |
| Problem write | `coderunner.problem.save_generated` | 保存 AI 生成题目草稿 | `tools/problems/write.py` |
| Code | `coderunner.code.execute` | 执行任意用户/外部代码 | `tools/code/executor.py` |
| Code internal | `coderunner.code.execute_internal` | Generator 自验证参考解 | `tools/code/executor.py` |
| Knowledge | `coderunner.knowledge.search` | 检索课程知识点 | `tools/knowledge_search/search.py` |
| Knowledge | `coderunner.knowledge.search_similar_problems` | 检索相似题 | `tools/knowledge_search/search.py` |
| Knowledge | `coderunner.knowledge.search_error_patterns` | 检索常见错误模式 | `tools/knowledge_search/search.py` |
| Analytics | `coderunner.analytics.student_activity` | 查询学生提交活动时间线 | `tools/analytics/queries.py` |
| Analytics | `coderunner.analytics.student_stats` | 查询教师维度统计 | `app.services.teacher_stats_service` |
| Analytics | `coderunner.analytics.class_statistics` | 查询班级统计 | `tools/analytics/queries.py` |
| Analytics | `coderunner.analytics.problem_difficulty` | 查询题目难度统计 | `tools/analytics/queries.py` |
| Trace | `coderunner.trace.get_agent_trace` | 查询 Agent trace | `tools/traces/queries.py` |
| Approval | `coderunner.approval.check` | 查询 human gate 审批状态并取回结果 | `mcp_gateway/bootstrap.py` |

### 内部工具、MCP 暴露工具和 Agent 专用工具

所有工具都在 `tools/protocol/schemas/catalog.py` 的 `TOOL_CATALOG` 中声明 descriptor，并由 `mcp_gateway/tool_map.py` 映射到外部 FastMCP 名称。也就是说当前“通过 MCP 暴露”的 surface 由 `EXTERNAL_TOOL_MAP` 决定，`mcp_gateway/server.py` 会断言实际注册工具集合与该 map 完全一致。

需要区分三层含义：

| 类型 | 当前工具 | 说明 |
|---|---|---|
| 内部业务实现 | `tools/problems/*`、`tools/code/*`、`tools/knowledge_search/*`、`tools/analytics/*`、`tools/traces/*` | 这些是 Python handler/service，不允许 Agent 直接调用；只能被 `ToolRuntime` 后端 dispatch。 |
| MCP surface | `search_knowledge`、`execute_code`、`save_generated_problem` 等外部名 | 由 `mcp_gateway/generated_tools.py` 注册到 FastMCP；内部 agent 和外部 API-key client 都经过同一 surface。 |
| 内部专用工具 | `coderunner.code.execute_internal` / `execute_internal` | 已注册在 MCP surface，方便内部 Agent 通过 gateway 调用；但 descriptor 标记 `internal_only=True`，外部 client 即使有 scope 也会被 guard 拒绝。 |
| Agent 专用能力 | `core/definitions.py` 中各 Agent 的 `allowed_tools` | LLM 只能看到当前 Agent 白名单工具；`ToolAllowlistHook` 会在跨 MCP client 前再次阻断白名单外工具。 |

## 3.2 Tool Registry 设计

当前 registry 是 descriptor-driven 设计：

- `tools/protocol/schemas/catalog.py` 是 canonical source，声明工具名、版本、输入 schema、输出 schema、risk level、required scopes、approval policy、timeout、server 和 `internal_only`。
- `tools/protocol/registry.py` 的 `ToolRegistry` 只保存 descriptor 和 server health，不包含业务执行逻辑。
- `mcp_gateway/bootstrap.py` 启动时创建新的 `ToolRegistry` 和 `LocalTransport`，把 `TOOL_CATALOG` 全量注册进去，再把 canonical tool name 绑定到具体 handler。
- `ToolRuntime.call()` 是 server-side 执行入口，顺序执行 input schema 校验、guard、参数身份覆盖、transport handler、output schema warn-only 校验和 audit。

Descriptor 里的 input schema 是强约束：参数不符合 schema 会返回 `MCP_ARGUMENT_INVALID`。Output schema 目前是 warn-only，避免 catalog 输出定义未完全收敛时把已有工具结果变成硬失败。

Registry 本身不是权限边界。权限边界在 Agent 白名单、MCP 身份、scope/RBAC/risk guard 和参数覆盖。

## 3.3 MCP 模块设计

当前 MCP 模块由三部分组成：

| 模块 | 入口 | 职责 |
|---|---|---|
| MCP client | `mcp_gateway/client.py` | Agent 侧工具调用适配器，提供 `InProcessMCPToolClient` 和 `StreamableHTTPMCPToolClient`。 |
| MCP gateway | `mcp_gateway/server.py`、`generated_tools.py`、`middleware/` | FastMCP server，注册工具和 prompt resources，解析 caller，限流并进入 `ToolRuntime`。 |
| ToolRuntime | `tools/protocol/runtime.py` | Gateway 后端执行引擎，负责 schema、guard、身份参数覆盖、audit、approval 和 handler dispatch。 |

生产部署里，`compose.yaml` 配置 `workers` 默认使用：

```text
MCP_AGENT_TRANSPORT=streamable-http
MCP_GATEWAY_URL=http://mcp_gateway:8200/mcp
```

这意味着 Agent Host 每次工具调用都会通过 `StreamableHTTPMCPToolClient` 跨 HTTP MCP transport 到 `mcp_gateway`。Agent Host 使用 `MCP_INTERNAL_SIGNING_KEY` 生成短期 EdDSA capability token，gateway 用 `MCP_INTERNAL_VERIFY_KEY` 校验。token claims 包含 `user_id`、`role`、`agent_type`、`scopes`、`task_id`、`conversation_id`、`trace_id`；gateway 只信任签名 claims，不信任 LLM 参数或普通 header 自报身份。

本地/测试路径在未设置 `MCP_AGENT_TRANSPORT` 或设置为 `inproc` 时使用 `InProcessMCPToolClient`。它不跨真实 transport，但仍把 `ToolRuntime` 依赖限制在 client 模块内部，Agent 代码不直接执行工具。

### MCP 暴露范围

工具 surface 由 `mcp_gateway/tool_map.py` 定义，包括知识库、题目、提交、学生摘要、代码执行、analytics、trace、保存生成题目和审批检查。

MCP resource 当前只暴露只读 prompt 资源：

- `prompt://agents/{agent}`
- `prompt://addenda/security`
- `prompt://addenda/handoff`

RAG 知识库内容没有作为 MCP resource 直接暴露；必须通过 `search_knowledge`、`search_similar_problems`、`search_error_patterns` 这类工具检索，并经过工具权限链路。

## 3.4 RAG 知识库设计

RAG 由 `knowledge/store.py` 管理，底层是 ChromaDB + sentence-transformers。当前 collection 有三类：

| Collection | 数据来源 | 用途 | 当前主要访问者 |
|---|---|---|---|
| `questions` | 业务库 `Problem` + variants 元数据，通过 `index_all_problems()` / `/api/v1/ai/knowledge/index` 索引 | 相似题检索、生成题去重参考 | `GeneratorAgent`、`coderunner.knowledge.search_similar_problems` |
| `knowledge_points` | `scripts/seed_knowledge.py` 内置知识点、教师通过 `/api/v1/ai/knowledge/add` 新增 | 课程知识点 RAG | `TutorAgent`、`coderunner.knowledge.search`、教师知识库页面 |
| `error_patterns` | `scripts/seed_knowledge.py` 内置 CE/RE/WA/TLE 错误模式、教师新增 error pattern | 常见错误诊断 | `TutorAgent`、`coderunner.knowledge.search_error_patterns` |

Docker 部署中 Chroma 是独立服务 `chroma`，web/workers/mcp_gateway 都配置：

```text
CHROMA_MODE=http
CHROMA_HOST=chroma
CHROMA_PORT=8000
```

本地隔离测试可传 `persist_dir` 给 `KnowledgeBase`，此时直接创建 `chromadb.PersistentClient`，不会修改全局 settings。

### RAG 数据从哪里来

当前没有通用外部文档库。RAG 数据来源只有这些：

1. 业务题库：`Problem.title` + `Problem.description`，加上 variants 的语言、难度、创建者等 metadata。
2. 内置种子：`scripts/seed_knowledge.py` 的 `ERROR_PATTERNS` 和 `KNOWLEDGE_POINTS`。
3. 教师端新增：`POST /api/v1/ai/knowledge/add` 写入知识点或错误模式。
4. 启动后台任务：当 Flask config `ENABLE_KB_STARTUP_INDEX=True` 时，`app/__init__.py` 会后台执行题目索引和知识种子填充。
5. 手动索引：`POST /api/v1/ai/knowledge/index` 触发全量题目索引。

## 3.5 文档处理流程

当前代码里的“文档处理”是轻量文本处理，不是完整文件 ingestion pipeline。

### 已实现

题目索引流程：

```text
Problem row
  -> text = title + "\n" + description
  -> _split_text()
  -> SentenceTransformer.encode(chunks)
  -> Chroma questions.upsert(ids, embeddings, documents, metadatas)
```

`KnowledgeBase._split_text()` 优先使用 `langchain_text_splitters.RecursiveCharacterTextSplitter`，配置来自：

- `RAG_CHUNK_SIZE`，默认 `512`
- `RAG_CHUNK_OVERLAP`，默认 `64`

如果 langchain splitter 不可用，会退回纯 Python 字符窗口切分：步长为 `chunk_size - overlap`。每个 problem 会生成 `problem_{id}_chunk_{i}`，metadata 包含 `parent_id`、`chunk_index`、`problem_id`、`languages`、`lang_<language>`、`title`、`difficulty`、`created_by`。

重建索引时会先按 `parent_id` 删除旧 chunk，避免短文档重建后残留旧尾部 chunk。

### 当前没有实现

当前没有看到以下通用文档处理能力：

- PDF / DOCX / Markdown / HTML 上传解析。
- OCR、表格抽取、文件版本管理。
- 文档级 ACL、文档空间、文件 hash 去重。
- 多段文档摘要、引用定位、source citation 输出。

因此在对外描述时应写成“题库与教学知识点的轻量 RAG”，不要写成完整生产级文档知识库。

## 3.6 检索与重排序

### 相似题检索

`search_similar_problems(query, n, language, owner_id)` 流程：

1. 对 query 生成 embedding。
2. 组装 Chroma where filter：
   - `language` 存在时过滤 `lang_<language> = True`。
   - `owner_id` 存在时只允许 `created_by = owner_id` 或 `created_by = 0` 的公共题。
3. 取 `max(n, RAG_CANDIDATE_K)` 个候选，默认候选数 `20`。
4. 按 `parent_id` 折叠 chunk，只保留每个 problem 的最佳 chunk。
5. 可选 cross-encoder rerank。
6. 返回前 `n` 个结果，并移除内部 `content` 与 `_distance` 字段，只保留 `text_preview` 等摘要字段。

### 知识点检索

`search_knowledge(query, n, scope_filter)` 默认返回结构化知识点结果，包括 `topic`、`category`、`content`、`distance`、`similarity`、`score`。当传入 `scope_filter.owner_id` 时，只检索：

- `scope = global`
- `owner_id = 当前用户`

API 层 `/api/v1/ai/knowledge/search` 对非 admin 用户会自动设置当前用户的 `owner_id` scope filter；admin 不加该过滤。

### 错误模式检索

`search_error_patterns(query, n)` 查询 `error_patterns` collection，返回 `error_type`、`content`、`distance`、`score`。当前错误模式没有 owner scope，主要作为全局教学诊断材料。

### 重排序

`KnowledgeBase._rerank()` 由 `RAG_RERANK_ENABLED` 控制，默认关闭。打开后会加载 `RAG_RERANK_MODEL`，默认 `cross-encoder/ms-marco-MiniLM-L-6-v2`，对 `(query, candidate_content)` 预测 rerank 分数并降序排序。reranker 不可用或抛错时，会降级为按向量相似度排序。

Tutor 直接预取 RAG 时还有一层业务过滤：`TutorAgent.MIN_KNOWLEDGE_SCORE = 0.3`，低分知识点和错误模式不会注入 tutor system context。

## 3.7 工具权限控制

权限控制分为 API、Agent、MCP、ToolRuntime、RAG metadata 五层。

### API 层

| 能力 | 当前保护 |
|---|---|
| AI chat / review / conversation / knowledge stats / knowledge search | `@require_auth` |
| generator、eval run、知识库 index/seed/add/delete、MCP key 管理 | `@require_teacher` |
| MCP API key 创建/列出/吊销 | `app/api/v1/mcp_keys.py`，teacher/admin only |

### Agent 层

`core/definitions.py` 同时定义 Agent 可访问角色和工具白名单：

| Agent | 可访问角色 | 工具白名单 | RAG 访问 |
|---|---|---|---|
| `tutor` | student、teacher、admin | code execute、problem detail、submission list/detail、knowledge search、error pattern search | 直接预取知识点和错误模式，也可通过 MCP 工具检索 |
| `reviewer` | student、teacher、admin | code execute、problem detail | 不直接访问 Chroma，白名单也无知识库工具 |
| `generator` | teacher、admin | internal code execute、similar problems、save generated problem | 直接预取相似题，也可通过 MCP 工具检索相似题 |
| `analytics` | student、teacher、admin | problem detail、submission list/detail、student stats/activity、class stats、problem difficulty | 不直接访问 Chroma；主要使用业务统计工具和 memory context |

`ToolAllowlistHook` 在工具调用跨 MCP client 前检查工具是否在当前 Agent 白名单内。LLM 也只会拿到白名单工具 schema。

### MCP / ToolRuntime 层

`tools/protocol/policies/guard.py` 的顺序是：

```text
internal_only
  -> RBAC
  -> scope
  -> risk / approval
```

当前关键规则：

- `internal_only=True` 的工具只允许 `actor_type="agent_host"`。外部 API-key client 无论 scope 如何都不能调用 `execute_internal`。
- RBAC role override 保护 teacher/admin 专用工具，例如 `student_stats`、`class_statistics`、`problem_difficulty`、`get_agent_trace`、`get_student_summary`、`save_generated_problem`。
- scope 对所有 caller 生效，包括内部 agent。内部 agent 的 scope 由 `scopes_for_agent(agent_type)` 从白名单工具的 `required_scopes` 推导，不存在 agent_host scope bypass。
- `HIGH` 风险且 `approval_policy != NONE` 的工具会返回 `approval_required`，进入 human gate。当前 `coderunner.code.execute` 和 `coderunner.problem.save_generated` 都需要 teacher approval。
- `MEDIUM` 风险工具学生不能用；`execute_internal` 是 `MEDIUM + internal_only`，给 generator 自验证使用。

`ToolRuntime._sanitize_args()` 会删除 LLM 或外部参数中的 `user_id`、`user_role`、`role`、`teacher_id`、`student_id`，再按可信 caller 身份写回：

- student caller 注入 `student_id = caller.user_id`
- teacher caller 注入 `teacher_id = caller.user_id`
- 所有 caller 注入 `_caller_user_id` 和 `_caller_role`

这防止模型或外部 client 通过参数伪造学生/教师身份。

### 外部 API Integration

当前外部集成有三类：

1. LLM provider：`models/providers/deepseek.py` 使用 `langchain_openai.ChatOpenAI` 兼容接口调用 DeepSeek，`DEEPSEEK_API_KEY` 必须配置。
2. MCP external client：教师/admin 通过 `/api/v1/mcp/keys` 创建 API key，key 存 hash、role、scope、rate limit；gateway 每次请求验证 bearer token、scope、RBAC 和速率限制。
3. 基础设施 API：Chroma 可通过 HTTP client 访问独立 `chroma` 服务；代码执行工具最终调用本地/远程 executor 实现，Docker 中 executor 在 internal network 隔离。

### 防止越权访问的组合策略

当前防线不是单点：

1. Web/API 路由先限制谁能管理知识库、生成题目和创建 MCP key。
2. Router 只允许角色进入可用 Agent，例如 student 不能进入 generator。
3. LLM 只绑定当前 Agent 白名单工具。
4. `ToolAllowlistHook` 阻断白名单外 tool call。
5. Gateway 只信任签名 internal token 或数据库中的 MCP API key。
6. `ToolRuntime` 强制 internal-only、RBAC、scope、risk/human gate。
7. `ToolRuntime._sanitize_args()` 覆盖身份参数，避免参数伪造。
8. RAG 检索使用 metadata filter 限制 teacher scoped 知识点和 owner scoped 题目可见性。
9. trace/student summary 等敏感结果在 gateway handler 中经过 sanitizer 后返回。

## 当前边界结论

1. Tools 的 canonical source 是 `TOOL_CATALOG`，不是 scattered `@tool` 函数。
2. MCP gateway 是生产工具边界；`ToolRuntime` 是 gateway 后端执行引擎，不是 Agent 直接 API。
3. 内部工具实现和 MCP surface 已分离；外部名通过 `EXTERNAL_TOOL_MAP` 映射 canonical tool。
4. `execute_internal` 是内部 Agent 专用自验证工具，虽然注册在 MCP surface，但外部 caller 被 `internal_only` guard 拒绝。
5. RAG 当前是题库 + 知识点 + 错误模式三类 collection，不是通用文档知识库。
6. 文档切分只发生在 problem 级文本索引；知识点和错误模式是短条目直接 embedding。
7. 检索使用 Chroma cosine distance、候选扩大、chunk parent collapse、可选 cross-encoder rerank 和 metadata scope filter。
8. 越权防护依赖 API auth、Agent allowlist、MCP identity、scope/RBAC/risk guard、参数覆盖和 RAG metadata filter 的组合。
