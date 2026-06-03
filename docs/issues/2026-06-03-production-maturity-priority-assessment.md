# CodeRunner-AI Production Maturity Priority Assessment

Date: 2026-06-03

This document preserves the previous evaluation notes and recommended execution order for reducing the project's "toy project" feel and moving it toward a mature deployable platform.

## Highest Priority

### 1. Make the database migration chain the only schema source of truth

Current startup still backfills missing tables with `db.create_all()` in `app/__init__.py` around line 55. At the same time, `tests/test_migration_full_schema.py` states that Alembic cannot build the full core schema from an empty database and marks that check as `xfail` at line 1.

This makes real deployment, rollback, and multi-developer collaboration look immature. The next step should be to add a baseline migration so `flask db upgrade` can build the full schema from an empty database, then remove startup/test dependencies on `create_all()`.

### 2. Bring real E2E into CI

CI currently runs pytest and two JavaScript syntax checks in `.github/workflows/tests.yml` around line 49, but Cypress is not included in GitHub Actions. Worse, `cypress.config.js` references a missing `docker/docker-compose.yml` seed command around line 10, while `package.json` still has a placeholder failing `npm test` around line 10.

Recommended next steps:

- Fix Cypress seed wiring to the root `compose.yaml`.
- Add a CI smoke E2E job.
- Cover at minimum login, student problem solving, teacher problem creation, and AI trace/eval pages.

### 3. Tighten production security boundaries

The registration service allows users to choose `teacher` directly in `app/services/auth_service.py` around line 40, and the signup page exposes the teacher option in `signup.html` around line 52. That may be acceptable for a teaching demo, but it does not feel production-ready. Open registration should create students only; teachers should go through invite codes or admin approval.

Additional security backlog items:

- Cookies have HttpOnly/SameSite and production secure configuration in `app/core/config.py` around line 58, but there is no real CSRF token.
- Redis rate limit failures currently fail open in `app/api/v1/ai.py` around line 47.

These should be captured as explicit security hardening work.

## Second Priority

### 4. Split the large AI API file

`app/api/v1/ai.py` is currently about 2252 lines and contains chat, generation, drafts, traces, evals, workflows, knowledge endpoints, and related helpers. The functionality is strong, but the maintenance shape looks like single-file accumulation.

Recommended target:

- Split into blueprint modules such as `chat.py`, `generation.py`, `traces.py`, `evals.py`, `knowledge.py`, and `workflows.py`.
- Move business logic into services instead of keeping endpoint functions as orchestration hubs.

### 5. Unify model and DB session boundaries

The project currently has both Flask-SQLAlchemy models under `app.models.*` and runtime-neutral SQLAlchemy Base models under `core.db.models.*`. Trace/eval already uses a runtime-neutral store, but the dual ORM world still increases migration, transaction, and relationship-resolution risk.

The mature target should explicitly define:

- Which tables belong to the Flask app model layer.
- Which tables belong to the runtime store.
- Cross-boundary access through repository/service APIs only.
- No direct ad hoc imports across the boundary.

### 6. Complete the operations loop

The root `compose.yaml` already includes MySQL, Redis, Chroma, executor, workers, and MCP gateway. The executor also has read-only, non-root, `cap_drop`, and related hardening around `compose.yaml` line 153.

Missing operational maturity items:

- Backup and restore.
- Log aggregation.
- Error alerting.
- Deployment rollback.
- Resource and capacity guidance.
- A dashboard or at least runbook guidance for using trace/eval data to diagnose incidents.

### 7. Fix documentation drift

The executor architecture document still describes a remote-failure fallback to local execution in `docs/architecture/executor.md` around line 33, while the code already fail-closes in `app/services/executor_service.py` around line 72.

The README also showed Chinese mojibake in terminal output. To look professional, docs must match runtime facts and render cleanly.

## Third Priority

### 8. Productize AI quality evaluation

The eval workflow exists and can produce DB-backed harness reports, with `.github/workflows/evals.yml` around line 70. The next step is to make it a real quality program instead of a basic pass-rate check.

Recommended next steps:

- Expand the dataset.
- Record prompt and model versions.
- Promote production failures into regression cases automatically.
- Track budget and cost trends.
- Report more than pass rate.

### 9. Fully connect Human Gate and AgentTask

The AI architecture document still frames Human Gate mainly as a generated-draft approval flow in `docs/architecture/ai-agents.md` around line 30. The target is to connect Human Gate fully with the AgentTask state machine.

Finishing this would significantly improve the feel of a real agent platform.

## Recommended Execution Order

1. Migration chain as schema source of truth.
2. Cypress CI repair and smoke E2E.
3. Teacher registration approval/invite flow.
4. Split `app/api/v1/ai.py`.
5. Clarify and enforce DB model/session boundaries.

These first three items reduce the "toy" impression fastest and address the highest deployment, test, and security risks.

## Current Workspace Note

The prior analysis did not modify files. At that time, the working tree already had two uncommitted test-file changes:

- `tests/test_agents.py`
- `tests/test_s7_execute_internal.py`

Verification performed in the prior analysis:

```powershell
pytest --collect-only -q
```

Result:

```text
507 tests collected
```

The full test suite was not run.
