# Dual-ORM Convergence — Phase 0 (Make Duplication Safe) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the two genuinely dangerous symptoms of the dual-ORM split — (1) two independent DB-URL builders that can silently point at different databases, and (2) a second engine/connection-pool living inside the Flask web process — and add a CI guardrail that stops the 7 duplicate table mappings from silently drifting apart. This does NOT delete the duplicate model classes (that is gated work — see "Phase 1 and beyond").

**Architecture:** The project runs the same MySQL behind FOUR surfaces: the Flask web app (`app/`, Flask-SQLAlchemy `db.Model`, 181 `.query` call sites), a FastAPI Agent Host (`app/api/v1/agents/*`, runtime-neutral `Base`), the MCP Gateway (`mcp_gateway/`, FastAPI, neutral `Base`), and headless workers (`workers/`, neutral sessions). Workers, Agent Host, and Gateway are SEPARATE PROCESSES, so each having its own pool is normal; the only harmful in-process double-engine is the Flask web process, where `app/api/v1/ai.py` opens a neutral `db_session()` that builds a second pool. Phase 0 unifies the URL source, makes the Flask process adopt one engine, and pins the 7 shared-table mappings with an invariant test. It changes NO model identity and NO `.query` call site.

**Tech Stack:** Python 3, Flask-SQLAlchemy (`app/core/extensions.py` `db`), runtime SQLAlchemy 2.0 `Base` + engine factory (`core/db/session.py`), unified settings (`core/config.py` `get_settings()`), pytest with the `app` fixture in `tests/conftest.py` (sqlite in-memory).

---

## Background: verified current state (read before starting)

All claims checked against the code on 2026-06-06. Treat as the baseline; do not "fix" what is already as described.

- **Two URL builders, currently agreeing by luck:** `core/config.py:13` `_build_database_url()` reads `DATABASE_URL` → `MYSQL_*`/`DB_*` and exposes `Settings.DB_URL` (`core/config.py:29`). `app/core/config.py:10-27` re-implements the SAME precedence into `Config.SQLALCHEMY_DATABASE_URI`. They match today only because the two functions happen to read the same env vars; a one-sided edit makes Flask write DB-A and core write DB-B with no error.
- **Two engines, but only one process has both:** `core/db/session.py:33` `get_engine()` lazily builds its own `create_engine(settings.DB_URL, ...)`. Flask-SQLAlchemy builds its own from `SQLALCHEMY_DATABASE_URI`. In the **worker** and **mcp_gateway** and **Agent Host** processes this is fine (separate processes). Inside the **Flask web process** the only neutral-engine user is `app/api/v1/ai.py:2001-2004` (`with db_session() as session:` writing `EvalCaseRun`/`EvalCaseGraderResult`) plus read-only `app/services/trace_query_service.py`. So the Flask process today opens a 2nd pool for those paths.
- **`app/api/v1/agents/chat.py` and `workflows.py` are FastAPI, NOT Flask** (`from fastapi import APIRouter`, module docstring "runs inside FastAPI"). They are part of the Agent Host process and correctly use neutral models. Do NOT treat them as in-Flask-process usage.
- **The 7 dual-mapped tables** (`ai_conversations`, `ai_messages`, `chat_tasks`, `workflow_runs`, `workflow_steps`, `eval_runs`, `users`) each have a Flask `db.Model` and a core `Base` class. Crucially the core copies can be **deliberate read-only subsets**: `core/db/models/agent_user.py:9` `User` maps ONLY `id` + `role`, whereas `app/models/user.py:12` `User` is the full model (username/password/email/role-Enum/timestamps/relationships). So the safe invariant is "core columns ⊆ Flask columns", not "equal".
- **`core/db/metadata.py:build_target_metadata()` already imports BOTH registries** (used by Alembic). Tests can call it to guarantee both `db.metadata` and `Base.metadata` are populated before asserting.
- **`app/__init__.py:create_app()`** calls `init_extensions(app)` (which creates `db`) at line 34, then runs startup work inside `with app.app_context():` at lines 40-47. `_recover_orphaned_tasks` (line 45) uses `graph.recovery`, which touches neutral sessions — so any engine adoption MUST happen before line 45.
- **`core/db/session.py:19` `init_db()` and `:33` `get_engine()`** both write the module globals `_engine` / `_SessionLocal`. A new `set_engine()` must set the same globals so all of `get_session()`, `get_db()`, `db_session()` pick it up.
- **`tests/conftest.py`** builds the schema for BOTH registries onto the SAME sqlite `_db.engine`. After Task 2, in-process neutral sessions will resolve to `db.engine` too — which is what the tests already assume, so this REDUCES test/runtime divergence.

## Scope decisions

**In scope (Phase 0 — direction-independent, low risk, immediately shippable):**
- Single source for the production DB URL.
- Single engine/pool inside the Flask web process.
- A CI invariant that the 7 shared mappings cannot drift in the dangerous direction.

**Out of scope — gated, see "Phase 1 and beyond" (do NOT do these here):**
- Deleting any of the 7 duplicate model classes / collapsing to one class per table.
- Cross-layer transactional atomicity (sharing ONE session across Flask + neutral writes).
- Relocating the mcp models off Flask `db`.
- Touching any `.query` call site or Flask-Login wiring.

## Constraints (do not violate)

- Do NOT change any model class, column, or relationship in `app/models/*` or `core/db/models/*`.
- Do NOT alter behavior for the worker / mcp_gateway / Agent Host processes — they legitimately keep their own engine; Task 2 only adopts an engine when one is explicitly handed in (i.e. only the Flask process calls `set_engine`).
- `set_engine()` must be idempotent and must run BEFORE `_recover_orphaned_tasks(app)` in `create_app`.
- The drift guardrail (Task 3) asserts `core_columns ⊆ flask_columns`; do NOT assert equality (core read-only projections like `users` are intentionally a subset).

---

## Task 1: Single source for the production DB URL

**Files:**
- Modify: `app/core/config.py:10-27` (the base `Config` URL block)
- Test: `tests/test_db_single_url.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db_single_url.py
"""Flask and core must derive the production DB URL from ONE source, so a
one-sided edit can never point the two layers at different databases."""


def test_flask_base_config_uses_core_db_url():
    from app.core.config import Config
    from core.config import get_settings

    assert Config.SQLALCHEMY_DATABASE_URI == get_settings().DB_URL
```

- [ ] **Step 2: Run test to verify it fails (or passes by coincidence)**

Run: `pytest tests/test_db_single_url.py -v`
Expected: it may PASS today by coincidence (same env). To prove the test has teeth, temporarily `export DATABASE_URL=mysql+pymysql://a:b@h/onlycore` and re-run — it must FAIL because Flask's base `Config` rebuilt from its own block. Unset the var afterward. (If you cannot set env in the runner, skip this sub-check; Step 4 makes equality structural.)

- [ ] **Step 3: Replace the duplicated URL block with an import from core**

In [app/core/config.py](../../app/core/config.py), replace the base-class URL construction (lines 10-27, the `_db_url = os.environ.get("DATABASE_URL")` block through the `SQLALCHEMY_DATABASE_URI = (...f-string...)` else branch) with a single delegation. Keep `import os` and any `TESTING`/`DEBUG` flags untouched:

```python
class Config:
    """Base configuration"""
    # Application configuration
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    DEBUG = False
    TESTING = False

    # Single source of truth for the DB URL — core builds it once
    # (DATABASE_URL → MYSQL_* → DB_* precedence lives in core/config.py).
    from core.config import get_settings as _get_core_settings
    SQLALCHEMY_DATABASE_URI = _get_core_settings().DB_URL
```

Leave the rest of the class (`SQLALCHEMY_TRACK_MODIFICATIONS`, `SQLALCHEMY_ENGINE_OPTIONS`, etc.) and any subclasses unchanged. The `TestingConfig` sqlite override at `app/core/config.py:82` still wins for tests because it is set on the subclass.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db_single_url.py -v`
Expected: PASS. Equality is now structural — `Config.SQLALCHEMY_DATABASE_URI` IS `get_settings().DB_URL`.

- [ ] **Step 5: Smoke-check the app still imports and the sqlite test config still overrides**

Run: `pytest tests/conftest.py -q` (or any one existing test that uses the `app` fixture, e.g. `pytest tests/test_db_single_url.py tests/test_combined_metadata.py -q`)
Expected: PASS; no import error from `app.core.config`, and the test app still uses sqlite (TestingConfig override intact).

- [ ] **Step 6: Commit**

```bash
git add app/core/config.py tests/test_db_single_url.py
git commit -m "fix(db): single source for production DB URL (Flask delegates to core)"
```

---

## Task 2: One engine/pool inside the Flask web process — DEFERRED to Phase 1

**Status: attempted 2026-06-06, reverted (commit `b074214` reverted by `1b1a801`).** Moved into the gated Phase 1.

**What was tried:** add `core.db.session.set_engine(engine)` that overwrites the module globals `_engine`/`_SessionLocal`, and call it from `create_app()` to adopt Flask's engine.

**Why it was reverted:** that approach introduces **global mutable engine state** that is stomped on every `create_app()`. The test suite (and, latently, the worker process via `workers/chat.py:107` `with app.app_context()`) constructs MORE THAN ONE app/engine in a single process; the first `create_app()` overwrites the global engine that the runtime-neutral tests and headless paths depend on. Result: 7 previously-green trace/workflow tests failed with `no such table: agent_trace_links` because their `db_session()` writes were redirected to an app engine lacking the core tables. Verified: the 11 trace tests pass at the Task 1 commit and fail after this change.

**Why it is acceptable to defer:** this is the lowest-value of the three Phase 0 items. Worker / mcp_gateway / Agent Host are SEPARATE PROCESSES where a per-process pool is correct; the only in-Flask-process second pool is `app/api/v1/ai.py`'s eval-result write — a narrow path. True cross-layer atomicity is Phase 1 work anyway.

**How to do it properly in Phase 1 (lesson learned):** do NOT mutate a process-global engine from `create_app()`. Instead either (a) make `get_engine()` *context-aware* — return the Flask engine only when `flask.has_app_context()` is true, else its own — or (b) adopt the engine via an explicit, scoped handle rather than a module global, and add a conftest fixture that resets/realigns the core engine per test so multi-app test isolation holds. Re-introduce `tests/test_single_engine_in_flask.py` then.

---

## Task 3: Guardrail — the 7 shared mappings cannot drift dangerously

**Files:**
- Test: `tests/test_dual_mapping_consistency.py` (create)

This makes the Phase-4 "edit BOTH model files when you add a column" rule machine-enforced, so the deferred duplication stays safe until Phase 1 deletes it.

- [ ] **Step 1: Write the guardrail test**

```python
# tests/test_dual_mapping_consistency.py
"""While the 7 tables remain dual-mapped, the core (runtime) registry must
never carry a column the authoritative Flask model lacks, and shared columns
must keep compatible types. Core MAY be a read-only subset (e.g. users)."""

import pytest

SHARED_TABLES = [
    "ai_conversations", "ai_messages", "chat_tasks",
    "workflow_runs", "workflow_steps", "eval_runs", "users",
]


@pytest.fixture(scope="module")
def both_registries():
    # Importing the combined metadata builder forces BOTH app.models and
    # core.db.models submodules to import and register their tables.
    from core.db.metadata import build_target_metadata
    build_target_metadata()
    from app.core.extensions import db
    from core.db.session import Base
    return db.metadata, Base.metadata


@pytest.mark.parametrize("table", SHARED_TABLES)
def test_core_columns_are_subset_of_flask(both_registries, table):
    flask_md, core_md = both_registries
    flask_cols = set(flask_md.tables[table].columns.keys())
    core_cols = set(core_md.tables[table].columns.keys())
    extra = core_cols - flask_cols
    assert not extra, (
        f"{table}: core/db/models defines columns absent from the "
        f"authoritative Flask model: {sorted(extra)}. Update app/models or "
        f"remove them from core."
    )


@pytest.mark.parametrize("table", SHARED_TABLES)
def test_shared_column_types_are_compatible(both_registries, table):
    flask_md, core_md = both_registries
    flask_t = flask_md.tables[table]
    core_t = core_md.tables[table]
    for name in set(core_t.columns.keys()) & set(flask_t.columns.keys()):
        flask_type = flask_t.columns[name].type.__class__.__name__
        core_type = core_t.columns[name].type.__class__.__name__
        assert flask_type == core_type, (
            f"{table}.{name}: type drift — Flask={flask_type} core={core_type}"
        )
```

- [ ] **Step 2: Run the guardrail against current code**

Run: `pytest tests/test_dual_mapping_consistency.py -v`
Expected: PASS for the subset test. The type test may surface a REAL pre-existing drift (e.g. `users.role` is `Enum` in Flask vs `String` in core `agent_user.py`). If it fails:
- This is a genuine finding, not a test bug. For the `users.role` Enum-vs-String case, relax that one assertion with an explicit allowlist entry (documented) rather than silently — add near the top of the test:

```python
# Known, accepted projection mismatches (core read-only views). Each entry is
# a deliberate divergence, not drift: revisit when the table is de-duplicated.
ACCEPTED_TYPE_MISMATCH = {("users", "role")}  # Flask Enum(UserRole) vs core String
```
and skip those pairs in `test_shared_column_types_are_compatible`:
```python
        if (table, name) in ACCEPTED_TYPE_MISMATCH:
            continue
```
Re-run until PASS. Record any accepted entry in the issue doc (Step 4).

- [ ] **Step 3: Commit**

```bash
git add tests/test_dual_mapping_consistency.py
git commit -m "test(db): pin dual-mapped tables against dangerous drift"
```

- [ ] **Step 4: Update the issue doc**

In [docs/issues/2026-06-04-dual-orm-database-issues.md](../../docs/issues/2026-06-04-dual-orm-database-issues.md), under 五、治理方向, update #2 to note that Phase 0 unified the URL source and the in-Flask-process engine (commits above), and that #3/#4 remain gated on the FastAPI Agent Host decision (see this plan's "Phase 1 and beyond"). List any `ACCEPTED_TYPE_MISMATCH` entries found in Task 3.

```bash
git add docs/issues/2026-06-04-dual-orm-database-issues.md
git commit -m "docs(issues): record Phase 0 dual-ORM convergence (URL + engine + drift guard)"
```

---

## Acceptance Criteria (Phase 0)

- [ ] `app/core/config.py` no longer rebuilds the DB URL; `Config.SQLALCHEMY_DATABASE_URI is get_settings().DB_URL`. `tests/test_db_single_url.py` PASSES.
- [ ] Inside the Flask process, `get_engine() is db.engine`. `tests/test_single_engine_in_flask.py` PASSES.
- [ ] Worker / mcp_gateway / Agent Host processes are untouched (they never call `set_engine`, still build their own engine from the unified URL).
- [ ] `tests/test_dual_mapping_consistency.py` PASSES (with any deliberate projection mismatches explicitly allowlisted).
- [ ] No model class, `.query` call site, or Flask-Login wiring changed.

---

## Phase 1 and beyond — collapsing the 7 duplicate classes (SEPARATE, GATED plan)

**Do NOT start this without first making one architecture decision.** Phase 0 makes the duplication *safe*; deleting it requires choosing which registry survives, and that depends on the fate of the FastAPI Agent Host (`app/api/v1/agents/*`) and MCP Gateway.

**The gating decision:** Is the FastAPI Agent Host going to be **folded back into the Flask app** (true single-process monolith), or **kept/grown as a separate process** (monolith + a runtime service)?

- **If folded back in →** survivor is Flask `db.Model`. Delete the 7 core duplicates; give the few headless consumers (`workers/task_runner.py`, the `ai.py` eval write) a Flask app context (the pattern already exists at `workers/chat.py:107` `with app.app_context():`). The Agent Host routers move under Flask or get an app context. Cost: medium (a handful of files), but it ends the dual ORM.
- **If kept separate →** you are NOT a single-process monolith for that surface; the honest target is "one OWNER per table." Keep the neutral `Base` for tables the Agent Host owns and the Flask app stops writing them directly (goes through the runtime). This is the service-extraction path and is much larger; it should not be framed as "ORM cleanup."

**Why this can't be a flat checklist yet:** the Flask app has **181 `.query` call sites across 25 files** plus Flask-Login bound to `app/models/user.py:User`. Migrating the Flask side onto the neutral `Base` is therefore off the table as a quick refactor; and migrating the neutral side onto Flask `db.Model` is only cheap if the Agent Host stops being a separate process. So the per-table tasks are well-defined ONLY after the gating decision.

**Suggested per-table difficulty once the decision is made (easiest → hardest):**
1. `eval_runs` — narrow consumers (`app/api/v1/ai.py` eval write, trace queries).
2. `workflow_runs` / `workflow_steps` — Agent Host + worker.
3. `chat_tasks` — Agent Host + worker + Flask poll.
4. `ai_conversations` / `ai_messages` — Agent Host + worker + Flask history + MemoryService.
5. `users` — hardest: Flask-Login, Enum role, rich relationships, ~half of the 181 `.query` sites. The core side is only a 2-column read view, so this may be solved by deleting the core `User` and having headless RBAC reads select `role` via the shared engine, NOT by merging the full model.

When the decision is made, generate `docs/plans/active/<date>-dual-orm-collapse-<flask|neutral>.md` as its own plan and read each table's exact consumers at that time.

## Risks & Mitigations (Phase 0)

- **Circular import (Task 1):** `app/core/config.py` importing `core.config` at class-body time. Mitigated: `core/config.py` imports only stdlib + `dotenv`; no `app` dependency. Verified safe.
- **Engine adopted too late (Task 2):** if any neutral session is used before `set_engine`, it would lazily build a throwaway engine. Mitigated: adoption runs at the very start of the first `app_context` block in `create_app`, before `_ensure_tables` and before `_recover_orphaned_tasks`.
- **Adoption leaking into worker/gateway (Task 2):** those are separate processes that never construct the Flask app, so they never call `set_engine` — they keep `get_engine()`'s own engine from the unified URL. No change for them.
- **Guardrail surfacing real drift (Task 3):** the `users.role` Enum-vs-String mismatch is expected; allowlist it explicitly and record it, so the test still guards against NEW drift.
