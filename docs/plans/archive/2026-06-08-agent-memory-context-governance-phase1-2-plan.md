# Agent Memory / Context Governance Phase 1-2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有按角色拼接的 memory 字符串升级为结构化 `MemoryContext`，并让 `AgentDefinition.memory_policy` 真实决定 tutor、generator、analytics、reviewer 的 memory 注入边界，同时保持现有 API 和用户可见 prompt 行为兼容。

**Architecture:** 在 `ai/memory/context.py` 定义纯数据契约，在 `MemoryService` 中建立 `build -> filter -> render` 单一入口。`core/definitions.py` 只声明 Phase 2 能立即消费的 policy 字段；各 agent 继续负责组装自身 system prompt，但不再自行决定读取哪类 profile 或 summary。

**Tech Stack:** Python 3.11、dataclasses、Flask-SQLAlchemy / SQLAlchemy 2.0、LangChain messages、pytest、现有 AgentDefinition registry。

---

## 1. 计划状态与范围

> 状态: Active  
> 日期: 2026-06-08  
> 来源: `docs/issues/2026-06-08-agent-memory-context-improvements.md`  
> 上层路线: `docs/plans/active/2026-06-05-agent-platform-remaining-improvements-plan.md`

本计划只执行 issue 建议启动的 **Phase 1 + Phase 2**：

1. 建立结构化 `MemoryContext` / `MemoryItem` 契约。
2. 保留 `MemoryService.get_memory_context()` 字符串兼容入口。
3. 将 `memory_policy` 加入 `AgentDefinition` 并由 `MemoryService` 真实消费。
4. 为 tutor、generator、analytics、reviewer 建立可测试的默认策略。
5. 同步当前架构文档，区分“当前已实现”和“后续治理目标”。

Phase 3-5 的 budget、敏感信息过滤、TTL/forget、extractor、trace audit、eval replay 不在本次实现范围内。它们必须建立在本计划的结构化上下文和稳定 policy 契约之上，再分别编写后续 active plan。

## 2. 已完成基线

实施者不得重开以下已完成工作：

- `AgentSession` / `AgentRuntime` / `LLMRunner` 已经是单次 agent run 的执行内核。
- `AgentDefinition` 已经承载 model tier、tool allowlist、rate limit、handoff target 和 prompt ref。
- `MemoryService.compact_messages()` 已负责短期消息窗口压缩。
- `AIConversation.summary` 已作为中期记忆回放，并排除当前 conversation。
- `StudentProfile` / `TeacherPreference` 已是长期画像载体。
- tutor、generator、analytics 已接入 memory；reviewer 当前没有接入。
- shared SQLAlchemy Domain、FastAPI Agent Runtime、trace/eval repository 已完成，不在本计划内迁移。

## 3. 非目标

- 不新增数据库表、Alembic migration 或新的持久化 memory item 模型。
- 不把课程资料、代码文档、Chroma 内容归入用户 memory。
- 不修改 `LLMRunner.compact()` 或重新设计短期消息压缩。
- 不在本阶段把 memory snapshot 写入 trace artifact。
- 不增加 token/character budget 字段；没有 enforcement 前不得增加 dead field。
- 不实现 extractor、candidate review、forget、TTL、superseded 或 conflict resolution。
- 不让 reviewer 读取学生画像、教师偏好或历史 summary。
- 不重构 `app/api/v1/ai.py` 的 generation pipeline；只守住现有兼容字符串接口。
- 不调整 Agent Runtime、ToolRuntime、MCP、WorkflowEngine 或 handoff kernel。

## 4. 目标行为

### 4.1 数据流

```text
Agent state
  -> agent_name + actor identity + optional target_student_id
  -> AgentDefinition.memory_policy
  -> MemoryService.build_memory_context(...)
       -> StudentProfile / TeacherPreference
       -> recent AIConversation summaries
       -> structured MemoryContext
  -> MemoryService.render_memory_context(...)
       -> backward-compatible prompt text
  -> agent-specific system prompt section
```

### 4.2 默认策略

| Agent | Profile | Recent summaries | Target student | 说明 |
|---|---|---|---|---|
| `tutor` | student | 仅 tutor summary | 不允许 | 学生身份读取自己的学习画像；教师/admin 调 tutor 时不把教师偏好误标成学生画像 |
| `generator` | teacher | 仅 generator summary | 不允许 | 教师/admin 读取自己的出题偏好；不读取学生画像 |
| `analytics` | actor；教师/admin 可切换到 `target_student_id` | 仅 analytics summary，且始终属于 actor | 允许，受角色限制 | 学生只能读自己的画像；教师/admin 可读取明确目标学生画像，但不能读取目标学生的 conversation summary |
| `reviewer` | none | none | 不允许 | 保持当前 reviewer 无长期 memory 的边界 |

### 4.3 兼容性

以下调用必须继续工作：

```python
MemoryService.get_memory_context(user_id, user_role, conversation_id=None)
```

没有 `agent_name` 时使用 legacy role-based policy：

- student -> `StudentProfile` + 最近所有 agent summary。
- teacher -> `TeacherPreference` + 最近所有 agent summary。
- 未知角色 -> 不读 profile，但仍可读当前用户的 recent summary。

现有文本标签保持不变：

- `Student Background`
- `Error History`
- `Weak Areas`
- `Previous Hints Given`
- `Teacher Preferences`
- `Class Weak Areas`
- `Recent Sessions`

## 5. 文件地图

### 新增

| 文件 | 职责 |
|---|---|
| `ai/memory/context.py` | 定义 `MemorySensitivity`、`MemoryMetadata`、`MemoryItem`、`RecentSessionMemory`、`MemoryContext` |

### 修改

| 文件 | 职责 |
|---|---|
| `ai/memory/service.py` | 拆分 build/render；解析 policy；保持 legacy string API |
| `core/definitions.py` | 定义 `MemoryPolicy` / `MemoryProfileKind`，为四个 agent 声明默认策略 |
| `domain/statements/chat.py` | recent summary 查询增加可选 `agent_types` 过滤 |
| `domain/repositories/chat.py` | 将 `agent_types` 透传到 statement |
| `ai/agents/base.py` | 从 definition registry 暴露只读 `memory_policy` |
| `ai/agents/tutor/agent.py` | 调用 agent-aware memory API |
| `ai/agents/generator/agent.py` | 调用 agent-aware memory API |
| `ai/agents/analytics/agent.py` | 传入 agent 名称与可选 `target_student_id` |
| `docs/architecture/data-state-memory.md` | 补 Phase 1+2 目标态和明确延期边界 |
| `docs/issues/2026-06-08-agent-memory-context-improvements.md` | 执行后更新完成状态与剩余问题 |
| `docs/issues/README.md` | 同步 issue 状态 |
| `docs/plans/README.md` | 执行完成后移动/归档计划入口 |

### 测试

| 文件 | 覆盖 |
|---|---|
| `tests/test_agents.py` | build/render、legacy API、agent system context、analytics target isolation |
| `tests/test_domain_chat_repository.py` | summary agent type 过滤、排除当前 conversation、limit |
| `tests/test_definitions_consistency.py` | policy 字段完整性、默认策略和非 dead-field 约束 |
| `tests/test_model_router_and_definitions.py` | agent class 与 definition policy 一致性 |
| `tests/test_agent_features.py` | generation pipeline 继续接收 legacy teacher context |

## 6. 数据契约

`ai/memory/context.py` 的目标接口：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MemorySensitivity(str, Enum):
    INTERNAL = "internal"
    RESTRICTED = "restricted"


@dataclass(frozen=True)
class MemoryMetadata:
    source: str
    confidence: float = 1.0
    sensitivity: MemorySensitivity = MemorySensitivity.INTERNAL
    expires_at: datetime | None = None
    reason_included: str = ""


@dataclass(frozen=True)
class MemoryItem:
    key: str
    value: Any
    metadata: MemoryMetadata


@dataclass(frozen=True)
class RecentSessionMemory:
    conversation_id: int
    agent_type: str
    summary: str
    created_at: datetime | None
    metadata: MemoryMetadata


@dataclass(frozen=True)
class MemoryContext:
    student_profile: tuple[MemoryItem, ...] = field(default_factory=tuple)
    teacher_preference: tuple[MemoryItem, ...] = field(default_factory=tuple)
    recent_sessions: tuple[RecentSessionMemory, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not (
            self.student_profile
            or self.teacher_preference
            or self.recent_sessions
        )
```

`core/definitions.py` 的目标 policy：

```python
class MemoryProfileKind(str, Enum):
    NONE = "none"
    ACTOR = "actor"
    STUDENT = "student"
    TEACHER = "teacher"


@dataclass(frozen=True)
class MemoryPolicy:
    profile_kind: MemoryProfileKind = MemoryProfileKind.NONE
    include_recent_summaries: bool = False
    recent_summary_agent_types: frozenset[str] = frozenset()
    max_recent_summaries: int = 3
    allow_target_student: bool = False
```

所有字段必须在 `MemoryService.build_memory_context()` 中被读取。若实现时发现字段没有消费点，删除该字段，不允许以“以后会用”为理由保留。

---

### Task 1: 锁定 legacy memory 输出和降级行为

**Files:**
- Modify: `tests/test_agents.py`

- [ ] **Step 1: 为学生画像完整渲染写 characterization test**

在 `TestMemorySummaryReplay` 前新增 `TestMemoryContextCompatibility`：

```python
class TestMemoryContextCompatibility:
    def test_legacy_student_context_keeps_existing_labels(self, db_session, app):
        with app.app_context():
            from domain.models.user import User, UserRole
            from app.models.student_profile import StudentProfile
            from ai.memory.service import MemoryService

            user = User(
                username="memory_student",
                password="x",
                email="memory-student@test.com",
                role=UserRole.STUDENT,
            )
            db_session.add(user)
            db_session.flush()
            db_session.add(StudentProfile(
                student_id=user.id,
                learning_summary="Needs visual examples.",
                error_patterns={"WA": 3},
                knowledge_map={"recursion": 0.4, "arrays": 0.9},
                current_hint_level={"recursion": 2},
            ))
            db_session.commit()

            rendered = MemoryService.get_memory_context(user.id, "student")

            assert "Student Background: Needs visual examples." in rendered
            assert "Error History: {'WA': 3}" in rendered
            assert "Weak Areas: recursion" in rendered
            assert "Previous Hints Given: {'recursion': 2}" in rendered
```

- [ ] **Step 2: 为教师偏好和空表降级写 characterization test**

```python
    def test_legacy_teacher_context_keeps_existing_labels(self, db_session, app):
        with app.app_context():
            from domain.models.user import User, UserRole
            from app.models.student_profile import TeacherPreference
            from ai.memory.service import MemoryService

            user = User(
                username="memory_teacher",
                password="x",
                email="memory-teacher@test.com",
                role=UserRole.TEACHER,
            )
            db_session.add(user)
            db_session.flush()
            db_session.add(TeacherPreference(
                teacher_id=user.id,
                style_notes="Prefer concise prompts.",
                preferred_language="java",
                preferred_difficulty="hard",
                class_weak_areas=["loops", "recursion"],
            ))
            db_session.commit()

            rendered = MemoryService.get_memory_context(user.id, "teacher")

            assert "Teacher Preferences: Prefer concise prompts." in rendered
            assert "Preferred Language: java" in rendered
            assert "Preferred Difficulty: hard" in rendered
            assert "Class Weak Areas: loops, recursion" in rendered

    def test_legacy_context_returns_empty_when_profile_query_fails(self, app):
        with app.app_context(), patch(
            "app.models.student_profile.StudentProfile.query"
        ) as query:
            from ai.memory.service import MemoryService

            query.filter_by.side_effect = RuntimeError("table unavailable")
            assert MemoryService.get_memory_context(1, "student") == ""
```

- [ ] **Step 3: 运行 characterization tests**

Run:

```powershell
$env:SECRET_KEY='test-secret-key'
$env:DEBUG='True'
.\.venv\Scripts\python.exe -m pytest tests/test_agents.py::TestMemoryContextCompatibility tests/test_agents.py::TestMemorySummaryReplay -q
```

Expected: PASS。若现有输出与测试不同，先按当前真实行为修正断言；本 Task 不修改生产代码。

- [ ] **Step 4: Commit**

```powershell
git add tests/test_agents.py
git commit -m "test(memory): lock legacy context rendering"
```

---

### Task 2: 新增结构化 MemoryContext 数据契约

**Files:**
- Create: `ai/memory/context.py`
- Modify: `ai/memory/__init__.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1: 写失败测试，定义 immutable context contract**

```python
class TestStructuredMemoryContext:
    def test_memory_context_exposes_structured_sections(self):
        from ai.memory.context import (
            MemoryContext,
            MemoryItem,
            MemoryMetadata,
            RecentSessionMemory,
        )

        profile_item = MemoryItem(
            key="learning_summary",
            value="Needs visual examples.",
            metadata=MemoryMetadata(
                source="student_profile:7",
                reason_included="tutor profile policy",
            ),
        )
        session = RecentSessionMemory(
            conversation_id=11,
            agent_type="tutor",
            summary="Worked on recursion.",
            created_at=None,
            metadata=MemoryMetadata(
                source="ai_conversation:11",
                reason_included="recent tutor summary policy",
            ),
        )

        context = MemoryContext(
            student_profile=(profile_item,),
            recent_sessions=(session,),
        )

        assert context.student_profile[0].key == "learning_summary"
        assert context.recent_sessions[0].conversation_id == 11
        assert context.is_empty is False
        assert MemoryContext().is_empty is True
```

- [ ] **Step 2: 运行测试并确认缺少模块**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agents.py::TestStructuredMemoryContext -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ai.memory.context'`.

- [ ] **Step 3: 创建数据契约**

在 `ai/memory/context.py` 实现第 6 节给出的完整 dataclass。约束：

- 所有 dataclass 使用 `frozen=True`。
- collection 使用 tuple，避免 build 后被 agent 原地修改。
- `MemoryMetadata.source` 使用稳定 source key，不保存 ORM 实例。
- `MemorySensitivity` 本阶段只作为结构化元数据，不做 filtering。
- 不在该模块 import Flask、SQLAlchemy、agent 或 repository。

- [ ] **Step 4: 从 package 导出公共类型**

`ai/memory/__init__.py`：

```python
from ai.memory.context import (
    MemoryContext,
    MemoryItem,
    MemoryMetadata,
    MemorySensitivity,
    RecentSessionMemory,
)

__all__ = [
    "MemoryContext",
    "MemoryItem",
    "MemoryMetadata",
    "MemorySensitivity",
    "RecentSessionMemory",
]
```

- [ ] **Step 5: 运行结构测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agents.py::TestStructuredMemoryContext -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add ai/memory/context.py ai/memory/__init__.py tests/test_agents.py
git commit -m "feat(memory): add structured context contract"
```

---

### Task 3: 给 recent summary 查询增加 agent type 过滤

**Files:**
- Modify: `domain/statements/chat.py`
- Modify: `domain/repositories/chat.py`
- Modify: `tests/test_domain_chat_repository.py`

- [ ] **Step 1: 写 repository 失败测试**

```python
def test_recent_summaries_filter_agent_types_and_exclude_current(
    repo, db_session, chat_user
):
    from domain.models.chat import AIConversation

    tutor = AIConversation(
        user_id=chat_user.id,
        agent_type="tutor",
        summary="Tutor memory",
    )
    generator = AIConversation(
        user_id=chat_user.id,
        agent_type="generator",
        summary="Generator memory",
    )
    current = AIConversation(
        user_id=chat_user.id,
        agent_type="tutor",
        summary="Current tutor memory",
    )
    db_session.add_all([tutor, generator, current])
    db_session.commit()

    rows = repo.get_recent_summarized_conversations(
        chat_user.id,
        exclude_conversation_id=current.id,
        agent_types=("tutor",),
        limit=3,
    )

    assert [row.id for row in rows] == [tutor.id]
```

- [ ] **Step 2: 运行测试并确认签名失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_domain_chat_repository.py -q
```

Expected: FAIL because `agent_types` is not accepted.

- [ ] **Step 3: 扩展 statement**

目标签名：

```python
def select_recent_summarized_conversations(
    user_id: int,
    exclude_conversation_id: int | None = None,
    limit: int = 3,
    agent_types: tuple[str, ...] | None = None,
) -> Select:
    stmt = (
        select(AIConversation)
        .where(AIConversation.user_id == user_id)
        .where(AIConversation.summary.isnot(None))
    )
    if exclude_conversation_id is not None:
        stmt = stmt.where(AIConversation.id != exclude_conversation_id)
    if agent_types:
        stmt = stmt.where(AIConversation.agent_type.in_(agent_types))
    return stmt.order_by(AIConversation.updated_at.desc()).limit(limit)
```

- [ ] **Step 4: 扩展 sync repository**

```python
def get_recent_summarized_conversations(
    self,
    user_id: int,
    *,
    exclude_conversation_id: Optional[int] = None,
    limit: int = 3,
    agent_types: tuple[str, ...] | None = None,
) -> list[AIConversation]:
    return list(
        self.session.execute(
            select_recent_summarized_conversations(
                user_id,
                exclude_conversation_id,
                limit,
                agent_types,
            )
        ).scalars()
    )
```

当前 `AsyncChatRepository` 没有该查询方法，本 Task 不新增未被消费的 async surface。

- [ ] **Step 5: 运行 repository tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_domain_chat_repository.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add domain/statements/chat.py domain/repositories/chat.py tests/test_domain_chat_repository.py
git commit -m "feat(memory): filter recent summaries by agent type"
```

---

### Task 4: 将 MemoryService 拆成 build + render，并保留 legacy API

**Files:**
- Modify: `ai/memory/service.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1: 写 build API 失败测试**

```python
class TestMemoryContextBuilder:
    def test_build_student_context_returns_source_metadata(
        self, db_session, app
    ):
        with app.app_context():
            from domain.models.user import User, UserRole
            from app.models.student_profile import StudentProfile
            from ai.memory.service import MemoryService

            user = User(
                username="structured_student",
                password="x",
                email="structured-student@test.com",
                role=UserRole.STUDENT,
            )
            db_session.add(user)
            db_session.flush()
            db_session.add(StudentProfile(
                student_id=user.id,
                learning_summary="Needs visual examples.",
                knowledge_map={"recursion": 0.4},
            ))
            db_session.commit()

            context = MemoryService.build_memory_context(
                user.id,
                "student",
            )

            items = {item.key: item for item in context.student_profile}
            assert items["learning_summary"].value == "Needs visual examples."
            assert items["learning_summary"].metadata.source == (
                f"student_profile:{user.id}"
            )
            assert items["weak_areas"].value == ("recursion",)
```

- [ ] **Step 2: 写 structured recent session 测试**

```python
    def test_build_context_keeps_recent_session_identity(
        self, db_session, app
    ):
        with app.app_context():
            from domain.models.chat import AIConversation
            from domain.models.user import User, UserRole
            from ai.memory.service import MemoryService

            user = User(
                username="structured_session",
                password="x",
                email="structured-session@test.com",
                role=UserRole.STUDENT,
            )
            db_session.add(user)
            db_session.flush()
            previous = AIConversation(
                user_id=user.id,
                agent_type="tutor",
                summary="Worked on recursion.",
            )
            db_session.add(previous)
            db_session.commit()

            context = MemoryService.build_memory_context(user.id, "student")

            assert context.recent_sessions[0].conversation_id == previous.id
            assert context.recent_sessions[0].agent_type == "tutor"
            assert context.recent_sessions[0].summary == "Worked on recursion."
            assert context.recent_sessions[0].metadata.source == (
                f"ai_conversation:{previous.id}"
            )
```

- [ ] **Step 3: 运行测试并确认缺少 build API**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agents.py::TestMemoryContextBuilder -q
```

Expected: FAIL with missing `build_memory_context`.

- [ ] **Step 4: 实现 profile builders**

在 `MemoryService` 内新增：

```python
@staticmethod
def _student_profile_items(student_id: int, reason: str) -> tuple[MemoryItem, ...]:
    from app.models.student_profile import StudentProfile

    profile = StudentProfile.query.filter_by(student_id=student_id).first()
    if profile is None:
        return ()

    metadata = MemoryMetadata(
        source=f"student_profile:{student_id}",
        reason_included=reason,
    )
    items: list[MemoryItem] = []
    if profile.learning_summary:
        items.append(MemoryItem(
            key="learning_summary",
            value=profile.learning_summary,
            metadata=metadata,
        ))
    if profile.error_patterns:
        items.append(MemoryItem(
            key="error_patterns",
            value=dict(profile.error_patterns),
            metadata=metadata,
        ))
    if profile.knowledge_map:
        weak_areas = tuple(
            key
            for key, score in profile.knowledge_map.items()
            if score < 0.5
        )
        if weak_areas:
            items.append(MemoryItem(
                key="weak_areas",
                value=weak_areas,
                metadata=metadata,
            ))
    if profile.current_hint_level:
        items.append(MemoryItem(
            key="current_hint_level",
            value=dict(profile.current_hint_level),
            metadata=metadata,
        ))
    return tuple(items)

@staticmethod
def _teacher_preference_items(
    teacher_id: int, reason: str
) -> tuple[MemoryItem, ...]:
    from app.models.student_profile import TeacherPreference

    preference = TeacherPreference.query.filter_by(
        teacher_id=teacher_id
    ).first()
    if preference is None:
        return ()

    metadata = MemoryMetadata(
        source=f"teacher_preference:{teacher_id}",
        reason_included=reason,
    )
    items: list[MemoryItem] = []
    if preference.style_notes:
        items.append(MemoryItem(
            key="style_notes",
            value=preference.style_notes,
            metadata=metadata,
        ))
    if preference.preferred_language:
        items.append(MemoryItem(
            key="preferred_language",
            value=preference.preferred_language,
            metadata=metadata,
        ))
    if preference.preferred_difficulty:
        items.append(MemoryItem(
            key="preferred_difficulty",
            value=preference.preferred_difficulty,
            metadata=metadata,
        ))
    if preference.class_weak_areas:
        items.append(MemoryItem(
            key="class_weak_areas",
            value=tuple(preference.class_weak_areas),
            metadata=metadata,
        ))
    return tuple(items)
```

字段映射必须保持：

| ORM 字段 | `MemoryItem.key` | 结构化 value |
|---|---|---|
| `learning_summary` | `learning_summary` | `str` |
| `error_patterns` | `error_patterns` | `dict` |
| `knowledge_map` 中 `< 0.5` | `weak_areas` | `tuple[str, ...]` |
| `current_hint_level` | `current_hint_level` | `dict` |
| `style_notes` | `style_notes` | `str` |
| `preferred_language` | `preferred_language` | `str` |
| `preferred_difficulty` | `preferred_difficulty` | `str` |
| `class_weak_areas` | `class_weak_areas` | `tuple[str, ...]` |

空值不生成 item。

- [ ] **Step 5: 实现 structured recent sessions**

将 `_recent_conversation_summaries()` 替换为以下 structured helper：

```python
@staticmethod
def _recent_sessions(
    user_id: int,
    *,
    exclude_conversation_id: int | None,
    limit: int,
    agent_types: tuple[str, ...] | None,
    reason: str,
) -> tuple[RecentSessionMemory, ...]:
    from app.core.extensions import db
    from domain.repositories.chat import SyncChatRepository

    rows = SyncChatRepository(db.session).get_recent_summarized_conversations(
        user_id,
        exclude_conversation_id=exclude_conversation_id,
        limit=limit,
        agent_types=agent_types,
    )
    return tuple(
        RecentSessionMemory(
            conversation_id=row.id,
            agent_type=row.agent_type,
            summary=row.summary.strip(),
            created_at=row.created_at,
            metadata=MemoryMetadata(
                source=f"ai_conversation:{row.id}",
                reason_included=reason,
            ),
        )
        for row in rows
        if row.summary and row.summary.strip()
    )
```

不得把 ORM row 放入 `MemoryContext`。

- [ ] **Step 6: 实现 build API 的 legacy 默认行为**

目标签名：

```python
@staticmethod
def build_memory_context(
    user_id: int,
    user_role: str,
    conversation_id: int | None = None,
    *,
    profile_kind: str | None = None,
    include_recent_summaries: bool = True,
    recent_summary_agent_types: tuple[str, ...] | None = None,
    max_recent_summaries: int = 3,
    target_student_id: int | None = None,
    allow_target_student: bool = False,
) -> MemoryContext:
    try:
        resolved_profile_kind = profile_kind
        if resolved_profile_kind is None:
            if user_role == "student":
                resolved_profile_kind = "student"
            elif user_role == "teacher":
                resolved_profile_kind = "teacher"
            else:
                resolved_profile_kind = "none"
        elif resolved_profile_kind == "actor":
            resolved_profile_kind = (
                user_role if user_role in {"student", "teacher"} else "none"
            )

        student_profile: tuple[MemoryItem, ...] = ()
        teacher_preference: tuple[MemoryItem, ...] = ()

        can_use_target = (
            allow_target_student
            and target_student_id is not None
            and user_role in {"teacher", "admin"}
        )
        if can_use_target:
            resolved_profile_kind = "student"
            profile_subject_id = target_student_id
            profile_reason = "target student allowed by agent memory policy"
        else:
            profile_subject_id = user_id
            profile_reason = "actor profile allowed by memory policy"

        try:
            if resolved_profile_kind == "student":
                student_profile = MemoryService._student_profile_items(
                    profile_subject_id,
                    profile_reason,
                )
            elif resolved_profile_kind == "teacher":
                teacher_preference = (
                    MemoryService._teacher_preference_items(
                        profile_subject_id,
                        profile_reason,
                    )
                )
        except Exception as exc:
            logger.debug("Memory profile unavailable: %s", exc)

        recent_sessions: tuple[RecentSessionMemory, ...] = ()
        if include_recent_summaries and max_recent_summaries > 0:
            try:
                recent_sessions = MemoryService._recent_sessions(
                    user_id,
                    exclude_conversation_id=conversation_id,
                    limit=max_recent_summaries,
                    agent_types=recent_summary_agent_types,
                    reason="recent summaries allowed by memory policy",
                )
            except Exception as exc:
                logger.debug(
                    "Recent conversation summaries unavailable: %s",
                    exc,
                )

        return MemoryContext(
            student_profile=student_profile,
            teacher_preference=teacher_preference,
            recent_sessions=recent_sessions,
        )
    except Exception as exc:
        logger.debug(
            "Memory context unavailable (table may not exist yet): %s",
            exc,
        )
        return MemoryContext()
```

要求：

- `profile_kind is None` 时按 `user_role` 模拟 legacy 行为。
- `target_student_id` 只有在 `allow_target_student=True` 且 actor role 是 `teacher`/`admin` 时生效。
- target student 只影响 profile subject，不改变 recent summary owner。
- profile query 失败时返回空 profile section；summary query 失败时保留已构建 profile。
- 最外层异常仍降级为空 `MemoryContext`。

- [ ] **Step 7: 实现 renderer**

```python
@staticmethod
def render_memory_context(context: MemoryContext) -> str:
    parts: list[str] = []

    student_labels = {
        "learning_summary": "Student Background",
        "error_patterns": "Error History",
        "weak_areas": "Weak Areas",
        "current_hint_level": "Previous Hints Given",
    }
    for item in context.student_profile:
        value = item.value
        if item.key == "weak_areas":
            value = ", ".join(value)
        parts.append(f"{student_labels[item.key]}: {value}")

    teacher_labels = {
        "style_notes": "Teacher Preferences",
        "preferred_language": "Preferred Language",
        "preferred_difficulty": "Preferred Difficulty",
        "class_weak_areas": "Class Weak Areas",
    }
    for item in context.teacher_preference:
        value = item.value
        if item.key == "class_weak_areas":
            value = ", ".join(value)
        parts.append(f"{teacher_labels[item.key]}: {value}")

    if context.recent_sessions:
        summaries = "\n".join(
            f"- {session.summary}" for session in context.recent_sessions
        )
        parts.append(f"Recent Sessions:\n{summaries}")

    return "\n".join(parts)
```

renderer 必须按 legacy 标签和顺序输出，不能输出 metadata、source key 或内部 ID。

- [ ] **Step 8: 将兼容入口委托给 build + render**

```python
@staticmethod
def get_memory_context(
    user_id: int,
    user_role: str,
    conversation_id: int = None,
    **build_options,
) -> str:
    context = MemoryService.build_memory_context(
        user_id,
        user_role,
        conversation_id,
        **build_options,
    )
    return MemoryService.render_memory_context(context)
```

- [ ] **Step 9: 运行 memory tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agents.py::TestMemoryContextCompatibility tests/test_agents.py::TestStructuredMemoryContext tests/test_agents.py::TestMemoryContextBuilder tests/test_agents.py::TestMemorySummaryReplay -q
```

Expected: PASS，且原 `TestMemorySummaryReplay` 不修改断言即可通过。

- [ ] **Step 10: Commit**

```powershell
git add ai/memory/service.py tests/test_agents.py
git commit -m "refactor(memory): split context build and render"
```

---

### Task 5: 在 AgentDefinition 中加入被真实消费的 MemoryPolicy

**Files:**
- Modify: `core/definitions.py`
- Modify: `tests/test_definitions_consistency.py`
- Modify: `tests/test_model_router_and_definitions.py`

- [ ] **Step 1: 写 policy contract 失败测试**

```python
def test_every_definition_declares_consumable_memory_policy():
    from core.definitions import MemoryProfileKind

    for name, defn in AGENT_DEFINITIONS.items():
        policy = defn.memory_policy
        assert isinstance(policy.max_recent_summaries, int), name
        assert policy.max_recent_summaries >= 0, name
        assert isinstance(policy.recent_summary_agent_types, frozenset), name
        if policy.profile_kind is MemoryProfileKind.NONE:
            assert policy.allow_target_student is False, name


def test_default_memory_policies_match_agent_boundaries():
    from core.definitions import MemoryProfileKind

    assert AGENT_DEFINITIONS["tutor"].memory_policy.profile_kind is (
        MemoryProfileKind.STUDENT
    )
    assert AGENT_DEFINITIONS["generator"].memory_policy.profile_kind is (
        MemoryProfileKind.TEACHER
    )
    assert AGENT_DEFINITIONS["analytics"].memory_policy.profile_kind is (
        MemoryProfileKind.ACTOR
    )
    assert AGENT_DEFINITIONS["analytics"].memory_policy.allow_target_student is True
    assert AGENT_DEFINITIONS["reviewer"].memory_policy.profile_kind is (
        MemoryProfileKind.NONE
    )
    assert AGENT_DEFINITIONS["reviewer"].memory_policy.include_recent_summaries is False
```

- [ ] **Step 2: 运行 tests 并确认字段缺失**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_definitions_consistency.py -q
```

Expected: FAIL because `memory_policy` and policy types do not exist.

- [ ] **Step 3: 定义 policy 类型并扩展 AgentDefinition**

在 `core/definitions.py`：

```python
from enum import Enum


class MemoryProfileKind(str, Enum):
    NONE = "none"
    ACTOR = "actor"
    STUDENT = "student"
    TEACHER = "teacher"


@dataclass(frozen=True)
class MemoryPolicy:
    profile_kind: MemoryProfileKind = MemoryProfileKind.NONE
    include_recent_summaries: bool = False
    recent_summary_agent_types: frozenset[str] = frozenset()
    max_recent_summaries: int = 3
    allow_target_student: bool = False
```

在 `AgentDefinition` 增加：

```python
memory_policy: MemoryPolicy = field(default_factory=MemoryPolicy)
```

- [ ] **Step 4: 声明四个默认 policy**

```python
TUTOR_MEMORY_POLICY = MemoryPolicy(
    profile_kind=MemoryProfileKind.STUDENT,
    include_recent_summaries=True,
    recent_summary_agent_types=frozenset({"tutor"}),
    max_recent_summaries=3,
)

REVIEWER_MEMORY_POLICY = MemoryPolicy()

GENERATOR_MEMORY_POLICY = MemoryPolicy(
    profile_kind=MemoryProfileKind.TEACHER,
    include_recent_summaries=True,
    recent_summary_agent_types=frozenset({"generator"}),
    max_recent_summaries=3,
)

ANALYTICS_MEMORY_POLICY = MemoryPolicy(
    profile_kind=MemoryProfileKind.ACTOR,
    include_recent_summaries=True,
    recent_summary_agent_types=frozenset({"analytics"}),
    max_recent_summaries=3,
    allow_target_student=True,
)
```

分别给 `TUTOR_DEFINITION`、`REVIEWER_DEFINITION`、`GENERATOR_DEFINITION`、`ANALYTICS_DEFINITION` 增加对应的 `memory_policy=<NAME>_MEMORY_POLICY` 参数。

- [ ] **Step 5: 给 BaseAgent 暴露只读 policy descriptor**

在 `ai/agents/base.py` 增加：

```python
from core.definitions import MemoryPolicy


class BaseAgent(ABC):
    name: str = ""
    description = _DefinitionAttr("description", "")
    default_model_tier = _DefinitionAttr(
        "default_model_tier",
        ModelTier.BALANCED,
    )
    memory_policy = _DefinitionAttr("memory_policy", MemoryPolicy())
```

如果为避免 module import cycle，保留 `MemoryPolicy` 的 local import 或使用 `_DefinitionAttr("memory_policy", None)`，但测试必须保证已注册 agent 永远得到非 `None` policy。

- [ ] **Step 6: 增加 class/definition 一致性断言**

在 `tests/test_model_router_and_definitions.py`：

```python
def test_memory_policies_match(self):
    from core.definitions import AGENT_DEFINITIONS
    from ai.agents.tutor.agent import TutorAgent
    from ai.agents.reviewer.agent import ReviewerAgent
    from ai.agents.generator.agent import GeneratorAgent
    from ai.agents.analytics.agent import AnalyticsAgent

    agent_classes = {
        "tutor": TutorAgent,
        "reviewer": ReviewerAgent,
        "generator": GeneratorAgent,
        "analytics": AnalyticsAgent,
    }

    for name, defn in AGENT_DEFINITIONS.items():
        assert agent_classes[name].memory_policy == defn.memory_policy
```

- [ ] **Step 7: 运行 definition tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_definitions_consistency.py tests/test_model_router_and_definitions.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add core/definitions.py ai/agents/base.py tests/test_definitions_consistency.py tests/test_model_router_and_definitions.py
git commit -m "feat(memory): declare agent-specific memory policies"
```

---

### Task 6: 让 MemoryService 真实消费 AgentDefinition.memory_policy

**Files:**
- Modify: `ai/memory/service.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1: 写 agent-aware policy 失败测试**

```python
class TestAgentMemoryPolicy:
    def test_tutor_only_reads_tutor_summaries(self, db_session, app):
        with app.app_context():
            from domain.models.chat import AIConversation
            from domain.models.user import User, UserRole
            from ai.memory.service import MemoryService

            user = User(
                username="policy_student",
                password="x",
                email="policy-student@test.com",
                role=UserRole.STUDENT,
            )
            db_session.add(user)
            db_session.flush()
            db_session.add_all([
                AIConversation(
                    user_id=user.id,
                    agent_type="tutor",
                    summary="Tutor-only summary.",
                ),
                AIConversation(
                    user_id=user.id,
                    agent_type="generator",
                    summary="Generator-only summary.",
                ),
            ])
            db_session.commit()

            rendered = MemoryService.get_memory_context(
                user.id,
                "student",
                agent_name="tutor",
            )

            assert "Tutor-only summary." in rendered
            assert "Generator-only summary." not in rendered

    def test_reviewer_policy_renders_no_memory(self, db_session, app):
        with app.app_context():
            from ai.memory.service import MemoryService

            assert MemoryService.get_memory_context(
                1,
                "student",
                agent_name="reviewer",
            ) == ""
```

- [ ] **Step 2: 运行 tests 并确认 agent_name 未被消费**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agents.py::TestAgentMemoryPolicy -q
```

Expected: FAIL because `get_memory_context()` does not accept or apply `agent_name`.

- [ ] **Step 3: 实现 policy resolution**

在 `MemoryService` 增加：

```python
@staticmethod
def _policy_options(agent_name: str | None) -> dict:
    if not agent_name:
        return {}

    from core.definitions import get_definition

    definition = get_definition(agent_name)
    if definition is None:
        return {}
    policy = definition.memory_policy
    return {
        "profile_kind": policy.profile_kind.value,
        "include_recent_summaries": policy.include_recent_summaries,
        "recent_summary_agent_types": tuple(
            sorted(policy.recent_summary_agent_types)
        ),
        "max_recent_summaries": policy.max_recent_summaries,
        "allow_target_student": policy.allow_target_student,
    }
```

- [ ] **Step 4: 扩展兼容入口**

```python
def get_memory_context(
    user_id: int,
    user_role: str,
    conversation_id: int = None,
    *,
    agent_name: str | None = None,
    target_student_id: int | None = None,
) -> str:
    options = MemoryService._policy_options(agent_name)
    context = MemoryService.build_memory_context(
        user_id,
        user_role,
        conversation_id,
        target_student_id=target_student_id,
        **options,
    )
    return MemoryService.render_memory_context(context)
```

重要：

- `agent_name=None` 时 `options == {}`，保持 Task 4 的 legacy 行为。
- unknown agent 不得意外关闭 legacy context；按兼容调用处理。
- registered reviewer policy 必须返回空 context。

- [ ] **Step 5: 运行 policy + compatibility tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agents.py::TestAgentMemoryPolicy tests/test_agents.py::TestMemoryContextCompatibility tests/test_agents.py::TestMemorySummaryReplay -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add ai/memory/service.py tests/test_agents.py
git commit -m "feat(memory): consume definition policy in memory service"
```

---

### Task 7: 接线 Tutor / Generator，并锁定用户可见 prompt 不回退

**Files:**
- Modify: `ai/agents/tutor/agent.py`
- Modify: `ai/agents/generator/agent.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1: 写 Tutor system context policy test**

```python
def test_tutor_build_context_requests_tutor_policy(self, app):
    with app.app_context(), patch(
        "ai.memory.service.MemoryService.get_memory_context",
        return_value="Student Background: prior context",
    ) as get_memory:
        from ai.agents.tutor.agent import TutorAgent

        state = {
            "user_id": 7,
            "user_role": "student",
            "messages": [],
            "context": {"conversation_id": 9},
        }

        rendered = TutorAgent()._build_system_context(state)

        get_memory.assert_called_once_with(
            7,
            "student",
            conversation_id=9,
            agent_name="tutor",
        )
        assert "## Student Profile (from previous sessions)" in rendered
        assert "Student Background: prior context" in rendered
```

- [ ] **Step 2: 写 Generator system context policy test**

```python
def test_generator_build_context_requests_generator_policy(self, app):
    with app.app_context(), patch(
        "ai.memory.service.MemoryService.get_memory_context",
        return_value="Teacher Preferences: concise",
    ) as get_memory, patch(
        "ai.agents.generator.agent.GeneratorAgent._get_similar_problems",
        return_value="",
    ):
        from ai.agents.generator.agent import GeneratorAgent

        state = {
            "user_id": 8,
            "user_role": "teacher",
            "messages": [],
            "context": {"conversation_id": 10},
        }

        rendered = GeneratorAgent()._build_system_context(state)

        get_memory.assert_called_once_with(
            8,
            "teacher",
            conversation_id=10,
            agent_name="generator",
        )
        assert "## Teacher Preferences (from profile)" in rendered
        assert "Teacher Preferences: concise" in rendered
```

- [ ] **Step 3: 运行 tests 并确认 call contract 失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agents.py -k "tutor_build_context_requests_tutor_policy or generator_build_context_requests_generator_policy" -q
```

Expected: FAIL because agents do not pass `agent_name`.

- [ ] **Step 4: 修改两个 agent 调用**

Tutor：

```python
memory_ctx = MemoryService.get_memory_context(
    state["user_id"],
    state.get("user_role", "student"),
    conversation_id=context.get("conversation_id"),
    agent_name=self.name,
)
```

Generator：

```python
memory_ctx = MemoryService.get_memory_context(
    state["user_id"],
    state.get("user_role", "teacher"),
    conversation_id=context.get("conversation_id"),
    agent_name=self.name,
)
```

不要修改 section heading、KB retrieval、tool list、model tier 或 invoke/stream loop。

- [ ] **Step 5: 运行 Tutor / Generator tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agents.py -k "TutorAgent or GeneratorAgent or tutor_build_context or generator_build_context or Memory" -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add ai/agents/tutor/agent.py ai/agents/generator/agent.py tests/test_agents.py
git commit -m "feat(memory): apply tutor and generator policies"
```

---

### Task 8: 接线 Analytics target isolation，并守住 Reviewer 无 memory

**Files:**
- Modify: `ai/agents/analytics/agent.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1: 写 Analytics 调用参数 test**

```python
def test_analytics_passes_target_student_to_memory_policy(self, app):
    with app.app_context(), patch(
        "ai.memory.service.MemoryService.get_memory_context",
        return_value="Student Background: target profile",
    ) as get_memory:
        from ai.agents.analytics.agent import AnalyticsAgent

        state = {
            "user_id": 20,
            "user_role": "teacher",
            "messages": [],
            "context": {
                "conversation_id": 30,
                "target_student_id": 40,
            },
        }

        rendered = AnalyticsAgent()._build_system_context(state)

        get_memory.assert_called_once_with(
            20,
            "teacher",
            conversation_id=30,
            agent_name="analytics",
            target_student_id=40,
        )
        assert "Student Background: target profile" in rendered
```

- [ ] **Step 2: 写跨用户 isolation tests**

```python
def test_student_analytics_cannot_read_another_student_profile(
    db_session, app
):
    with app.app_context():
        from domain.models.user import User, UserRole
        from app.models.student_profile import StudentProfile
        from ai.memory.service import MemoryService

        actor = User(
            username="analytics_actor",
            password="x",
            email="analytics-actor@test.com",
            role=UserRole.STUDENT,
        )
        target = User(
            username="analytics_target",
            password="x",
            email="analytics-target@test.com",
            role=UserRole.STUDENT,
        )
        db_session.add_all([actor, target])
        db_session.flush()
        db_session.add_all([
            StudentProfile(
                student_id=actor.id,
                learning_summary="Actor profile",
            ),
            StudentProfile(
                student_id=target.id,
                learning_summary="Target private profile",
            ),
        ])
        db_session.commit()

        rendered = MemoryService.get_memory_context(
            actor.id,
            "student",
            agent_name="analytics",
            target_student_id=target.id,
        )

        assert "Actor profile" in rendered
        assert "Target private profile" not in rendered


def test_teacher_analytics_target_does_not_read_target_conversation_summaries(
    db_session, app
):
    with app.app_context():
        from domain.models.chat import AIConversation
        from domain.models.user import User, UserRole
        from app.models.student_profile import StudentProfile
        from ai.memory.service import MemoryService

        teacher = User(
            username="analytics_teacher",
            password="x",
            email="analytics-teacher@test.com",
            role=UserRole.TEACHER,
        )
        target = User(
            username="analytics_target_student",
            password="x",
            email="analytics-target-student@test.com",
            role=UserRole.STUDENT,
        )
        db_session.add_all([teacher, target])
        db_session.flush()
        db_session.add(StudentProfile(
            student_id=target.id,
            learning_summary="Target student profile",
        ))
        db_session.add_all([
            AIConversation(
                user_id=teacher.id,
                agent_type="analytics",
                summary="Teacher analytics history",
            ),
            AIConversation(
                user_id=target.id,
                agent_type="analytics",
                summary="Target private conversation",
            ),
        ])
        db_session.commit()

        rendered = MemoryService.get_memory_context(
            teacher.id,
            "teacher",
            agent_name="analytics",
            target_student_id=target.id,
        )

        assert "Target student profile" in rendered
        assert "Teacher analytics history" in rendered
        assert "Target private conversation" not in rendered
```

第二个测试必须创建 teacher actor、student target、target 的 summary，并断言：

- target `StudentProfile` 可进入 context。
- target `AIConversation.summary` 不进入 context。
- teacher 自己的 analytics summary 可以进入 context。

- [ ] **Step 3: 写 Reviewer 无调用 test**

```python
def test_reviewer_does_not_request_memory(self, app):
    with app.app_context(), patch(
        "ai.memory.service.MemoryService.get_memory_context"
    ) as get_memory:
        from ai.agents.reviewer.agent import ReviewerAgent

        ReviewerAgent()._build_system_context({
            "user_id": 1,
            "user_role": "student",
            "messages": [],
            "context": {"code": "print('ok')", "language": "python"},
        })

        get_memory.assert_not_called()
```

- [ ] **Step 4: 运行 tests 并确认 analytics 参数失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agents.py -k "analytics_passes_target or analytics_cannot_read or target_does_not_read or reviewer_does_not_request" -q
```

Expected: analytics call contract FAIL；Reviewer test PASS。

- [ ] **Step 5: 修改 Analytics 调用**

```python
memory_ctx = MemoryService.get_memory_context(
    state.get("user_id", 0),
    state.get("user_role", "student"),
    conversation_id=context.get("conversation_id"),
    agent_name=self.name,
    target_student_id=context.get("target_student_id"),
)
```

- [ ] **Step 6: 运行 Analytics / Reviewer tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agents.py -k "AnalyticsAgent or ReviewerAgent or analytics_ or reviewer_" -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add ai/agents/analytics/agent.py tests/test_agents.py
git commit -m "feat(memory): isolate analytics target context"
```

---

### Task 9: 守住 generation pipeline 的 legacy compatibility

**Files:**
- Modify: `tests/test_agent_features.py`
- Test only: `app/api/v1/ai.py`
- Test only: `ai/workers/generation_pipeline.py`

- [ ] **Step 1: 写 pipeline 兼容 test**

在 `tests/test_agent_features.py` 增加：

```python
def test_generation_pipeline_keeps_rendered_teacher_context():
    from ai.workers.generation_pipeline import _generate_problem

    state = {
        "teacher_id": 1,
        "language": "python",
        "difficulty": "medium",
        "topic": "loops",
        "test_case_count": 3,
        "prompt": "Create a loop problem",
        "teacher_context": "Teacher Preferences: concise",
        "generated_problem": None,
        "validation_results": [],
        "validation_passed": False,
        "similar_problems": [],
        "is_duplicate": False,
        "dedup_attempts": 0,
        "quality_review": None,
        "generate_attempts": 0,
        "final_draft": None,
        "error": None,
        "status": "generating",
    }

    with patch("ai.workers.generation_pipeline.AIConfig.get_llm") as get_llm:
        llm = MagicMock()
        llm.invoke.return_value.content = (
            '{"title":"Loop","solution":"pass","test_cases":[{"input":"","expected_output":""}]}'
        )
        get_llm.return_value = llm

        _generate_problem(state)

        messages = llm.invoke.call_args.args[0]
        assert "Teacher Preferences: concise" in messages[0].content
```

- [ ] **Step 2: 运行 generation tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_features.py -k "generation_pipeline or generate_problem" -q
```

Expected: PASS，不需要修改 production pipeline。

- [ ] **Step 3: 运行 API generation focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_api_ai.py -k "generate" -q
```

Expected: PASS。若现有 suite 没有 pipeline route test，记录为后续 API coverage gap，但不要在本计划中重构 route。

- [ ] **Step 4: Commit**

```powershell
git add tests/test_agent_features.py
git commit -m "test(memory): preserve generation pipeline compatibility"
```

---

### Task 10: 更新架构文档与 issue 状态

**Files:**
- Modify: `docs/architecture/data-state-memory.md`
- Modify: `docs/issues/2026-06-08-agent-memory-context-improvements.md`
- Modify: `docs/issues/README.md`
- Modify: `docs/plans/README.md`
- Modify: `docs/plans/active/2026-06-05-agent-platform-remaining-improvements-plan.md`

- [ ] **Step 1: 更新 memory 架构文档**

在 `docs/architecture/data-state-memory.md` 的 memory 章节增加“结构化治理目标态”小节，必须明确：

```markdown
### 结构化 MemoryContext 与 Agent Policy

- `MemoryService.build_memory_context()` 返回结构化 `MemoryContext`。
- `MemoryService.render_memory_context()` 是唯一字符串渲染入口。
- `AgentDefinition.memory_policy` 决定 profile 类型、summary 范围和 target student 权限。
- Reviewer 默认不读取长期画像或历史 summary。
- Legacy API 仍供 generation pipeline 等现有调用使用。

尚未实现的 budget、TTL/forget、extractor、trace audit、eval replay 继续作为后续阶段，不得描述成当前能力。
```

同时修复文档中已经归档的 shared-domain plan 链接：

```markdown
../plans/archive/2026-06-06-shared-sqlalchemy-domain-fastapi-agent-runtime-plan.md
```

- [ ] **Step 2: 更新 issue**

实施完成后将 issue 头部改为：

```markdown
> 状态: Phase 1-2 Completed
> 更新日期: 使用 `Get-Date -Format yyyy-MM-dd` 得到的完成日期
> 执行计划: [Agent Memory / Context Governance Phase 1-2 Plan](../plans/archive/2026-06-08-agent-memory-context-governance-phase1-2-plan.md)
```

在 issue 末尾增加“实施结果”：

- Phase 1/2 完成证据。
- 实际测试命令和结果。
- Phase 3-5 仍未实现。
- 不得把整个 P2 issue 标记为全部关闭；只关闭“无结构、无 agent policy”两项。

- [ ] **Step 3: 更新 issues index**

将 memory/context 条目改为：

```markdown
| [2026-06-08-agent-memory-context-improvements.md](2026-06-08-agent-memory-context-improvements.md) | Agent memory / context 治理 | Phase 1-2 完成；budget/audit/forget/replay 待后续计划 | P2 |
```

- [ ] **Step 4: 更新 plans taxonomy**

实施完成后：

1. 将本计划从 `docs/plans/active/` 移到 `docs/plans/archive/`。
2. `docs/plans/README.md` 的 active 区只保留仍在执行的上层计划。
3. 在 archive 的 Agent Platform 分组增加本计划链接和完成证据摘要。
4. 上层 remaining-improvements plan 的 Context/Memory 项标记 Phase 1-2 已完成，并保留 Phase 3-5 后续触发条件。

- [ ] **Step 5: 检查 Markdown links**

Run:

```powershell
@'
from pathlib import Path
import re

root = Path("docs")
errors = []
for path in root.rglob("*.md"):
    text = path.read_text(encoding="utf-8")
    for target in re.findall(r"\]\(([^)#]+)(?:#[^)]+)?\)", text):
        if "://" in target or target.startswith("mailto:"):
            continue
        resolved = (path.parent / target).resolve()
        if not resolved.exists():
            errors.append(f"{path}: {target}")

if errors:
    raise SystemExit("\n".join(errors))
print("markdown links ok")
'@ | .\.venv\Scripts\python.exe -
```

Expected: `markdown links ok`.

- [ ] **Step 6: Commit**

```powershell
git add docs/architecture/data-state-memory.md docs/issues docs/plans
git commit -m "docs(memory): record phase 1-2 governance state"
```

---

### Task 11: 运行 focused regression gate

**Files:**
- Test only

- [ ] **Step 1: 运行 memory / definition / repository focused suite**

Run:

```powershell
$env:SECRET_KEY='test-secret-key'
$env:DEBUG='True'
.\.venv\Scripts\python.exe -m pytest tests/test_agents.py tests/test_domain_chat_repository.py tests/test_definitions_consistency.py tests/test_model_router_and_definitions.py tests/test_agent_features.py -q
```

Expected: PASS.

- [ ] **Step 2: 运行 agent runtime regression suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_session.py tests/test_agent_runtime_kernel.py tests/test_agent_runtime_chat.py tests/test_agent_runtime_app.py tests/test_agent_registry.py tests/test_agent_contracts.py -q
```

Expected: PASS。该 gate 确认 policy 没有破坏 AgentSession definition、runtime loop、registry 或 remote runtime。

- [ ] **Step 3: 运行 API / workflow 边界回归**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_api_ai.py tests/test_workflow_routes.py tests/test_workflow_resume.py tests/test_workflow_approval_audit.py -q
```

Expected: PASS。memory 改造不应改变 workflow、approval 或 API envelope。

- [ ] **Step 4: 检查 diff**

Run:

```powershell
git diff --check
git status -sb
```

Expected:

- `git diff --check` 无输出。
- 没有 migration、schema、ToolRuntime、WorkflowEngine 或无关 UI 文件进入本任务 diff。
- 用户已有 `app/templates/dashboard.html` 修改仍保持原样且未被 staging。

- [ ] **Step 5: Commit verification adjustments**

仅当验证暴露测试或文档小修时执行：

```powershell
git add ai/memory ai/agents/tutor/agent.py ai/agents/generator/agent.py ai/agents/analytics/agent.py core/definitions.py domain/statements/chat.py domain/repositories/chat.py tests/test_agents.py tests/test_domain_chat_repository.py tests/test_definitions_consistency.py tests/test_model_router_and_definitions.py tests/test_agent_features.py docs/architecture/data-state-memory.md docs/issues docs/plans
git commit -m "test(memory): complete phase 1-2 regression coverage"
```

---

### Task 12: 运行完整质量门禁并关闭 Phase 1-2

**Files:**
- Test only
- Modify only if verification finds in-scope defects

- [ ] **Step 1: 运行完整 pytest**

Run:

```powershell
$env:SECRET_KEY='test-secret-key'
$env:DEBUG='True'
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: 完整 suite PASS；已知 skip 可保留，但不得新增与 memory 改造相关的 skip/xfail。

- [ ] **Step 2: 运行 schema drift gate**

本计划不改 schema，但必须确认没有意外 metadata drift：

```powershell
docker compose up -d --build web
docker exec educode_web flask db check
```

Expected: `No new upgrade operations detected` 或仓库当前等价成功输出。

- [ ] **Step 3: 运行 Docker health smoke**

Run:

```powershell
docker compose ps
docker compose logs --tail 100 web agent_runtime
```

Expected:

- `web`、`agent_runtime` 处于 healthy/running。
- 日志中没有 memory import cycle、definition resolution、table query 或 startup exception。

- [ ] **Step 4: 最终验收清单**

逐项确认：

- [ ] `MemoryContext` 不引用 ORM 实例。
- [ ] legacy `get_memory_context()` 文本保持兼容。
- [ ] tutor 不读取 generator/analytics summary。
- [ ] generator 不读取 student profile。
- [ ] analytics student 不能通过 `target_student_id` 读取其他学生 profile。
- [ ] analytics teacher/admin 读取目标学生 profile 时不读取目标学生 summary。
- [ ] reviewer 不读取任何长期 memory。
- [ ] policy 的每个字段都有 production consumer。
- [ ] generation pipeline 仍接收字符串 teacher context。
- [ ] 未新增 migration。
- [ ] docs 把 Phase 3-5 明确标记为未实现。

- [ ] **Step 5: 归档计划**

所有 gate 通过后：

```powershell
git mv docs/plans/active/2026-06-08-agent-memory-context-governance-phase1-2-plan.md docs/plans/archive/2026-06-08-agent-memory-context-governance-phase1-2-plan.md
```

修正 `docs/plans/README.md`、issue 和上层计划的链接后运行：

```powershell
git diff --check
git diff --cached --check
```

- [ ] **Step 6: Commit closeout**

```powershell
git add docs/plans docs/issues docs/architecture/data-state-memory.md
git commit -m "docs(memory): close phase 1-2 governance plan"
```

## 7. 验收矩阵

| Requirement | Task | 自动化证据 |
|---|---|---|
| 结构化 `MemoryContext` | 2、4 | `TestStructuredMemoryContext`、`TestMemoryContextBuilder` |
| build/render 分离 | 4 | structured tests + legacy tests |
| legacy API 兼容 | 1、4、9 | `TestMemoryContextCompatibility`、generation pipeline test |
| current conversation 排除 | 1、3、4 | `TestMemorySummaryReplay`、repository test |
| summary 按 agent 过滤 | 3、6 | repository + `TestAgentMemoryPolicy` |
| AgentDefinition policy 被真实消费 | 5、6 | definition tests + policy behavior tests |
| Tutor 策略 | 6、7 | tutor summary / prompt context tests |
| Generator 策略 | 6、7、9 | generator prompt + pipeline compatibility |
| Analytics target isolation | 8 | actor/target/summary isolation tests |
| Reviewer 默认无 memory | 5、6、8 | policy + no-call tests |
| 空表/异常降级 | 1、4 | compatibility tests |
| 文档同步 | 10、12 | markdown link check + archive closeout |
| 不改 schema/runtime kernel | 11、12 | diff inspection、full pytest、`flask db check` |

## 8. 后续阶段触发条件

本计划完成后，以下工作按已经建立的 active 计划继续执行：

### Phase 3: Budget、过滤与审计

执行计划：[Agent Memory Budget, Filtering, and Audit Phase 3 Plan](../archive/2026-06-08-agent-memory-budget-filter-audit-phase3-plan.md)

触发条件：

- memory + RAG + tool residue 出现可测量的 context 膨胀。
- 需要在 trace 中解释 included/filtered/dropped memory。
- 需要 sensitivity/TTL enforcement。

依赖本计划：

- `MemoryContext` 提供可计量 item。
- `MemoryMetadata` 提供 source/sensitivity/reason。
- `MemoryPolicy` 提供 agent-specific selection baseline。

### Phase 4: Extractor、forget 与冲突治理

执行计划：[Governed Memory Lifecycle Phase 4 Plan](../active/2026-06-08-governed-memory-lifecycle-phase4-plan.md)

触发条件：

- 开始从 conversation/submission/teacher edit 自动写入新 memory。
- 产品需要用户可见 forget/delete/suppress。

前置要求：

- 单独的持久化 memory item schema。
- 权限和审计设计。
- candidate/pending/superseded 生命周期。

### Phase 5: Eval replay snapshot

执行计划：[Eval Memory Replay Snapshot Phase 5 Plan](../active/2026-06-08-eval-memory-replay-snapshot-phase5-plan.md)

触发条件：

- production failure 需要复原当时 memory。
- eval 需要比较 recorded snapshot 与 current memory。

前置要求：

- Phase 3 trace artifact/schema。
- 稳定 snapshot serializer 和 hash。
- eval dataset schema 扩展。

## 9. 完成定义

Phase 1+2 只有在以下条件全部满足时才算完成：

1. 新结构不是旁路对象，生产 prompt 必须通过 build/render。
2. `memory_policy` 不是 registry 装饰字段，四个 agent 的行为可通过测试区分。
3. legacy API 和 generation pipeline 不回退。
4. analytics target boundary 有负向测试。
5. reviewer 无 memory 有明确 policy 和 no-call test。
6. focused suite、runtime suite、API/workflow suite、full pytest、schema drift gate 全部通过。
7. 文档准确区分已完成 Phase 1-2 与未完成 Phase 3-5。
8. 计划从 active 归档，并同步 `docs/plans/README.md` 与 `docs/issues/README.md`。
