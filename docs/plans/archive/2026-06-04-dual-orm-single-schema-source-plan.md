# Dual-ORM → Single Schema Source Implementation Plan

> 状态：Archived / Done（数据库/schema 基础设施方案，已从 active 归档）
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Alembic the single source of truth for the DB schema by giving `migrations/env.py` a combined view of both ORM registries and squashing the chain into one baseline that builds the complete schema from an empty MySQL, then retiring `db.create_all()` from the production startup path.

**Architecture:** The project maps tables across two SQLAlchemy registries (Flask `db.Model` in `app/models/*` and runtime `Base` in `core/db/models/*`); 7 tables are defined in both, and `migrations/env.py` only sees Flask's half — so autogenerate is blind to the core tables and the real schema source is the boot-time `create_all()`. This plan does NOT unify the two ORMs or the two engines (deferred — see Scope). It does the migration-first work from the existing schema strategy: (1) build one de-duplicated `target_metadata` (Flask wins on shared names, core-only tables added on top) so Alembic can see everything; (2) replace the partial chain with a single squashed baseline that `flask db upgrade head` can run on a truly empty DB; (3) remove the production `create_all()` fallback.

**Tech Stack:** Python 3, Flask-SQLAlchemy + Flask-Migrate (Alembic), runtime SQLAlchemy 2.0 `Base` (`core/db/session.py`), MySQL 8.0 (real test DB), pytest (`tests/` with `app` fixture in `tests/conftest.py`).

---

## Background: verified current state (read before starting)

All claims below were checked against the code on 2026-06-04. Treat as the baseline; do not "fix" what is already as described.

- `migrations/env.py:48-51` `get_metadata()` returns `current_app.extensions['migrate'].db.metadata` — **only the Flask-SQLAlchemy metadata**. The runtime `Base` tables (`agent_trace_runs`, `agent_trace_spans`, `agent_trace_events`, `agent_trace_artifacts`, `agent_trace_links`, `eval_case_runs`, `eval_case_grader_results`, plus the mcp tables) are invisible to autogenerate.
- `core/db/session.py:13` defines its own `Base = declarative_base()`; `:24,:37` build a **second** `create_engine(...)` (separate pool). At runtime the two ORMs use two engines.
- The 7 dual-mapped tables (same physical table, two mapped classes): `ai_conversations`, `ai_messages` (`app/models/ai_conversation.py` vs `core/db/models/ai_conversation.py`), `chat_tasks` (`app/models/chat_task.py` vs `core/db/models/chat_task.py`), `workflow_runs`, `workflow_steps` (`app/models/workflow.py` vs `core/db/models/workflow.py`), `eval_runs` (`app/models/eval_run.py` vs `core/db/models/agent_trace.py`), `users` (`app/models/user.py` vs `core/db/models/agent_user.py`). **Combining the two metadatas naively will raise "table already defined" on these 7 names.**
- `core/db/models/mcp_api_key.py:3`, `mcp_audit_log.py:3`, `mcp_approval.py:3` all `from app.core.extensions import db` and subclass `db.Model` — i.e. core-located files that actually register into the **Flask** metadata. (Useful here: it means these 3 are already visible to env.py.)
- Migration root is `migrations/versions/f9bf29de9f8f_*.py` with `down_revision = None`; its `upgrade()` is an **ALTER** (`add_solution_explanation`) that assumes the `question` table already exists. **No migration creates the core tables from empty.**
- `app/__init__.py:55-77` `_ensure_tables()` inspects for a subset of tables and calls `db.create_all()` (Flask metadata only) on boot — the production schema fallback.
- `tests/conftest.py:32` `_db.create_all()` and `:42` `core_session.Base.metadata.create_all(bind=_db.engine)` build the test schema from BOTH registries onto the **same** `_db.engine` (tests mask the dual-engine split).
- `tests/test_migration_full_schema.py:125` is `@pytest.mark.xfail` — the gate asserting `upgrade head` on an empty MySQL builds the complete schema. Flipping it to PASS is the success signal for Task 2.

## Scope decisions

**In scope (aligns with the migration-first schema strategy + the architecture-upgrade roadmap):**
- Governance direction #1 (migration baseline) and #5 (Alembic sees all metadata) from `docs/issues/2026-06-04-dual-orm-database-issues.md`.

**Out of scope — deferred, with reasons (do NOT do these here):**
- Direction #2 "unify engines/URL by making core reuse Flask's engine" — conflicts with the roadmap's direction that the runtime/Agent Host become **independent of Flask** (`claude-code-inspired-architecture-upgrade-plan.md` Phase 3, FastAPI Agent Host as a standalone service; `workers/task_runner.py` uses plain `core.db`). Pointing core back at Flask is the opposite vector. Needs its own decision before any code.
- Direction #3 "one mapped class per table" — directly contradicts the currently accepted transitional state. The Phase 4 plan hard-requires "any column add must change BOTH model files" and the schema strategy explicitly allows "dual-declare during transition". Full dedup is a later, separate effort.
- Direction #4 "relocate mcp models off Flask `db`" — couples with Phase 4 T2, which plans to **reuse/extend** `core/db/models/mcp_approval.py`. Coordinate there, not here.

This plan stays a self-contained, testable unit: schema becomes reproducible from migrations without touching ORM identity, engines, or model ownership.

## Prerequisites

- A real, empty MySQL 8.0 reachable for Task 2/3 validation. The schema strategy notes `testcontainers[mysql]` install was proxy-blocked in this env; the fallback is a local container:
  ```bash
  docker run -d --rm --name crai-mig-test -e MYSQL_ROOT_PASSWORD=pw -e MYSQL_DATABASE=crai -p 3307:3306 mysql:8.0
  # wait until healthy, then:
  export TEST_MYSQL_URL="mysql+pymysql://root:pw@127.0.0.1:3307"
  ```
- `pip install pymysql cryptography` if not already present (needed for `mysql+pymysql`).

## File Structure

| File | Responsibility | Created/Modified |
|---|---|---|
| `core/db/metadata.py` | `build_target_metadata()` — one de-duplicated `MetaData` (Flask wins on shared names, core-only tables added) | Create |
| `migrations/env.py:48-51` | `get_metadata()` returns the combined metadata | Modify |
| `tests/test_combined_metadata.py` | Unit test: combined metadata has core-only tables and no duplicate collision | Create |
| `migrations/versions/<new>_baseline_full_schema.py` | Single squashed baseline (`down_revision=None`) creating the complete schema | Create (replaces chain) |
| `migrations/versions/*` (existing 14 files) | Removed — collapsed into the baseline | Delete |
| `tests/test_migration_full_schema.py:125` | Remove `xfail`; becomes a normal gate test | Modify |
| `app/__init__.py:55-77` | `_ensure_tables()` no longer calls `create_all()`; relies on `upgrade head` | Modify |
| `docs/issues/2026-06-04-dual-orm-database-issues.md` | Mark directions #1/#5 resolved; note #2/#3/#4 deferred | Modify |

## Constraints (do not violate)

- Do NOT merge the two engines, dedup the model classes, or move the mcp models (out of scope above).
- `build_target_metadata()` MUST keep Flask's definition authoritative for the 7 shared table names — copying core's version of `users`/`ai_conversations`/etc. could silently change column/index/constraint details.
- The squashed baseline in Task 2 is **autogenerated then human-reviewed** against the checklist — do not hand-fabricate `create_table` calls and assume they are complete.
- Deleting the existing migration chain is irreversible for migration *history*. Existing deployed DBs MUST be `flask db stamp <baseline>`'d (Task 2 Step 7), never re-run from empty. Confirm with a human before deleting `migrations/versions/*`.
- Do NOT remove `create_all()` from `tests/conftest.py` in this plan — the unit suite still runs on its current test DB; moving the whole suite onto MySQL is a separate effort. Only the production startup `create_all()` is retired (Task 3).

---

## Task 1: Combined, de-duplicated target_metadata

**Files:**
- Create: `core/db/metadata.py`
- Modify: `migrations/env.py:48-51`
- Test: `tests/test_combined_metadata.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_combined_metadata.py
"""The Alembic target metadata must see BOTH ORM registries without colliding
on the 7 dual-mapped table names."""


def test_combined_metadata_includes_core_only_tables(app):
    from core.db.metadata import build_target_metadata

    md = build_target_metadata()
    # Previously invisible to Flask-only autogenerate:
    assert "agent_trace_runs" in md.tables
    assert "agent_trace_spans" in md.tables
    assert "eval_case_runs" in md.tables


def test_combined_metadata_dedupes_shared_tables(app):
    from core.db.metadata import build_target_metadata

    md = build_target_metadata()
    # Shared names present exactly once (build did not raise on duplicates):
    for name in ("users", "ai_conversations", "ai_messages",
                 "chat_tasks", "workflow_runs", "workflow_steps", "eval_runs"):
        assert name in md.tables


def test_combined_metadata_shared_table_is_flask_definition(app):
    from core.db.metadata import build_target_metadata
    from app.core.extensions import db

    md = build_target_metadata()
    # Flask's column set wins for a shared table.
    flask_cols = set(db.metadata.tables["users"].columns.keys())
    combined_cols = set(md.tables["users"].columns.keys())
    assert combined_cols == flask_cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_combined_metadata.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.db.metadata'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/db/metadata.py
"""Single combined MetaData for Alembic autogenerate across both ORM layers.

Some tables are mapped in BOTH the Flask-SQLAlchemy registry (app/models) and
the runtime SQLAlchemy registry (core/db/models). To give Alembic one
non-colliding view, the Flask definition is authoritative for any shared table
name; only core-exclusive tables are copied in on top.

This is a transitional bridge, not a merge of the two ORMs — see
docs/plans/archive/2026-06-04-dual-orm-single-schema-source-plan.md.
"""

import importlib
import pkgutil

from sqlalchemy import MetaData


def _import_all_submodules(package_name: str) -> None:
    """Import every submodule so its mapped tables register on the metadata.
    NOTE (verified 2026-06-04): core/db/models/__init__.py is empty, so a plain
    ``import core.db.models`` leaves Base.metadata EMPTY — each module must be
    imported explicitly."""
    package = importlib.import_module(package_name)
    if not hasattr(package, "__path__"):
        return
    for mod in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{package_name}.{mod.name}")


def build_target_metadata() -> MetaData:
    _import_all_submodules("app.models")  # populates db.metadata
    _import_all_submodules("core.db.models")  # populates Base.metadata

    from app.core.extensions import db
    from core.db.session import Base

    combined = MetaData()
    for table in db.metadata.tables.values():
        table.to_metadata(combined)
    for name, table in Base.metadata.tables.items():
        if name not in combined.tables:  # Flask definition wins on shared names
            table.to_metadata(combined)
    return combined
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_combined_metadata.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Wire env.py to the combined metadata**

In [migrations/env.py:48-51](../../migrations/env.py), replace `get_metadata()`:

```python
def get_metadata():
    from core.db.metadata import build_target_metadata
    return build_target_metadata()
```

- [ ] **Step 6: Verify autogenerate now sees core tables (no destructive diff)**

Run (against a DB that already has the full schema, e.g. dev): `flask db migrate -m "probe" --sql 2>&1 | head -40` — or `flask db migrate -m "probe"` then inspect the generated file.
Expected: the generated migration does NOT contain `op.drop_table('agent_trace_runs')` (or any core table). Before this task, autogenerate would have proposed dropping them. **Delete the probe migration file afterward** — it is only a check.

> DEFERRED to Task 2 setup (2026-06-04): this probe needs a populated DB; the
> empty MySQL stood up in Task 2 Step 1 + a one-off `upgrade head` gives a clean
> place to run it. The wiring correctness (env.py → build_target_metadata) is
> already proven by `tests/test_combined_metadata.py`.

- [ ] **Step 7: Commit**

```bash
git add core/db/metadata.py migrations/env.py tests/test_combined_metadata.py
git commit -m "feat(migrations): combined de-duplicated target_metadata for autogenerate"
```

---

## Task 2: Squashed baseline that builds the full schema from empty

**Files:**
- Create: `migrations/versions/<new>_baseline_full_schema.py` (autogenerated)
- Delete: all existing `migrations/versions/*.py`
- Modify: `tests/test_migration_full_schema.py:125`

> This task rewrites migration history. Confirm with a human before Step 3 (deletion). Existing deployed DBs are handled by Step 7 (`stamp`), not by re-running.

- [ ] **Step 1: Start an empty MySQL and point the app at it**

```bash
docker run -d --rm --name crai-mig-test -e MYSQL_ROOT_PASSWORD=pw -e MYSQL_DATABASE=crai -p 3307:3306 mysql:8.0
# wait ~15s for init
export SQLALCHEMY_DATABASE_URI="mysql+pymysql://root:pw@127.0.0.1:3307/crai"
export DATABASE_URL="$SQLALCHEMY_DATABASE_URI"
```
Expected: `docker ps` shows `crai-mig-test` healthy; the DB `crai` is empty.

- [ ] **Step 2: Generate the baseline against the empty DB**

With the empty DB and the combined metadata (Task 1), autogenerate emits CREATE for every table:

```bash
flask db revision --autogenerate -m "baseline full schema"
```
Expected: a new file under `migrations/versions/` whose `upgrade()` is a sequence of `op.create_table(...)` covering all tables. Note its revision id.

- [ ] **Step 3: Make it the sole root and delete the old chain**

1. Open the new file; set `down_revision = None`.
2. Delete every OTHER file in `migrations/versions/` (the 14 pre-existing migrations).

```bash
# after confirming the new baseline file name:
git rm migrations/versions/f9bf29de9f8f_*.py migrations/versions/6ed1b6dd2b48_*.py \
       migrations/versions/81ad73512a67_*.py migrations/versions/a1b2c3d4e5f6_*.py \
       migrations/versions/b2c3d4e5f6a7_*.py migrations/versions/c3d4e5f6a7b8_*.py \
       migrations/versions/20260522_*.py migrations/versions/20260523_*.py \
       migrations/versions/20260525_*.py migrations/versions/20260526_*.py \
       migrations/versions/20260601_*.py
```
Expected: `migrations/versions/` contains exactly one file — the baseline.

- [ ] **Step 4: Review the baseline against this checklist (do not skip)**

Open the baseline `upgrade()` and confirm:
- Every Flask table from `app/models/*` is created (spot-check: `users`, `problems`, `questions`, `submissions`, `ai_conversations`, `ai_messages`, `chat_tasks`, `workflow_runs`, `workflow_steps`, `eval_runs`, `agent_tasks`, `ai_audit_logs`).
- Every core-only table is created: `agent_trace_runs`, `agent_trace_spans`, `agent_trace_events`, `agent_trace_artifacts`, `agent_trace_links`, `eval_case_runs`, `eval_case_grader_results`, `mcp_api_keys`, `mcp_audit_logs`, `mcp_tool_approvals`.
- `create_table` order satisfies FKs: referenced tables (`users`, `ai_conversations`, `ai_messages`, `mcp_api_keys`) appear before the tables that reference them (`chat_tasks`, mcp child tables). Alembic sorts by dependency, but cross-registry FKs (`core/db/models/chat_task.py` → `users.id`) are the risk area — reorder `op.create_table` calls if a referenced table comes later.
- `downgrade()` drops the tables in reverse order.

- [ ] **Step 5: Validate on a fresh empty DB**

```bash
# recreate an empty DB to prove from-scratch build
docker exec crai-mig-test mysql -uroot -ppw -e "DROP DATABASE crai; CREATE DATABASE crai;"
flask db upgrade head
```
Expected: completes with no error; `SHOW TABLES` lists all tables from Step 4.

- [ ] **Step 6: Flip the gate test from xfail to a real pass**

In [tests/test_migration_full_schema.py:125](../../tests/test_migration_full_schema.py), remove the `@pytest.mark.xfail(...)` decorator on `test_alembic_upgrade_head_builds_complete_core_schema`. Then:

```bash
TEST_MYSQL_URL="mysql+pymysql://root:pw@127.0.0.1:3307" pytest tests/test_migration_full_schema.py -v
```
Expected: PASS (was xfail). If it errors on a missing table, return to Step 4 — the baseline is incomplete.

- [ ] **Step 7: Document the one-time stamp for existing DBs**

Add to the top of the baseline file as a module docstring:

```python
"""Baseline: full schema from empty.

Existing deployments whose schema was built by db.create_all() + the old chain
must run ONCE, instead of `upgrade head`:

    flask db stamp <THIS_REVISION_ID>

This marks the existing schema as already at the baseline without re-creating
tables. Fresh/empty databases use the normal `flask db upgrade head`.
"""
```

- [ ] **Step 8: Commit**

```bash
git add migrations/versions tests/test_migration_full_schema.py
git commit -m "feat(migrations): squash chain into a single full-schema baseline"
```

---

## Task 3: Retire the production create_all() fallback

**Files:**
- Modify: `app/__init__.py:55-77`
- Test: `tests/test_migration_full_schema.py` (already green from Task 2 is the guard)

The schema is now reproducible from the baseline, so the boot-time `create_all()` is no longer the source of truth. Deploy must run `flask db upgrade head` (or `stamp` for legacy DBs) before serving. `tests/conftest.py` create_all stays (out of scope — see Constraints).

- [ ] **Step 1: Replace `_ensure_tables` with a schema check (no create)**

In [app/__init__.py:55-77](../../app/__init__.py), replace the body so it verifies the migration ran rather than silently creating tables:

```python
def _ensure_tables(app):
    """Verify the schema was migrated. Does NOT create tables — the schema is
    owned by Alembic now (run `flask db upgrade head` on deploy)."""
    try:
        from app.core.extensions import db
        from sqlalchemy import inspect
        existing = set(inspect(db.engine).get_table_names())
        required = {
            "users", "agent_trace_runs", "chat_tasks", "workflow_runs",
            "mcp_api_keys", "mcp_audit_logs", "mcp_tool_approvals",
        }
        missing = required - existing
        if missing:
            app.logger.error(
                "Startup: schema missing %s — run `flask db upgrade head`", missing
            )
        else:
            app.logger.info("Startup: schema present (Alembic-managed)")
    except Exception as e:
        app.logger.error("Startup: schema check FAILED: %s", e, exc_info=True)
```

- [ ] **Step 2: Confirm no other production path calls create_all**

Run: `grep -rn "create_all" app/ core/ workers/ --include=*.py`
Expected: the only remaining hits are `app/core/init_db.py` (an explicit dev helper, not the boot path) and NOT `app/__init__.py`. If `init_db.create_all()` is wired into startup, leave it for a follow-up — note it in the issue doc.

- [ ] **Step 3: Run the existing app/boot and DB test suites for no regression**

Run: `pytest tests/test_migration_full_schema.py tests/conftest.py -q` then the broader DB-touching suites (e.g. `pytest tests/ -k "migration or db or model" -q`).
Expected: PASS. The gate test still builds from empty; nothing depends on the boot `create_all()` anymore.

- [ ] **Step 4: Commit**

```bash
git add app/__init__.py
git commit -m "refactor(startup): retire create_all fallback; schema is Alembic-owned"
```

- [ ] **Step 5: Update the issue doc**

In `docs/issues/2026-06-04-dual-orm-database-issues.md`, under 四、治理方向, mark #1 and #5 as **done** (with a pointer to this plan), and add a line that #2/#3/#4 are deferred per the architecture roadmap.

```bash
git add docs/issues/2026-06-04-dual-orm-database-issues.md
git commit -m "docs(issues): mark dual-ORM directions #1/#5 done, #2/#3/#4 deferred"
```

---

## Acceptance Criteria

- [x] `migrations/env.py` autogenerate sees core tables; the baseline autogenerate emitted CREATE for all `agent_trace_*` / `eval_case_*` tables (supersedes the Task 1 Step 6 drop-probe).
- [x] `flask db upgrade head` on a truly empty MySQL builds the COMPLETE schema (35 tables); `tests/test_migration_full_schema.py` PASSES (no longer xfail) (Task 2 Step 6).
- [x] `migrations/versions/` contains exactly one baseline `e21895a59f7d` with `down_revision = None` (Task 2 Step 3).
- [x] Production boot no longer calls `db.create_all()`; missing schema is logged as an error telling the operator to run `upgrade head` (Task 3 Step 1).
- [x] No engine merge, no model dedup, no mcp relocation happened (Scope honored).

## Execution log (2026-06-04)

- **Task ordering deviation (necessary):** Task 3 Step 1 (retire boot `db.create_all()`) had to run BEFORE Task 2's baseline autogenerate. Reason: `FLASK_APP=run.py flask db revision --autogenerate` runs `create_app()`, whose old `_ensure_tables()` called `db.create_all()` and populated the empty MySQL with all Flask tables *before* Alembic compared metadata — so the first baseline contained only the 7 core-only tables. After retiring the boot `create_all()` and resetting the DB, the regenerated baseline (`e21895a59f7d`) correctly emits all 35 tables.
- **Chain deleted before generation:** the 14 old migrations were `git rm`'d first (vs the plan's Step2→Step3 order) so autogenerate against an empty DB produced a fresh root (`down_revision=None`) instead of hitting Alembic's "Target database is not up to date".
- **Port 3308, not 3307:** 3307 is held by the running `educode_db` dev container; the throwaway `crai-mig-test` used 3308 and was removed after validation.
- **Follow-up (out of this plan):** `workers/__main__.py:51` still calls `Base.metadata.create_all(engine)` on worker startup (core trace/eval tables only). The baseline now covers those tables; retiring this second boot path is a separate cleanup, noted in the issue doc.
- Commits: `feat(migrations): combined de-duplicated target_metadata` (Task 1), `feat(migrations): squash chain into a single full-schema baseline` (Task 2), `refactor(startup): retire create_all fallback` (Task 3), `docs(issues): mark dual-ORM directions #1/#5 done`.

## Out of scope (tracked separately)

- Unifying the two engines / URLs (direction #2) — pending a roadmap decision on Flask-independence of the runtime.
- Collapsing the 7 dual-mapped tables to one class each (direction #3) — conflicts with the Phase 4 "edit both models" constraint.
- Relocating the mcp models off Flask `db` (direction #4) — coordinate with Phase 4 T2.
- Moving the pytest suite onto a real MySQL and removing `tests/conftest.py` create_all — separate test-infra effort.

## Risks & Mitigations

- **`to_metadata` cross-registry FK remap (Task 1):** copying core-only tables whose FKs point at Flask tables (`chat_tasks.user_id → users.id`) relies on the referenced table already being in `combined`. Flask tables are copied first, so `users`/`ai_conversations` exist before core tables are added — order is load-bearing; keep the two loops in that order.
- **Incomplete baseline (Task 2):** autogenerate can miss server-side defaults or check constraints. Step 4's checklist + Step 5's from-empty build are the guard; the gate test is the final proof.
- **Breaking existing deployments (Task 2):** never run the from-empty baseline against a populated DB — use `flask db stamp` (Step 7). This is the irreversible step; confirm with a human before deleting the old chain.
- **FK ordering in MySQL (Task 2):** unlike SQLite, MySQL enforces FK creation order. If `upgrade head` fails on a foreign key, reorder the `op.create_table` calls so referenced tables come first.
