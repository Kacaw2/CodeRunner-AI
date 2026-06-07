当前代码里的 RAG 是“题库 + 教学知识点 + 错误模式”的轻量 RAG，不是通用文档知识库。

**Chunking**
`questions` collection 会 chunk：索引的是 `Problem.title + "\n" + Problem.description`。优先用 `RecursiveCharacterTextSplitter`，默认 `RAG_CHUNK_SIZE=512`、`RAG_CHUNK_OVERLAP=64`；失败时退回纯 Python 字符窗口切分，步长是 `size - overlap`。每个 chunk ID 是 `problem_{id}_chunk_{i}`，并带 `parent_id`、`chunk_index`、`problem_id`、语言、难度、创建者等 metadata。重建索引前会按 `parent_id` 删除旧 chunk，避免残留。见 [knowledge/store.py](C:/Users/libie/Desktop/program/CodeRunner-AI/knowledge/store.py:102)。

`knowledge_points` 和 `error_patterns` 基本不是 chunking pipeline：知识点按 `topic: content` 做一条 embedding，错误模式按 `error_type + description + explanation` 做一条 embedding。见 [knowledge/store.py](C:/Users/libie/Desktop/program/CodeRunner-AI/knowledge/store.py:231) 和 [knowledge/store.py](C:/Users/libie/Desktop/program/CodeRunner-AI/knowledge/store.py:290)。

**Embedding**
用 `sentence-transformers` 的 `SentenceTransformer`，默认模型是 `all-MiniLM-L6-v2`，可通过 `RAG_EMBED_MODEL` 改。query、problem chunks、knowledge point、error pattern 都走同一个 embedder。见 [core/config.py](C:/Users/libie/Desktop/program/CodeRunner-AI/core/config.py:65) 和 [knowledge/store.py](C:/Users/libie/Desktop/program/CodeRunner-AI/knowledge/store.py:96)。

**Vector DB**
用 ChromaDB。当前默认 `CHROMA_MODE=http`，Docker 里是独立 `chroma` 服务，镜像 `chromadb/chroma:1.5.9`，web/workers/mcp_gateway 通过 `CHROMA_HOST=chroma`、`CHROMA_PORT=8000` 访问。也保留 `persistent` 模式和测试用 `persist_dir`。三个 collection 都配置 HNSW cosine：`questions`、`knowledge_points`、`error_patterns`。见 [knowledge/store.py](C:/Users/libie/Desktop/program/CodeRunner-AI/knowledge/store.py:9)、[knowledge/store.py](C:/Users/libie/Desktop/program/CodeRunner-AI/knowledge/store.py:34)、[compose.yaml](C:/Users/libie/Desktop/program/CodeRunner-AI/compose.yaml:47)。

**Retrieval**
相似题检索：query embedding 后查 `questions`，可按 `lang_<language>` 过滤，也可按 `created_by=owner_id OR created_by=0` 做 owner 隔离；先取 `max(n, RAG_CANDIDATE_K)`，默认候选 20；然后按 `parent_id` 折叠 chunk，只保留每道题距离最小的 chunk；最后可选 rerank，返回前 n 个，并移除内部 `content` 和 `_distance`。见 [knowledge/store.py](C:/Users/libie/Desktop/program/CodeRunner-AI/knowledge/store.py:175)。

知识点检索：query embedding 后查 `knowledge_points`，如果有 owner scope，只返回 `scope=global` 或当前 owner 的内容；返回 `topic/category/content/distance/similarity/score`，再可选 rerank。见 [knowledge/store.py](C:/Users/libie/Desktop/program/CodeRunner-AI/knowledge/store.py:248)。

错误模式检索：query embedding 后直接查 `error_patterns` top n，返回 `error_type/content/distance/score`，当前没有走 candidate_k 和 rerank。见 [knowledge/store.py](C:/Users/libie/Desktop/program/CodeRunner-AI/knowledge/store.py:301)。

**Reranker**
有 cross-encoder rerank，但默认关闭：`RAG_RERANK_ENABLED=False`。开启后懒加载 `CrossEncoder`，默认模型 `cross-encoder/ms-marco-MiniLM-L-6-v2`，对 `(query, candidate_content)` 预测分数并降序排序；失败时 fallback 到向量 similarity 排序。见 [knowledge/store.py](C:/Users/libie/Desktop/program/CodeRunner-AI/knowledge/store.py:156) 和 [core/config.py](C:/Users/libie/Desktop/program/CodeRunner-AI/core/config.py:66)。

**Agent / Tool 接入**
RAG 不作为 MCP resource 暴露，只通过三个工具：`coderunner.knowledge.search`、`coderunner.knowledge.search_similar_problems`、`coderunner.knowledge.search_error_patterns`，需要 `knowledge:read` scope。工具实现会捕获异常，返回空数组加 error，不让 agent 因 KB 初始化失败直接崩。见 [tools/knowledge_search/search.py](C:/Users/libie/Desktop/program/CodeRunner-AI/tools/knowledge_search/search.py:4) 和 [tools/protocol/schemas/catalog.py](C:/Users/libie/Desktop/program/CodeRunner-AI/tools/protocol/schemas/catalog.py:249)。

Tutor 会直接预取错误模式和知识点，分数低于 `0.3` 的过滤掉，再注入 system context；Generator 会预取相似题用于去重提醒。见 [agents/tutor/agent.py](C:/Users/libie/Desktop/program/CodeRunner-AI/agents/tutor/agent.py:43) 和 [agents/generator/agent.py](C:/Users/libie/Desktop/program/CodeRunner-AI/agents/generator/agent.py:159)。

**Evaluation**
这里分两层：

RAG 子系统测试：有 focused tests 覆盖 Chroma cosine 配置、索引/搜索、similarity 范围、chunk 折叠、rerank 开关/失败 fallback、语言过滤、owner 隔离、scope 隔离、KB health degraded。主要在 [tests/test_knowledge_base.py](C:/Users/libie/Desktop/program/CodeRunner-AI/tests/test_knowledge_base.py:43)、[tests/test_rag_chunk_rerank.py](C:/Users/libie/Desktop/program/CodeRunner-AI/tests/test_rag_chunk_rerank.py:23)、[tests/test_rag_filter.py](C:/Users/libie/Desktop/program/CodeRunner-AI/tests/test_rag_filter.py:23)。

Agent eval 平台：`EvalHarness` 从 `evals/datasets/*` 加载 case，跑真实 agent，绑定 trace，执行 graders，持久化 `EvalRun/EvalCaseRun/EvalCaseGraderResult`，报告 pass rate、cost、latency、tokens、failure types、regressions。见 [evals/harness/eval_harness.py](C:/Users/libie/Desktop/program/CodeRunner-AI/evals/harness/eval_harness.py:69) 和 [evals/reports/generator.py](C:/Users/libie/Desktop/program/CodeRunner-AI/evals/reports/generator.py:91)。

但我没看到“专门评估 retrieval 质量”的 benchmark，比如 recall@k、MRR、nDCG、query-doc relevance 标注集。现在的 RAG evaluation 更像工程正确性测试 + agent 行为 eval 的间接覆盖。