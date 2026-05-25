# RAG 子系统评审验证与修复计划

> 日期: 2026-05-24
> 状态: **全部完成** (P0-P6)
> 范围: `app/agents/knowledge_base.py`, `app/agents/tools/knowledge_tools.py`, `app/agents/generation_pipeline.py`, `app/agents/agents/tutor.py`, `app/agents/agents/generator.py`, `app/__init__.py`

---

## 一、评审断言逐条验证

### 已确认属实的断言

| # | 断言 | 验证结果 | 代码位置 |
|---|------|----------|----------|
| 1 | ChromaDB + sentence-transformers 选型合理 | 属实 | `knowledge_base.py:13-21` |
| 2 | 三个 collection 职责分明 | 属实 | `knowledge_base.py:23-25` |
| 3 | TutorAgent 注入知识点/错误模式到 prompt | 属实 | `tutor.py:45-77` (`_get_kb_context`) |
| 4 | GeneratorAgent 查相似题避免重复 | 属实 | `generator.py:114` (`_get_similar_questions`) |
| 5 | 有 index/seed/add/search/delete API | 属实 | `ai.py:1432+` |
| 6 | 教师权限保护管理操作 | 属实 | `ai.py` 上 `@require_teacher`; `permissions.py:17` |
| 7 | `similarity = 1 - dist` 不严谨 | 属实 | 已修复 — 现在使用 cosine space |
| 8 | 向量库按 `question.id` 存，Problem 迁移后粒度不匹配 | 属实 | 已修复 — 现在使用 `problem_{problem.id}` |
| 9 | `search_knowledge()` 只返回 document 文本 | 属实 | 已修复 — 现在返回结构化 dict |
| 10 | 无 chunking / rerank / 阈值过滤 | 属实 | 已修复 — tutor 使用 MIN_KNOWLEDGE_SCORE |
| 11 | 启动时自动全量索引无配置开关 | 属实 | 已修复 — ENABLE_KB_STARTUP_INDEX |
| 12 | 知识库全局无 scope 隔离 | 属实 | 已修复 — scope + owner_id 字段 |
| 13 | 测试覆盖仅限权限，无向量操作行为测试 | 属实 | 已修复 — `tests/test_knowledge_base.py` |

### 总结：建议中的所有断言均属实，全部已修复。

---

## 二、修复完成记录

### P0 — 距离度量修复 ✅ 已完成

**修复内容**: 所有 collection 创建时指定 `metadata={"hnsw:space": "cosine"}`，similarity 计算使用 `max(0, 1 - dist)`。

**涉及文件**: `knowledge_base.py:23-30,91,148,185`

---

### P1 — Problem 粒度索引 ✅ 已完成

**修复内容**: 新增 `index_problem()` 方法，使用 `f"problem_{problem.id}"` 作为 ID；`index_all_problems()` 替代旧的 per-variant 索引；`index_all_questions()` 保留为 legacy alias。

**涉及文件**: `knowledge_base.py:48-63,207-224`, `app/__init__.py:84`

---

### P2 — 结构化返回数据 ✅ 已完成

**修复内容**: `search_knowledge()` 和 `search_error_patterns()` 返回 `list[dict]`，包含 topic/category/content/distance/score。所有调用方已适配。

**涉及文件**: `knowledge_base.py:118-192`, `tutor.py:68,78`, `knowledge_tools.py`

---

### P3 — 最低相关性阈值 ✅ 已完成

**修复内容**: `TutorAgent.MIN_KNOWLEDGE_SCORE = 0.3`，检索结果在注入 prompt 前按 score 过滤。

**涉及文件**: `tutor.py:45,64,74`

---

### P4 — 启动索引可配置化 ✅ 已完成

**修复内容**: `ENABLE_KB_STARTUP_INDEX` 配置项，开发环境默认 True，生产环境默认 False。

**涉及文件**: `app/__init__.py:36`, `app/core/config.py:67,76`

---

### P5 — 知识库 Scope 隔离 ✅ 已完成

**修复内容**:
- `add_knowledge_point()` 接受 `scope` 和 `owner_id` 参数
- `search_knowledge()` 接受 `scope_filter`，使用 `$or` 查询（global + owner）
- `/knowledge/add` API 默认 scope="teacher"，自动填充当前用户 ID
- `/knowledge/search` API 按用户角色应用 scope_filter（admin 无限制）
- `search_knowledge` tool 支持 `owner_id` 参数

**涉及文件**: `knowledge_base.py:101-136`, `ai.py:1574-1592,1608-1616`, `knowledge_tools.py:19-32`

---

### P6 — 测试覆盖 ✅ 已完成

**测试文件**: `tests/test_knowledge_base.py`

| 测试用例 | 验证内容 | 状态 |
|----------|----------|------|
| `test_cosine_distance_metric` | collection 使用 cosine space | ✅ |
| `test_index_problem_and_search` | seed 后 count > 0，search 能命中 | ✅ |
| `test_similarity_score_range` | cosine 距离返回 score ∈ [0, 1] | ✅ |
| `test_dedup_threshold` | 相似度 > 0.8 的题被标记为重复 | ✅ |
| `test_problem_level_indexing_no_duplicates` | 同一 problem 多个 variant 只生成一条向量 | ✅ |
| `test_search_returns_structured_data` | 返回结构化 dict 而非纯文本 | ✅ |
| `test_global_scope_visible_to_all` | global 内容所有人可见 | ✅ |
| `test_teacher_scope_visible_to_owner` | teacher 内容 owner 可见 | ✅ |
| `test_teacher_scope_hidden_from_others` | teacher 内容对其他人不可见 | ✅ |
| `test_tutor_filters_low_relevance` | 弱相关结果不注入 tutor prompt | ✅ |
| `test_index_all_problems_function` | 集成测试 index_all_problems | ✅ |

---

### 迁移脚本 ✅ 已完成

**文件**: `scripts/migrate_kb.py`

功能: 删除旧 collection → 重建（cosine）→ 重新索引 Problems → 重新 seed 知识点和错误模式。

支持 `python -m scripts.migrate_kb` 或 `flask kb-migrate` 两种运行方式。

---

## 三、执行记录

```
2026-05-24:  P0 (距离度量修复) + P1 (Problem 粒度索引) + P2 (结构化返回) + P3 (阈值过滤) ✅
2026-05-24:  P4 (启动配置化) + P5 (Scope 隔离) + P6 (测试) + 迁移脚本 ✅
```

全部修复已通过 commit `3da18c2` 合入 master。
