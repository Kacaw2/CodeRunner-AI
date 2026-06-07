# CodeRunner-AI Production Maturity Priority Assessment

Date: 2026-06-03
Updated: 2026-06-05

This document preserves the original production-maturity assessment, but the status below has been refreshed against the current repository state. The most important change since the original assessment is that the database migration baseline work has landed and is no longer an open P1 issue.

## Status Changes Since Original Assessment

### Closed: migration chain as schema source of truth

The original highest-priority item was to make the migration chain the only schema source of truth. This is now complete:

- `migrations/versions/e21895a59f7d_baseline_full_schema.py` is the full baseline migration with `down_revision = None`.
- `migrations/env.py` reads combined metadata through `core/db/metadata.py:build_target_metadata()`.
- `tests/test_migration_full_schema.py` is now a normal passing gate instead of an xfail placeholder.
- `app/__init__.py:_ensure_tables()` verifies that required tables exist and logs `flask db upgrade head` guidance; it does not call `db.create_all()`.

This closes the original deployment blocker around empty-database rebuilds and runtime schema creation.

## Highest Priority

### 1. Bring real E2E into CI

CI currently runs pytest and JavaScript syntax checks in `.github/workflows/tests.yml`, but Cypress is not included in GitHub Actions. `cypress.config.js` still references a missing `docker/docker-compose.yml` seed command, while `package.json` still has a placeholder failing `npm test`.

Recommended next steps:

- Fix Cypress seed wiring to the root `compose.yaml`.
- Add a CI smoke E2E job.
- Cover at minimum login, student problem solving, teacher problem creation, and AI trace/eval pages.

### 2. Tighten production security boundaries

The registration service allows users to choose `teacher` directly in `app/services/auth_service.py`, and the signup page exposes the teacher option in `signup.html`. That may be acceptable for a teaching demo, but it does not feel production-ready. Open registration should create students only; teachers should go through invite codes or admin approval.

Additional security backlog items:

- Cookies have HttpOnly/SameSite and production secure configuration in `app/core/config.py`, but there is no real CSRF token.
- Redis rate limit failures currently fail open in `app/api/v1/ai.py`.

These should be captured as explicit security hardening work.

## Second Priority

### 3. Split the large AI API file

`app/api/v1/ai.py` still contains chat, generation, drafts, traces, evals, workflows, knowledge endpoints, and related helpers. The functionality is strong, but the maintenance shape still looks like single-file accumulation.

Recommended target:

- Split into blueprint modules such as `chat.py`, `generation.py`, `traces.py`, `evals.py`, `knowledge.py`, and `workflows.py`.
- Move business logic into services instead of keeping endpoint functions as orchestration hubs.

### 4. Finish DB model/session boundary decisions

The project still has both Flask-SQLAlchemy models under `app.models.*` and runtime-neutral SQLAlchemy Base models under `core.db.models.*`. The migration baseline now sees both worlds, but the architecture still has two engines, two sessions, and several duplicated mapped classes.

The mature target should explicitly define:

- Which tables belong to the Flask app model layer.
- Which tables belong to the runtime store.
- Whether runtime stores should reuse the Flask engine in-process or remain separate for Agent Host portability.
- Cross-boundary access through repository/service APIs only.
- No direct ad hoc imports across the boundary.

### 5. Complete the operations loop

The root `compose.yaml` already includes MySQL, Redis, Chroma, executor, workers, and MCP gateway. The executor also has read-only, non-root, `cap_drop`, and related hardening.

Missing operational maturity items:

- Backup and restore.
- Log aggregation.
- Error alerting.
- Deployment rollback.
- Resource and capacity guidance.
- A dashboard or at least runbook guidance for using trace/eval data to diagnose incidents.

## Third Priority

### 6. Productize AI quality evaluation

The eval workflow exists and can produce DB-backed harness reports, and the agent platform has trace-bound eval foundations. The next step is to make it a real quality program instead of a basic pass-rate check.

Recommended next steps:

- Expand and govern the dataset layers.
- Record prompt, model, tool catalog, and runtime versions.
- Promote production failures into regression cases automatically.
- Track budget and cost trends.
- Report more than pass rate.
- Split fast eval vs full eval in local and CI workflows.

This now aligns with [the active remaining-improvements plan](../plans/active/2026-06-05-agent-platform-remaining-improvements-plan.md).

### 7. ToolRuntime operational guardrails

Phase 3.5 completed retry policy consumption and output-schema enforce toggle, but operational guardrails remain future work:

- per-tool / per-user quota.
- per-tool circuit breaker.
- write-tool idempotency.
- live streamable-http integration test.

### 8. Fix documentation drift continuously

The most urgent drift around migration/schema source of truth has been fixed in this directory. The rule remains: docs must match runtime facts and render cleanly.

## Recommended Execution Order

1. Cypress CI repair and smoke E2E.
2. Teacher registration approval/invite flow plus CSRF/rate-limit hardening.
3. Split `app/api/v1/ai.py`.
4. Clarify and enforce DB model/session boundaries.
5. Productize EvalOps/replay and ToolRuntime operational guardrails.

## Current Workspace Note

This document is a status update only. It does not imply the original open work has been implemented beyond the closed migration/schema item listed above.
