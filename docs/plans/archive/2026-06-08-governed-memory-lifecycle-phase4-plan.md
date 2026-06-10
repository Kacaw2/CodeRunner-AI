# Governed Memory Lifecycle Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将长期 memory 从不可删除的聚合 profile 字段升级为 item 级、可候选、可批准、可冲突处理、可 TTL、可 suppress/forget 的治理对象，并让 prompt 注入读取受治理的 active item。

**Architecture:** 新增 shared-domain `MemoryItemRecord` 表与 repository，使用 `status` 表示 candidate/active/rejected/superseded/suppressed/expired。`MemoryService` 优先读取 active memory item，legacy `StudentProfile` / `TeacherPreference` 仅作为 backfill 和兼容 API 物化层；extractor 只产生 candidate，不直接覆盖 active memory。

**Tech Stack:** Python 3.11、SQLAlchemy 2.0 DomainBase、Alembic、Flask API blueprint、MemoryService、pytest、Docker `flask db check`。

---

## 1. 前置条件

必须先完成：

- Phase 1-2: structured `MemoryContext` + agent-specific policy。
- Phase 3: budget/filter/audit trace event/artifact。

若 Phase 3 未完成，不得实施本计划。原因：没有审计前写入更多 memory 会让污染路径更难排查。

## 2. 范围

本阶段实现：

- `memory_items` 表。
- item lifecycle repository。
- legacy profile/preference backfill。
- active item query、TTL 排除、suppression 排除。
- deterministic candidate extractor。
- teacher generation preference 写入 candidate。
- conversation summary candidate。
- approve/reject/suppress API。
- conflict supersede。
- `MemoryService.build_memory_context()` 从 active items 读取。
- profile endpoints 继续兼容。

本阶段不实现：

- LLM 自动抽取任意自由文本事实。
- 面向多租户的组织级隔离。
- 向量检索型 memory。
- eval replay snapshot。
- 从 trace 自动生成 memory。

## 3. 数据模型

### 3.1 Table

`domain/models/memory.py`：

```python
class MemoryItemRecord(DomainBase):
    __tablename__ = "memory_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    subject_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    memory_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    memory_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    sensitivity: Mapped[str] = mapped_column(String(30), nullable=False, default="internal")
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    source_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    superseded_by_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_china)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_china, onupdate=now_china)
```

状态枚举：

```python
ACTIVE = "active"
CANDIDATE = "candidate"
REJECTED = "rejected"
SUPERSEDED = "superseded"
SUPPRESSED = "suppressed"
EXPIRED = "expired"
```

Subject scopes：

| `subject_type` | `subject_id` | 权限 |
|---|---|---|
| `student` | user id | 学生本人、教师/admin 仅在已有班级/分析权限下可读 |
| `teacher` | user id | 教师本人、admin |
| `classroom` | classroom id | classroom owner teacher、admin |
| `course` | course key | admin only in this phase |

Phase 4 implementation may initially write only `student` and `teacher` items, but API/repository must reject unauthorized `classroom`/`course` access explicitly instead of silently allowing it。

## 4. 文件地图

### 新增

- `domain/models/memory.py`
- `domain/repositories/memory.py`
- `ai/memory/lifecycle.py`
- `ai/memory/extractor.py`
- `app/api/v1/ai_memory.py`
- `migrations/versions/e3f4a5b6c7d8_add_memory_items.py`
- `tests/test_domain_memory_repository.py`
- `tests/test_memory_lifecycle.py`
- `tests/test_memory_api.py`

### 修改

- `domain/models/__init__.py`
- `app/core/extensions.py`
- `ai/memory/service.py`
- `ai/memory/preference.py`
- `app/__init__.py`
- `tests/test_trace_schema_contract.py`
- `tests/test_migration_full_schema.py`
- `docs/architecture/data-state-memory.md`
- `docs/issues/2026-06-08-agent-memory-context-improvements.md`
- `docs/plans/README.md`

---

### Task 1: 新增 shared-domain memory model 与 migration

**Files:**
- Create: `domain/models/memory.py`
- Modify: `domain/models/__init__.py`
- Modify: `app/core/extensions.py`
- Create: `migrations/versions/e3f4a5b6c7d8_add_memory_items.py`
- Modify: `tests/test_trace_schema_contract.py`

- [ ] **Step 1: 写 schema contract 失败测试**

```python
def test_memory_items_table_has_governance_columns(app, _setup_db):
    from sqlalchemy import inspect
    from app.core.extensions import db

    with app.app_context():
        inspector = inspect(db.engine)
        columns = {
            c["name"] for c in inspector.get_columns("memory_items")
        }

    assert {
        "id",
        "subject_type",
        "subject_id",
        "memory_kind",
        "memory_key",
        "value_json",
        "value_hash",
        "status",
        "confidence",
        "sensitivity",
        "source_type",
        "source_id",
        "source_json",
        "reason",
        "superseded_by_id",
        "created_by_user_id",
        "expires_at",
        "created_at",
        "updated_at",
    } <= columns
```

- [ ] **Step 2: 实现 model**

创建第 3.1 节模型。`value_json` 必须是 JSON object，简单字符串包装为 `{"value": "..."}`。

- [ ] **Step 3: 注册模型**

`domain/models/__init__.py` 导入并加入 `__all__`。`app/core/extensions.py` app context import 中增加：

```python
from domain.models.memory import MemoryItemRecord  # noqa: F401
```

- [ ] **Step 4: 写 migration**

`down_revision = "d9a1f2c3b4e5"`。创建 table 和 indexes：

```python
op.create_table(
    "memory_items",
    sa.Column("id", sa.String(length=36), nullable=False),
    sa.Column("subject_type", sa.String(length=30), nullable=False),
    sa.Column("subject_id", sa.String(length=80), nullable=False),
    sa.Column("memory_kind", sa.String(length=40), nullable=False),
    sa.Column("memory_key", sa.String(length=120), nullable=False),
    sa.Column("value_json", sa.JSON(), nullable=False),
    sa.Column("value_hash", sa.String(length=64), nullable=False),
    sa.Column("status", sa.String(length=30), nullable=False),
    sa.Column("confidence", sa.Float(), nullable=False),
    sa.Column("sensitivity", sa.String(length=30), nullable=False),
    sa.Column("source_type", sa.String(length=50), nullable=False),
    sa.Column("source_id", sa.String(length=120), nullable=True),
    sa.Column("source_json", sa.JSON(), nullable=True),
    sa.Column("reason", sa.Text(), nullable=True),
    sa.Column("superseded_by_id", sa.String(length=36), nullable=True),
    sa.Column("created_by_user_id", sa.Integer(), nullable=True),
    sa.Column("expires_at", sa.DateTime(), nullable=True),
    sa.Column("created_at", sa.DateTime(), nullable=False),
    sa.Column("updated_at", sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint("id"),
)
```

Indexes：

```python
batch_op.create_index("ix_memory_subject_status", ["subject_type", "subject_id", "status"], unique=False)
batch_op.create_index("ix_memory_key_status", ["memory_kind", "memory_key", "status"], unique=False)
batch_op.create_index("ix_memory_value_hash", ["value_hash"], unique=False)
```

- [ ] **Step 5: 运行 schema tests**

```powershell
$env:SECRET_KEY='test-secret-key'
$env:DEBUG='True'
.\.venv\Scripts\python.exe -m pytest tests/test_trace_schema_contract.py tests/test_migration_full_schema.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add domain/models/memory.py domain/models/__init__.py app/core/extensions.py migrations/versions/e3f4a5b6c7d8_add_memory_items.py tests/test_trace_schema_contract.py tests/test_migration_full_schema.py
git commit -m "feat(memory): add governed memory item table"
```

---

### Task 2: 实现 repository lifecycle

**Files:**
- Create: `domain/repositories/memory.py`
- Create: `tests/test_domain_memory_repository.py`

- [ ] **Step 1: 写 repository tests**

```python
def test_memory_repository_creates_candidate_and_promotes(db_session):
    from domain.repositories.memory import SyncMemoryRepository

    repo = SyncMemoryRepository(db_session)
    candidate = repo.create_candidate(
        subject_type="student",
        subject_id="7",
        memory_kind="profile",
        memory_key="learning_summary",
        value_json={"value": "Needs recursion practice"},
        source_type="conversation_summary",
        source_id="11",
        created_by_user_id=7,
        reason="student asked for help with recursion",
    )
    db_session.flush()

    assert candidate.status == "candidate"
    active = repo.promote(candidate.id)
    db_session.flush()

    assert active.status == "active"
    assert repo.active_for_subject("student", "7")[0].id == active.id
```

```python
def test_promote_supersedes_conflicting_active_item(db_session):
    from domain.repositories.memory import SyncMemoryRepository

    repo = SyncMemoryRepository(db_session)
    first = repo.create_active(
        subject_type="teacher",
        subject_id="3",
        memory_kind="preference",
        memory_key="preferred_language",
        value_json={"value": "python"},
        source_type="manual",
    )
    second = repo.create_candidate(
        subject_type="teacher",
        subject_id="3",
        memory_kind="preference",
        memory_key="preferred_language",
        value_json={"value": "java"},
        source_type="generation",
    )
    db_session.flush()

    promoted = repo.promote(second.id)
    db_session.refresh(first)

    assert promoted.status == "active"
    assert first.status == "superseded"
    assert first.superseded_by_id == promoted.id
```

```python
def test_suppressed_and_expired_items_are_not_active(db_session):
    from datetime import datetime, timedelta
    from domain.repositories.memory import SyncMemoryRepository

    repo = SyncMemoryRepository(db_session)
    suppressed = repo.create_active(
        subject_type="student",
        subject_id="9",
        memory_kind="profile",
        memory_key="learning_summary",
        value_json={"value": "hide me"},
        source_type="manual",
    )
    expired = repo.create_active(
        subject_type="student",
        subject_id="9",
        memory_kind="profile",
        memory_key="temporary_preference",
        value_json={"value": "also hide"},
        source_type="manual",
        expires_at=datetime.utcnow() - timedelta(days=1),
    )
    db_session.flush()
    repo.suppress(suppressed.id)

    assert repo.active_for_subject("student", "9") == []
```

- [ ] **Step 2: 实现 repository**

必须包含：

- `create_candidate(*, subject_type, subject_id, memory_kind, memory_key, value_json, source_type, source_id=None, source_json=None, reason=None, confidence=1.0, sensitivity="internal", created_by_user_id=None, expires_at=None) -> MemoryItemRecord`
- `create_active(*, subject_type, subject_id, memory_kind, memory_key, value_json, source_type, source_id=None, source_json=None, reason=None, confidence=1.0, sensitivity="internal", created_by_user_id=None, expires_at=None) -> MemoryItemRecord`
- `promote(item_id: str) -> MemoryItemRecord`
- `reject(item_id: str) -> MemoryItemRecord`
- `suppress(item_id: str) -> MemoryItemRecord`
- `active_for_subject(subject_type: str, subject_id: str) -> list[MemoryItemRecord]`
- `candidates_for_subject(subject_type: str, subject_id: str) -> list[MemoryItemRecord]`

`value_hash` 用同一 canonical JSON hash 函数，防止同值重复候选。`promote()` 在同 subject/kind/key 上只 supersede 值不同的 active item；同 hash candidate 直接 rejected，reason 写 `duplicate active value`。

- [ ] **Step 3: 运行 tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_domain_memory_repository.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add domain/repositories/memory.py tests/test_domain_memory_repository.py
git commit -m "feat(memory): add governed item repository"
```

---

### Task 3: Backfill legacy profile fields into memory_items

**Files:**
- Create: `ai/memory/lifecycle.py`
- Modify: `tests/test_memory_lifecycle.py`

- [ ] **Step 1: 写 backfill test**

```python
def test_backfill_student_profile_creates_active_items(app, db_session, student_user):
    from app.models.student_profile import StudentProfile
    from ai.memory.lifecycle import backfill_user_memory_items
    from domain.repositories.memory import SyncMemoryRepository

    db_session.add(StudentProfile(
        student_id=student_user.id,
        learning_summary="Needs recursion practice",
        error_patterns={"WA": 2},
    ))
    db_session.commit()

    created = backfill_user_memory_items(student_user.id, "student")

    assert created >= 2
    rows = SyncMemoryRepository(db_session).active_for_subject(
        "student",
        str(student_user.id),
    )
    keys = {row.memory_key for row in rows}
    assert {"learning_summary", "error_patterns"} <= keys
```

```python
def test_backfill_is_idempotent(app, db_session, teacher_user):
    from app.models.student_profile import TeacherPreference
    from ai.memory.lifecycle import backfill_user_memory_items

    db_session.add(TeacherPreference(
        teacher_id=teacher_user.id,
        preferred_language="python",
        style_notes="Concise prompts",
    ))
    db_session.commit()

    first = backfill_user_memory_items(teacher_user.id, "teacher")
    second = backfill_user_memory_items(teacher_user.id, "teacher")

    assert first >= 2
    assert second == 0
```

- [ ] **Step 2: 实现 lifecycle helpers**

`backfill_user_memory_items(user_id, role)`：

- student: `StudentProfile` -> `subject_type="student"`。
- teacher/admin: `TeacherPreference` -> `subject_type="teacher"`。
- source_type 为 `legacy_student_profile` 或 `legacy_teacher_preference`。
- 所有 backfill item 直接 `active`。
- 不覆盖已有相同 value hash。

- [ ] **Step 3: 运行 tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_memory_lifecycle.py tests/test_domain_memory_repository.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add ai/memory/lifecycle.py tests/test_memory_lifecycle.py
git commit -m "feat(memory): backfill legacy profiles into governed items"
```

---

### Task 4: 切换 MemoryService 读 active items

**Files:**
- Modify: `ai/memory/service.py`
- Modify: `tests/test_memory_lifecycle.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1: 写 forget-effective 失败测试**

```python
def test_suppressed_memory_item_no_longer_enters_prompt(app, db_session, student_user):
    from domain.repositories.memory import SyncMemoryRepository
    from ai.memory.service import MemoryService

    repo = SyncMemoryRepository(db_session)
    item = repo.create_active(
        subject_type="student",
        subject_id=str(student_user.id),
        memory_kind="profile",
        memory_key="learning_summary",
        value_json={"value": "Do not inject this"},
        source_type="manual",
    )
    db_session.flush()
    repo.suppress(item.id)
    db_session.commit()

    rendered = MemoryService.get_memory_context(
        student_user.id,
        "student",
        agent_name="tutor",
    )

    assert "Do not inject this" not in rendered
```

- [ ] **Step 2: 修改 build_memory_context**

读 profile/preference 时：

1. 查询 `memory_items.active_for_subject()`。
2. 如果存在 active governed items，转换成 `MemoryItem`。
3. 如果不存在 active governed items，再 fallback 到 legacy `StudentProfile` / `TeacherPreference`。

映射：

| memory_key | section |
|---|---|
| `learning_summary` / `error_patterns` / `weak_areas` / `current_hint_level` | student profile |
| `style_notes` / `preferred_language` / `preferred_difficulty` / `class_weak_areas` | teacher preference |

fallback 只能在没有 active governed items 时触发；不能让 suppressed item 被 legacy fallback 重新注入。

- [ ] **Step 3: 运行 memory tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_memory_lifecycle.py tests/test_agents.py -k "Memory" -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add ai/memory/service.py tests/test_memory_lifecycle.py tests/test_agents.py
git commit -m "feat(memory): read governed active items for prompt context"
```

---

### Task 5: Candidate extractor and write-path conversion

**Files:**
- Create: `ai/memory/extractor.py`
- Modify: `ai/memory/preference.py`
- Modify: `ai/memory/service.py`
- Modify: `tests/test_memory_lifecycle.py`
- Modify: `tests/test_agent_features.py`

- [ ] **Step 1: 写 extractor tests**

```python
def test_teacher_generation_extractor_creates_candidates(app, db_session, teacher_user):
    from ai.memory.extractor import extract_from_teacher_generation
    from domain.repositories.memory import SyncMemoryRepository

    created = extract_from_teacher_generation(
        teacher_id=teacher_user.id,
        request_params={"language": "java", "difficulty": "hard", "topic": "graphs"},
        generated_question={"programming_language": "java", "difficulty": "hard"},
    )

    assert created >= 3
    rows = SyncMemoryRepository(db_session).candidates_for_subject(
        "teacher",
        str(teacher_user.id),
    )
    keys = {row.memory_key for row in rows}
    assert {"preferred_language", "preferred_difficulty", "preferred_topics"} <= keys
```

```python
def test_conversation_summary_extractor_creates_student_candidate(app, db_session, student_user):
    from ai.memory.extractor import extract_from_conversation_summary

    created = extract_from_conversation_summary(
        user_id=student_user.id,
        user_role="student",
        conversation_id=55,
        summary="Student struggled with recursion base cases.",
    )

    assert created == 1
```

- [ ] **Step 2: 实现 deterministic extractor**

Extractor 只基于已结构化字段：

- generation -> preferred_language、preferred_difficulty、preferred_topics。
- conversation summary -> learning_summary candidate。

不调用 LLM，不解析隐私字段，不读取 Chroma。

- [ ] **Step 3: 修改现有写路径**

`learn_from_generation()`：

- 先调用 extractor 创建 candidates。
- 仍可更新 legacy `TeacherPreference` 作为 compatibility materialized view。
- 不直接使 candidate active。

`generate_conversation_summary()` 的调用方暂不变；在成功持久化 summary 的路径新增 extractor 调用，找不到统一调用点时只在 service 方法内返回 summary，不硬塞 side effect。

- [ ] **Step 4: 运行 tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_memory_lifecycle.py tests/test_agent_features.py -k "PreferenceLearner or extractor or memory" -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add ai/memory/extractor.py ai/memory/preference.py ai/memory/service.py tests/test_memory_lifecycle.py tests/test_agent_features.py
git commit -m "feat(memory): create governed memory candidates"
```

---

### Task 6: Memory governance API

**Files:**
- Create: `app/api/v1/ai_memory.py`
- Modify: `app/__init__.py`
- Create: `tests/test_memory_api.py`

- [ ] **Step 1: 写 API tests**

```python
def test_user_can_list_own_memory_items(client, mock_auth_student, db_session, student_user):
    from domain.repositories.memory import SyncMemoryRepository

    SyncMemoryRepository(db_session).create_active(
        subject_type="student",
        subject_id=str(student_user.id),
        memory_kind="profile",
        memory_key="learning_summary",
        value_json={"value": "Visible to owner"},
        source_type="manual",
    )
    db_session.commit()

    resp = client.get("/api/v1/ai/memory")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["items"][0]["memory_key"] == "learning_summary"
```

```python
def test_user_can_suppress_own_memory_item(client, mock_auth_student, db_session, student_user):
    from domain.repositories.memory import SyncMemoryRepository

    item = SyncMemoryRepository(db_session).create_active(
        subject_type="student",
        subject_id=str(student_user.id),
        memory_kind="profile",
        memory_key="learning_summary",
        value_json={"value": "Forget me"},
        source_type="manual",
    )
    db_session.commit()

    resp = client.delete(f"/api/v1/ai/memory/{item.id}")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "suppressed"
```

```python
def test_teacher_can_approve_own_candidate(client, mock_auth_teacher, db_session, teacher_user):
    from domain.repositories.memory import SyncMemoryRepository

    item = SyncMemoryRepository(db_session).create_candidate(
        subject_type="teacher",
        subject_id=str(teacher_user.id),
        memory_kind="preference",
        memory_key="preferred_language",
        value_json={"value": "java"},
        source_type="generation",
    )
    db_session.commit()

    resp = client.post(f"/api/v1/ai/memory/{item.id}/approve")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "active"
```

- [ ] **Step 2: 实现 blueprint**

`bp = Blueprint("ai_memory", __name__, url_prefix="/api/v1/ai/memory")`

Endpoints：

- `GET /`: active + candidate items for current subject。
- `POST /<item_id>/approve`
- `POST /<item_id>/reject`
- `DELETE /<item_id>` -> suppress。

权限：

- student 只能操作 `subject_type=student` + 自己 id。
- teacher 只能操作 `subject_type=teacher` + 自己 id；classroom scope 必须验证 owner。
- admin 可操作全部。

错误 envelope 用 `{"error": {"code": "...", "message": "..."}}`，保持 AI API 风格。

- [ ] **Step 3: 注册 blueprint**

`app/__init__.py`：

```python
from app.api.v1.ai_memory import bp as ai_memory_bp
app.register_blueprint(ai_memory_bp)
```

- [ ] **Step 4: 运行 API tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_memory_api.py tests/test_api_ai.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/api/v1/ai_memory.py app/__init__.py tests/test_memory_api.py
git commit -m "feat(memory): expose governed memory lifecycle API"
```

---

### Task 7: Profile API compatibility and materialized view sync

**Files:**
- Modify: `ai/memory/lifecycle.py`
- Modify: `app/api/v1/ai.py`
- Modify: `tests/test_api_ai.py`
- Modify: `tests/test_memory_lifecycle.py`

- [ ] **Step 1: 写 compatibility tests**

```python
def test_approving_teacher_candidate_updates_profile_endpoint(
    client, mock_auth_teacher, db_session, teacher_user
):
    from domain.repositories.memory import SyncMemoryRepository

    repo = SyncMemoryRepository(db_session)
    candidate = repo.create_candidate(
        subject_type="teacher",
        subject_id=str(teacher_user.id),
        memory_kind="preference",
        memory_key="preferred_language",
        value_json={"value": "java"},
        source_type="generation",
    )
    db_session.commit()

    client.post(f"/api/v1/ai/memory/{candidate.id}/approve")
    resp = client.get("/api/v1/ai/profile")

    assert resp.status_code == 200
    assert resp.get_json()["preference"]["preferred_language"] == "java"
```

- [ ] **Step 2: 实现 sync helper**

`sync_legacy_profile_from_active_items(subject_type, subject_id)`：

- teacher -> update/create `TeacherPreference`。
- student -> update/create `StudentProfile`。
- suppressed/superseded 不写回。

在 `promote()` 后调用；reject 不调用；suppress 后也调用，让 legacy profile 删除/置空对应字段。

- [ ] **Step 3: 运行 tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_memory_lifecycle.py tests/test_memory_api.py tests/test_api_ai.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add ai/memory/lifecycle.py app/api/v1/ai.py tests/test_api_ai.py tests/test_memory_lifecycle.py tests/test_memory_api.py
git commit -m "feat(memory): sync governed items to legacy profile APIs"
```

---

### Task 8: 权限、TTL 与冲突验收

**Files:**
- Modify: `tests/test_memory_api.py`
- Modify: `tests/test_memory_lifecycle.py`
- Modify: `domain/repositories/memory.py`

- [ ] **Step 1: 增加负向 tests**

增加以下完整测试场景：

- `test_student_cannot_suppress_other_student_memory`: 创建属于另一 student subject 的 active item，当前学生调用 `DELETE`，断言 403、错误 code 为 `memory_forbidden`，数据库 row 仍是 `active`。
- `test_teacher_cannot_operate_student_memory_without_class_scope`: teacher 对 student item 调用 approve/reject/delete 中任一 mutation，断言 403 且 row 状态不变。
- `test_expired_items_are_marked_expired_on_query`: 创建 `expires_at < now` 的 active item，调用 `active_for_subject()`，断言结果为空并 refresh row 后状态为 `expired`。
- `test_conflict_does_not_silently_overwrite_without_approve`: 同 subject/kind/key 创建 active old value 和 candidate new value，只查询 candidate 时断言 old 仍 active、new 仍 candidate；调用 approve 后再断言 old superseded、new active。

每个 API 测试必须同时断言 status code、错误 code 和数据库 row status；repository 测试必须 refresh row 后断言最终状态。

- [ ] **Step 2: 实现缺口**

- `active_for_subject()` 查询时将已过期 active item 标记 `expired`。
- unauthorized 返回 403。
- approve 是唯一会 supersede active item 的路径。
- duplicate candidate 不创建第二条 active。

- [ ] **Step 3: 运行 tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_domain_memory_repository.py tests/test_memory_lifecycle.py tests/test_memory_api.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add domain/repositories/memory.py tests/test_memory_api.py tests/test_memory_lifecycle.py
git commit -m "test(memory): enforce lifecycle permissions and conflicts"
```

---

### Task 9: 文档、schema gate、归档

**Files:**
- Modify: `docs/architecture/data-state-memory.md`
- Modify: `docs/issues/2026-06-08-agent-memory-context-improvements.md`
- Modify: `docs/plans/README.md`
- Modify: `docs/plans/active/2026-06-05-agent-platform-remaining-improvements-plan.md`

- [ ] **Step 1: 更新文档**

必须说明：

- `memory_items` 是 prompt 注入的治理源。
- `StudentProfile` / `TeacherPreference` 是兼容物化视图，不再是唯一 prompt source。
- extractor 只产生 candidate。
- forget = suppress，不是物理删除；审计保留。
- course/classroom scope 目前拒绝未实现权限路径，不静默放行。

- [ ] **Step 2: Focused verification**

```powershell
$env:SECRET_KEY='test-secret-key'
$env:DEBUG='True'
.\.venv\Scripts\python.exe -m pytest tests/test_domain_memory_repository.py tests/test_memory_lifecycle.py tests/test_memory_api.py tests/test_agents.py tests/test_api_ai.py tests/test_migration_full_schema.py tests/test_trace_schema_contract.py -q
```

Expected: PASS.

- [ ] **Step 3: Full verification**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
docker compose up -d --build web agent_runtime
docker exec educode_web flask db upgrade head
docker exec educode_web flask db check
docker compose ps
git diff --check
```

Expected:

- pytest pass。
- migration applies。
- `flask db check` has no diff。
- Docker services healthy。

- [ ] **Step 4: 归档**

```powershell
git mv docs/plans/active/2026-06-08-governed-memory-lifecycle-phase4-plan.md docs/plans/archive/2026-06-08-governed-memory-lifecycle-phase4-plan.md
```

更新 README / issue / 上层路线。

- [ ] **Step 5: Commit**

```powershell
git add domain/models/memory.py domain/repositories/memory.py ai/memory app/api/v1/ai_memory.py app/__init__.py app/api/v1/ai.py migrations/versions/e3f4a5b6c7d8_add_memory_items.py tests docs
git commit -m "feat(memory): complete governed lifecycle"
```

## 5. 完成定义

Phase 4 完成必须同时满足：

1. `memory_items` 表由 Alembic 和 metadata 同时覆盖。
2. active/candidate/rejected/superseded/suppressed/expired 生命周期都有测试。
3. extractor 不直接写 active。
4. prompt 注入优先读取 active governed items。
5. suppress 后 memory 不再进入 prompt。
6. approve 才能 supersede。
7. profile endpoint 兼容。
8. unauthorized scope 返回 403。
9. full pytest、migration upgrade、`flask db check`、Docker health 全部通过。
