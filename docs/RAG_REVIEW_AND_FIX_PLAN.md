# RAG 子系统评审验证与修复计划

> 日期: 2026-05-24
> 范围: `app/agents/knowledge_base.py`, `app/agents/tools/knowledge_tools.py`, `app/agents/generation_pipeline.py`, `app/agents/agents/tutor.py`, `app/agents/agents/generator.py`, `app/__init__.py`

---

## 一、评审断言逐条验证

### ✅ 已确认属实的断言

| # | 断言 | 验证结果 | 代码位置 |
|---|------|----------|----------|
| 1 | ChromaDB + sentence-transformers 选型合理 | ✅ 属实 | `knowledge_base.py:13-21` |
| 2 | 三个 collection 职责分明 | ✅ 属实 | `knowledge_base.py:23-25` |
| 3 | TutorAgent 注入知识点/错误模式到 prompt | ✅ 属实 | `tutor.py:45-77` (`_get_kb_context`) |
| 4 | GeneratorAgent 查相似题避免重复 | ✅ 属实 | `generator.py:114` (`_get_similar_questions`) |
| 5 | 有 index/seed/add/search/delete API | ✅ 属实 | `ai.py:1432+` |
| 6 | 教师权限保护管理操作 | ✅ 属实 | `ai.py` 上 `@require_teacher`; `permissions.py:17` |
| 7 | `similarity = 1 - dist` 不严谨 | ✅ 属实 | `knowledge_base.py:68`; collection 创建未指定距离度量 |
| 8 | 向量库按 `question.id` 存，Problem 迁移后粒度不匹配 | ✅ 属实 | `knowledge_base.py:32` 使用 `str(question.id)` |
| 9 | `search_knowledge()` 只返回 document 文本 | ✅ 属实 | `knowledge_base.py:98` |
| 10 | 无 chunking / rerank / 阈值过滤 | ✅ 属实 | tutor `_get_kb_context` 无阈值判断，直接 top-n |
| 11 | 启动时自动全量索引无配置开关 | ✅ 属实 | `app/__init__.py:36,78-98`; 无 `ENABLE_KB_*` 环境变量 |
| 12 | 知识库全局无 scope 隔离 | ✅ 属实 | metadata 无 `teacher_id`/`classroom_id` 字段 |
| 13 | 测试覆盖仅限权限，无向量操作行为测试 | ✅ 属实 | `test_phase3.py:395-411` 只测 `check_tool_permission` |

### ⚠️ 补充说明

| 断言 | 补充 |
|------|------|
| ChromaDB distance 默认值 | ChromaDB 默认使用 **L2 (欧氏距离)**，不是 cosine。因此 `1 - dist` 根本不是余弦相似度，阈值 0.8 完全不可靠 |
| `/knowledge/search` 权限 | 该 API 使用 `@require_auth`（任何登录用户可访问），而非 `@require_teacher`。评审说的"对所有登录用户开放"属实 |

### 总结：建议中的所有断言均属实，无虚假或过度夸张的描述。

---

## 二、修复计划

### P0 — 紧急修复（相似度计算不可靠）

**问题**: ChromaDB 默认 L2 距离，`1 - dist` 无实际语义意义，`SIMILARITY_THRESHOLD = 0.8` 形同虚设。

**修复**:

```python
# knowledge_base.py — 创建 collection 时显式指定 cosine 距离
self.questions = self.client.get_or_create_collection(
    "questions",
    metadata={"hnsw:space": "cosine"},
)
self.knowledge = self.client.get_or_create_collection(
    "knowledge_points",
    metadata={"hnsw:space": "cosine"},
)
self.error_patterns = self.client.get_or_create_collection(
    "error_patterns",
    metadata={"hnsw:space": "cosine"},
)
```

```python
# knowledge_base.py — search_similar_questions 返回规范化 score
# cosine distance ∈ [0, 2], similarity = 1 - distance/2 ∈ [0, 1]
# 但 Chroma cosine space 直接返回 1 - cos(a,b) ∈ [0, 2]
# 所以 similarity = 1 - dist 此时 ∈ [-1, 1], 更好的做法:
"similarity": round(max(0, 1 - dist), 4) if dist is not None else 0,
```

**注意**: 切换距离度量后需要**重建索引**（删除旧 collection 数据，重新 `index_all_questions`）。

**涉及文件**: `knowledge_base.py`, `generation_pipeline.py`

---

### P1 — 按 Problem 粒度索引

**问题**: Question 是 Problem 的语言 variant（Python/C），同一题面被重复索引 N 次。

**修复**:

```python
# knowledge_base.py — 新增 index_problem 方法
def index_problem(self, problem):
    """Index a problem (not per-variant) into the vector store."""
    text = f"{problem.title}\n{problem.description}"
    embedding = self.embedder.encode(text).tolist()
    languages = [v.programming_language for v in problem.variants]
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

```python
# 相应修改 index_all_questions → index_all_problems
def index_all_problems():
    from app.models.problem import Problem
    kb = get_knowledge_base()
    problems = Problem.query.all()
    for p in problems:
        try:
            kb.index_problem(p)
        except Exception as e:
            logger.warning("Failed to index problem %d: %s", p.id, e)
    logger.info("Indexed %d problems", len(problems))
    return len(problems)
```

**涉及文件**: `knowledge_base.py`, `app/__init__.py`, `ai.py`, `generation_pipeline.py`

---

### P2 — 检索结果增加元数据

**问题**: `search_knowledge()` 只返回纯文本，agent 无法引用来源，也不好调试。

**修复**:

```python
# knowledge_base.py — search_knowledge 返回结构化数据
def search_knowledge(self, query: str, n: int = 3) -> list:
    """Search course knowledge for relevant context. Returns structured results."""
    if self.knowledge.count() == 0:
        return []

    embedding = self.embedder.encode(query).tolist()
    results = self.knowledge.query(
        query_embeddings=[embedding],
        n_results=min(n, self.knowledge.count()),
        include=["documents", "metadatas", "distances"],
    )
    if not results["documents"] or not results["documents"][0]:
        return []

    return [
        {
            "topic": meta.get("topic", ""),
            "category": meta.get("category", ""),
            "content": doc,
            "distance": round(dist, 4),
            "score": round(max(0, 1 - dist), 4),
        }
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )
    ]
```

**同样修改** `search_error_patterns` 返回结构化数据。

**涉及文件**: `knowledge_base.py`, `knowledge_tools.py`, `tutor.py`

---

### P3 — 检索结果加最低相关性阈值

**问题**: Tutor 直接将 top-n 注入 prompt，弱相关内容会污染上下文。

**修复**:

```python
# tutor.py — _get_kb_context 中添加阈值过滤
MIN_KNOWLEDGE_SCORE = 0.3  # cosine similarity threshold

# 在检索后过滤:
knowledge = kb.search_knowledge(topic_query, n=2)
knowledge = [k for k in knowledge if k.get("score", 0) >= MIN_KNOWLEDGE_SCORE]

patterns = kb.search_error_patterns(query, n=2)
patterns = [p for p in patterns if p.get("score", 0) >= MIN_KNOWLEDGE_SCORE]
```

**涉及文件**: `tutor.py`, 可选也在 `generation_pipeline.py` 中加

---

### P4 — 启动索引可配置化

**问题**: `create_app()` 每次启动开后台线程，多 worker 时重复跑、抢 Chroma 写锁。

**修复**:

```python
# app/__init__.py — 受配置控制
if app.config.get("ENABLE_KB_STARTUP_INDEX", False):
    _async_index_knowledge_base(app)
```

```python
# app/core/config.py — 各环境配置
class DevelopmentConfig(BaseConfig):
    ENABLE_KB_STARTUP_INDEX = True   # 开发环境方便

class ProductionConfig(BaseConfig):
    ENABLE_KB_STARTUP_INDEX = False  # 生产用 CLI/调度任务
```

**涉及文件**: `app/__init__.py`, `app/core/config.py`

---

### P5 — 知识库 Scope 隔离（中期）

**问题**: 知识库全局共享，未来教师添加私有知识点会越权泄露。

**修复方向**:

```python
# knowledge_base.py — add_knowledge_point 增加 scope 参数
def add_knowledge_point(self, topic, content, category="concept",
                        scope="global", owner_id=None):
    metadata = {
        "topic": topic,
        "category": category,
        "scope": scope,           # "global" | "teacher" | "classroom"
        "owner_id": owner_id,     # teacher.id or classroom.id
    }
    ...

# search_knowledge 增加 where 过滤
def search_knowledge(self, query, n=3, scope_filter=None):
    where = None
    if scope_filter:
        # 允许看到 global + 自己 scope 的内容
        where = {"$or": [
            {"scope": "global"},
            {"owner_id": scope_filter["owner_id"]},
        ]}
    ...
```

```python
# ai.py — /knowledge/search 加当前用户 scope
user = get_current_user_or_401()
scope_filter = {"owner_id": user.id} if user.role != "admin" else None
results["knowledge_points"] = kb.search_knowledge(query, n=n, scope_filter=scope_filter)
```

**涉及文件**: `knowledge_base.py`, `ai.py`, `knowledge_tools.py`

---

### P6 — 补充测试

**需要覆盖的场景**:

| 测试用例 | 验证内容 |
|----------|----------|
| `test_kb_index_and_search` | seed 后 count > 0，search 能命中 |
| `test_kb_similarity_score_range` | cosine 距离返回 score ∈ [0, 1] |
| `test_kb_dedup_threshold` | 相似度 > 0.8 的题被标记为重复 |
| `test_kb_problem_level_indexing` | 同一 problem 多个 variant 只生成一条向量 |
| `test_kb_scope_isolation` | 学生搜不到教师私有知识点 |
| `test_kb_low_relevance_filtered` | 弱相关结果不注入 tutor prompt |

**涉及文件**: 新建 `tests/test_knowledge_base.py`

---

## 三、执行优先级

```
Week 1:  P0 (距离度量修复) + P1 (Problem 粒度索引) + 重建向量数据
Week 2:  P2 (结构化返回) + P3 (阈值过滤)
Week 3:  P4 (启动配置化) + P6 (补测试)
Week 4+: P5 (Scope 隔离) — 等有多教师需求时做
```

---

## 四、迁移注意事项

1. **P0 切换距离度量需要重建**: ChromaDB 不支持就地修改 collection 的距离函数。需要：
   - 删除旧 collection: `client.delete_collection("questions")` 等
   - 重新创建并指定 `metadata={"hnsw:space": "cosine"}`
   - 重新运行 `index_all_problems()` 和 `seed_all()`
   
2. **P1 ID 格式变更**: 从 `str(question.id)` 改为 `f"problem_{problem.id}"`，旧数据不兼容，需完整重建。

3. **P2 返回格式变更**: `search_knowledge` 从 `list[str]` 改为 `list[dict]`，所有调用方需要适配：
   - `tutor.py:_get_kb_context` — 从 `k[:300]` 改为 `k["content"][:300]`
   - `knowledge_tools.py:search_knowledge` — 返回值结构变化
   - `ai.py:/knowledge/search` — 已经是透传，无需改

4. **建议提供迁移脚本**: `scripts/migrate_kb.py`，一键删旧 collection + 重建索引。
