# Project Optimization Stage 1 Schema Fail-Fast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `executing-plans` task-by-task. Do not begin Task 1 until this plan is approved. Use `finishing-a-development-branch` after Task 8 verification.

**Goal:** Ensure every real API and Worker process refuses to serve or claim work unless the database contains exactly one `alembic_version` row equal to the code's `CURRENT_SCHEMA_REVISION`, while keeping migrations explicit and never changing business state during compatibility checks.

**Architecture:** Add one read-only compatibility guard under `app.maintenance`, reuse it from an explicit preflight CLI, the FastAPI lifespan, the Worker CLI, container dispatch and supported PowerShell launchers. Runtime startup creates one bounded engine, proves schema compatibility, then exposes that same engine/session factory to request handlers or constructs the Worker runner. Docker Compose removes the implicit `migrate` dependency and moves migration into an `operations` profile. A versioned entrance manifest and process tests prove all nine Stage 0 launch identities are covered.

**Tech stack:** Python 3.14, FastAPI lifespan, SQLAlchemy 2, Alembic revision metadata, Uvicorn, PowerShell 7, Docker Compose, MySQL 8.0/8.4, pytest, Ruff and mypy.

## Global Constraints

- This plan implements only roadmap Stage 1. Worker heartbeats, queue metrics, monitoring APIs/UI, schema `0023`, UI framework dependencies and business workflow changes are out of scope.
- Baseline commit is `0f6f3d1d059c58f37979df7fec148da859019bd3`; baseline tree is `1539e53fe9e060c9cdda9c7d3ea5f2d81adc45b2`.
- Implementation branch is `codex/project-optimization-stage1` in `D:\CLSEN_Data_Web-worktrees\project-optimization-stage1`.
- Do not implement Stage 1 on `codex/ui-quick-prototype`; that branch remains an independently reviewable prototype and is not a Stage 1 dependency.
- Do not read, enumerate, modify, stage or commit `data/`, real customer data, backups, private corpora or credentials.
- The compatibility guard is read-only: no DDL, DML, Alembic command, migration, retry that changes state, `CREATE TABLE`, or manual update of `alembic_version` is allowed in runtime code.
- No production or user database migration is authorized by this plan. Migration/revision mismatch rehearsals use only disposable MySQL 8.0/8.4 databases owned by the test runners.
- Runtime compatibility means exact equality with `CURRENT_SCHEMA_REVISION`. `BACKUP_READER_SCHEMA_REVISIONS` must never be accepted by API or Worker startup.
- There is no bypass flag, environment variable, fallback mode or read-only application mode for an incompatible real database.
- Offline OpenAPI generation, pure unit tests and application factories with explicitly injected test session factories must not connect to a database.
- A supported API wrapper must fail before Uvicorn is launched. Direct Uvicorn is additionally protected by lifespan and may never complete startup or return a successful business response on mismatch.
- Worker preflight must happen before ready text, storage construction, runner construction, heartbeat creation or any queue claim/write.
- Errors and logs may include expected revision, a closed failure code and `DatabaseSettings.safe_url`; they must never include passwords, raw SQL parameters, file names or business payloads.
- Existing untracked user content is preserved. Each implementation commit contains only files assigned to its task.
- Stage 1 cannot be called complete until the same candidate SHA passes both MySQL versions, canonical quality gates, OpenAPI no-drift, process/zero-side-effect tests and the documented rollback rehearsal.

## Approved Inputs and Current Facts

- Authoritative roadmap: `docs/superpowers/specs/2026-08-27-project-optimization-roadmap-design.md`, especially sections 4.2, 5.2, 6.2–6.6 and 7.1.
- Stage 0 entrance inventory contains nine identities: `dev-api`, `direct-api`, `container-api`, `demo-api`, `live-api`, `dev-worker`, `direct-worker`, `container-worker`, and `live-worker`.
- At the baseline, all nine have `schema_guard: missing`.
- `backend/app/maintenance/schema_revision.py` is the only runtime source of `CURRENT_SCHEMA_REVISION`; it currently declares `0022`.
- `backend/app/main.py` has no lifespan compatibility guard. Its readiness handler can create an engine and prove only `SELECT 1`.
- `backend/app/worker/cli.py` constructs storage and all four consumers without a schema preflight.
- `scripts/run-worker.ps1` prints `CLSEN worker ready.` before the Worker CLI can prove database compatibility.
- `ops/docker-compose.yml` makes backend and worker depend on successful `migrate`, so ordinary Compose startup can migrate implicitly.
- No schema change is needed for Stage 1. The expected head remains `0022` throughout this plan.

## Planned File Set

| Path | Action | Single responsibility |
| --- | --- | --- |
| `backend/app/maintenance/schema_compatibility.py` | Create | Read-only exact-revision guard, stable failure model and safe structured event payload |
| `backend/app/schema_preflight.py` | Create | Supported process-level preflight CLI used before Uvicorn/Worker launch |
| `backend/app/main.py` | Modify | Runtime lifespan guard, shared runtime engine/session lifecycle and truthful readiness |
| `backend/app/api/dependencies.py` | Modify | Reuse the lifespan-provisioned engine/factory without creating an unchecked server engine |
| `backend/app/worker/cli.py` | Modify | Guard before runner/storage construction and all queue claims |
| `backend/app/deployment/entrypoint.py` | Modify | Container API/Worker preflight before `exec`; explicit migrate remains a separate command |
| `scripts/dev-backend.ps1` | Modify | Load local environment and run preflight before launching reload Uvicorn |
| `scripts/run-worker.ps1` | Modify | Run preflight before ready text and Worker execution |
| `scripts/start-stage9-demo.ps1` | Modify | Preflight the isolated test database before demo Uvicorn |
| `scripts/run-product-catalog-live-e2e.ps1` | Modify | Preflight disposable live API/Worker phases before starting owned processes |
| `ops/docker-compose.yml` | Modify | Put migrate in `operations`; backend/worker depend directly on base services |
| `ops/verify-deployment.ps1` | Modify | Invoke explicit operations migration before each disposable deployment startup |
| `ops/DEPLOYMENT.md` | Modify | Document stop → backup → migrate → verify → start and mismatch recovery |
| `docs/operations/local-maintenance.md` | Modify | Document supported local preflight/start and refusal semantics |
| `docs/operations/schema-compatibility.md` | Create | Failure codes, entrance coverage, diagnostics and rollback runbook |
| `scripts/schema-compatibility-entrypoints.json` | Create | Versioned Stage 1 coverage matrix for all nine identities |
| `backend/tests/unit/maintenance/test_schema_compatibility.py` | Create | Pure failure matrix and read-only SQL assertions |
| `backend/tests/unit/test_schema_preflight.py` | Create | CLI exit, safe JSON logging and engine disposal tests |
| `backend/tests/unit/test_main_schema_compatibility.py` | Create | Lifespan/current-head/mismatch/offline-factory tests |
| `backend/tests/unit/worker/test_cli.py` | Modify | Prove preflight precedes storage/runner/claim and failure disposes engine |
| `backend/tests/unit/deployment/test_entrypoint.py` | Modify | Prove container preflight precedes API/Worker `exec` |
| `backend/tests/contracts/test_schema_compatibility_contract.py` | Create | Nine-entrance, Compose, scripts, docs and no-bypass traceability |
| `backend/tests/contracts/test_server_deployment.py` | Modify | Lock explicit migration profile and direct service dependencies |
| `backend/tests/contracts/test_maintenance_scripts.py` | Modify | Lock preflight-before-ready ordering in supported scripts |
| `backend/tests/integration/test_schema_compatibility.py` | Create | MySQL read-only current/missing/zero/multiple/old/new/unknown/error matrix |
| `backend/tests/integration/test_schema_startup_processes.py` | Create | Real preflight/Uvicorn/Worker process refusal and zero-side-effect proof |
| `scripts/ci-suite-manifest.json` | Modify | Register the Stage 1 MySQL suite and offline/Windows contract coverage |
| `scripts/test-mysql-matrix.ps1` | Modify | Execute the Stage 1 suite on disposable MySQL 8.0 and 8.4 |
| `backend/tests/contracts/test_ci_suite_manifest.py` | Modify | Lock exact Stage 1 suite membership and collection |
| `backend/tests/fixtures/ci/offline-backend-nodeids.txt` | Modify | Freeze new unit/contract nodes |
| `backend/tests/fixtures/ci/windows-smoke-nodeids.txt` | Modify | Freeze Windows-compatible guard/script contract nodes |
| `backend/tests/fixtures/ci/mysql-compatibility-nodeids.txt` | Modify | Freeze Stage 1 integration/process nodes collected on both MySQL versions |

## Fixed Public Interfaces

Implementations must use these names and meanings; do not create a second compatibility policy.

```python
# backend/app/maintenance/schema_compatibility.py
from dataclasses import dataclass
from enum import StrEnum
from sqlalchemy.engine import Engine

class SchemaCompatibilityCode(StrEnum):
    DATABASE_UNAVAILABLE = "schema_database_unavailable"
    VERSION_TABLE_MISSING = "schema_version_table_missing"
    VERSION_UNREADABLE = "schema_version_unreadable"
    VERSION_ROW_MISSING = "schema_version_row_missing"
    VERSION_ROWS_MULTIPLE = "schema_version_rows_multiple"
    REVISION_OLDER = "schema_revision_older"
    REVISION_NEWER = "schema_revision_newer"
    REVISION_UNKNOWN = "schema_revision_unknown"

@dataclass(frozen=True, slots=True)
class SchemaCompatibilityFailure(RuntimeError):
    code: SchemaCompatibilityCode
    expected_revision: str
    actual_revision: str | None
    database_identity: str

def classify_revision(actual_revision: str, *, expected_revision: str) -> SchemaCompatibilityCode: ...
def assert_schema_compatible(engine: Engine, *, database_identity: str) -> None: ...
def schema_event(error: SchemaCompatibilityFailure | None, *, component: str) -> dict[str, str | None]: ...
```

`classify_revision` follows the repository's explicit four-digit revision contract: equality passes; a different four-digit numeric revision is classified by parsed integer value, not lexical string ordering; any other value is `REVISION_UNKNOWN`. This classifier does not claim to detect manual structural drift.

`assert_schema_compatible` issues exactly one read-only `SELECT version_num FROM alembic_version` observation. It reads all rows and requires exactly one. It must not use `LIMIT 1`, because that would hide multiple heads/rows. MySQL error codes are mapped to closed failure codes without returning the original exception text. The engine is created by the caller and always disposed by the caller that owns it.

```python
# backend/app/schema_preflight.py
def run_preflight(
    *,
    database_environment: str = "APP_DATABASE_URL",
    environment_file: Path | None = None,
    component: str,
) -> None: ...

def main(arguments: Sequence[str] | None = None) -> int: ...
```

The CLI accepts only `--database-environment`, optional `--environment-file`, and `--component api|worker`. It emits one JSON success or failure event to stderr/stdout as documented and returns `0` or `2`. It never prints the database URL supplied by the environment; only `DatabaseSettings.safe_url` may appear.

```python
# backend/app/main.py
def create_app(
    settings: Settings | None = None,
    *,
    session_factory: SessionFactory | None = None,
) -> FastAPI: ...

def create_runtime_app(settings: Settings | None = None) -> FastAPI: ...

app = create_runtime_app()
```

`create_app` remains the offline/injected test factory and never discovers a database by itself. `create_runtime_app` installs the mandatory lifespan: create engine → assert exact schema → create session factory → set application state → serve → dispose at shutdown. There is no runtime bypass parameter. Direct Uvicorn continues to target `app.main:app`, which is always guarded.

## Task 1: Shared Read-Only Compatibility Guard

**Files:**

- Create `backend/app/maintenance/schema_compatibility.py`.
- Create `backend/tests/unit/maintenance/test_schema_compatibility.py`.
- Update `backend/tests/contracts/test_schema_revision_contract.py` only if needed to lock the single-head/revision relationship.

**Steps:**

1. Write failing unit tests for one current row, missing table, zero rows, multiple rows, old numeric revision, new numeric revision, unknown revision, permission/unreadable failure and connection failure.
2. Assert the fake connection receives only `SELECT version_num FROM alembic_version`, with no `LIMIT`, DDL or DML.
3. Implement the fixed failure types and exact-equality guard.
4. Map SQLAlchemy/MySQL failures to closed codes. Preserve exception chaining for controlled server logs, but never include the raw exception in `str(error)` or `schema_event`.
5. Prove `BACKUP_READER_SCHEMA_REVISIONS` is not consulted.
6. Run:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest backend/tests/unit/maintenance/test_schema_compatibility.py backend/tests/contracts/test_schema_revision_contract.py -q
   .\.venv\Scripts\python.exe -m ruff check backend/app/maintenance/schema_compatibility.py backend/tests/unit/maintenance/test_schema_compatibility.py
   .\.venv\Scripts\python.exe -m mypy backend/app/maintenance/schema_compatibility.py
   ```

**Checkpoint:** Commit `feat(stage1): add read-only schema compatibility guard`.

## Task 2: Preflight CLI and FastAPI Lifespan Defense

**Files:**

- Create `backend/app/schema_preflight.py`.
- Modify `backend/app/main.py`.
- Modify `backend/app/api/dependencies.py`.
- Create `backend/tests/unit/test_schema_preflight.py`.
- Create `backend/tests/unit/test_main_schema_compatibility.py`.
- Modify `backend/tests/unit/test_health.py` where readiness expectations change.

**Steps:**

1. Write failing CLI tests for current/mismatch/configuration/connection cases, safe URL redaction, one event, exit `0/2`, and engine disposal.
2. Write lifespan tests proving a current head exposes the shared engine/session factory and disposes it at shutdown.
3. Write mismatch tests proving TestClient cannot complete startup and no route returns success.
4. Keep `create_app(..., session_factory=...)` offline for existing unit/OpenAPI tests. Add `create_runtime_app()` as the only runtime factory; do not add `skip_schema_check` or a similar argument.
5. Remove readiness's lazy creation of an unchecked engine. In a runtime app, readiness uses only the engine established by the successful lifespan. In an injected test app, existing explicit fake state remains supported.
6. Ensure OpenAPI module import/build does not enter lifespan or touch the database.
7. Run the new tests plus all existing health and OpenAPI unit tests.

**Checkpoint:** Commit `feat(stage1): guard FastAPI runtime startup`.

## Task 3: Guard Every Worker and Supported Local/Live Launcher

**Files:**

- Modify `backend/app/worker/cli.py`.
- Modify `scripts/dev-backend.ps1`.
- Modify `scripts/run-worker.ps1`.
- Modify `scripts/start-stage9-demo.ps1`.
- Modify `scripts/run-product-catalog-live-e2e.ps1`.
- Modify `backend/tests/unit/worker/test_cli.py`.
- Modify `backend/tests/contracts/test_maintenance_scripts.py`.

**Steps:**

1. Add Worker CLI characterization tests around its current argument parsing and drain loop.
2. Insert `assert_schema_compatible` immediately after engine creation and before `StorageSettings`, `LocalContentStore`, any repository/worker/runner construction or `run_once` call.
3. On guard failure, emit the safe structured event, dispose the engine and exit `2`. No consumer call or business write is allowed.
4. In `scripts/run-worker.ps1`, run `app.schema_preflight` first and print `CLSEN worker ready.` only after exit `0`; keep the Worker CLI's internal second defense.
5. In `scripts/dev-backend.ps1`, pass the same optional `.env` to preflight before invoking Uvicorn. A failure must leave port 8000 unbound.
6. In the Stage 9 demo and both live-E2E process-launch sections, preflight the exact database environment used by the following process. Test databases remain disposable/isolated.
7. Add source-order contracts so future edits cannot move ready/Start-Process/uvicorn before preflight.
8. Run Worker unit and script contract suites.

**Checkpoint:** Commit `feat(stage1): guard worker and local launchers`.

## Task 4: Guard Container Roles and Make Migration Explicit

**Files:**

- Modify `backend/app/deployment/entrypoint.py`.
- Modify `backend/tests/unit/deployment/test_entrypoint.py`.
- Modify `ops/docker-compose.yml`.
- Modify `ops/verify-deployment.ps1`.
- Modify `backend/tests/contracts/test_server_deployment.py`.

**Steps:**

1. After container secrets are loaded into process environment, preflight API and Worker roles before `_exec`. Unit tests must prove `_exec` is never reached after failure.
2. Preserve the API lifespan and Worker CLI checks as defense in depth; container preflight does not replace them.
3. Add `profiles: ["operations"]` to `migrate`.
4. Remove backend/worker `depends_on: migrate`. Both depend directly on `mysql: service_healthy` and `storage-init: service_completed_successfully`.
5. Ensure ordinary `docker compose up` effective config cannot create a migrate container. A fresh or old schema causes API/Worker refusal, not automatic upgrade.
6. Update the disposable deployment verifier to call `docker compose --profile operations run --rm migrate` as an explicit recorded step before starting matching API/Worker containers.
7. Keep reset-test-database, grant sync, verification and maintenance profiles explicit and functioning.
8. Run entrypoint and deployment contract tests plus `docker compose config` with required non-secret selector variables.

**Checkpoint:** Commit `feat(stage1): require explicit deployment migration`.

## Task 5: MySQL Matrix and Real Process Zero-Side-Effect Proof

**Files:**

- Create `backend/tests/integration/test_schema_compatibility.py`.
- Create `backend/tests/integration/test_schema_startup_processes.py`.
- Add only test helpers local to those files unless a shared fixture has at least two callers.

**Steps:**

1. Use only the matrix runner's disposable database. Record the original `alembic_version` state and restore it in `finally` even when assertions fail.
2. Test current, missing table, zero rows, multiple rows, old (`0021`), new (`0023`), unknown and insufficient-read-permission states against a real MySQL connection.
3. Before each mismatch process case, record counts/checksums for the four queue source tables and other designated sentinel tables. After refusal, prove all values and the revision state are unchanged by the application/Worker process.
4. For supported API preflight wrappers, prove nonzero exit occurs before port binding. For direct Uvicorn, prove lifespan fails, readiness never becomes successful and the process exits.
5. For Worker CLI/container role, patch or instrument claim boundaries so the four claim counts are all zero; no ready event is emitted.
6. Run matching-head controls to prove API readiness and Worker `--drain` startup succeed on MySQL 8.0 and 8.4.
7. Never run these destructive schema-shape fixtures against `APP_DATABASE_URL`; require matrix-owned scope/environment markers and refuse otherwise.

**Checkpoint:** Commit `test(stage1): prove schema mismatch startup refusal`.

## Task 6: Entrance Manifest, CI Collection and OpenAPI No-Drift

**Files:**

- Create `scripts/schema-compatibility-entrypoints.json`.
- Create `backend/tests/contracts/test_schema_compatibility_contract.py`.
- Modify `scripts/ci-suite-manifest.json`.
- Modify `scripts/test-mysql-matrix.ps1`.
- Modify `backend/tests/contracts/test_ci_suite_manifest.py`.
- Modify the three node-ID fixtures listed in Planned File Set.

**Steps:**

1. Create a strict versioned manifest with the nine Stage 0 identities, exact source path, pre-process guard, in-process defense and expected failure boundary.
2. Add repository contracts that resolve every path/token and reject missing identities, duplicate IDs, bypass strings, automatic migration calls and unsafe logging.
3. Add `mysql-schema-startup` to both MySQL versions' canonical suite list with exactly the two Stage 1 integration files.
4. Update matrix ValidateSets/dispatch and frozen node-ID fixtures from actual `pytest --collect-only` output; do not hand-invent node IDs.
5. Keep the pre-existing 14 Stage 0 MySQL exclusions unchanged except for any test file explicitly moved into the new canonical suite with documented ownership.
6. Run offline, Windows-smoke collection contracts and both generated OpenAPI checks. No API schema change is expected; generated TypeScript must remain byte-identical.

**Checkpoint:** Commit `test(stage1): register schema startup gates`.

## Task 7: Operations and Rollback Documentation

**Files:**

- Create `docs/operations/schema-compatibility.md`.
- Modify `ops/DEPLOYMENT.md`.
- Modify `docs/operations/local-maintenance.md`.

**Required runbook sequence:**

1. Stop all old API and Worker processes that can access the target database.
2. Create and verify a backup under the existing maintenance write-barrier procedure.
3. Run `docker compose --profile operations run --rm migrate` or the approved local migration command as a separately authorized action.
4. Query and verify exactly one head equal to the candidate code's `CURRENT_SCHEMA_REVISION`.
5. Start matching API and Worker artifacts.
6. Verify schema startup events, readiness, authentication canary and Worker drain/idle canary.

Document every failure code, what can be safely inspected, and what must never be done. Rollback always means restoring a code/schema pair proven compatible. It never means bypassing the guard, editing `alembic_version`, auto-downgrading or starting an older process against a newer schema. If the database has already advanced beyond the old artifact, prefer forward repair; data restoration requires the existing isolated restore-verification runbook.

**Checkpoint:** Commit `docs(stage1): document explicit schema operations`.

## Task 8: Same-SHA Verification, Review and Completion Evidence

**Preconditions:**

- Worktree contains no unrelated or untracked files.
- Candidate SHA is recorded and remains unchanged for all evidence.
- Test evidence root is new, external to the repository and contains only synthetic/disposable results.

**Verification commands:**

```powershell
.\.venv\Scripts\python.exe -m ruff check backend/app backend/tests
.\.venv\Scripts\python.exe -m ruff format --check backend/app backend/tests
.\.venv\Scripts\python.exe -m mypy backend/app
.\.venv\Scripts\python.exe -m pytest backend/tests -m "not mysql" --ignore=backend/tests/performance/test_project_optimization_baseline.py
pwsh -File scripts\run-ci-profile.ps1 -Profile windows-smoke
pwsh -File scripts\test-mysql-matrix.ps1 -Suite mysql-schema-startup -MySqlVersion 8.0
pwsh -File scripts\test-mysql-matrix.ps1 -Suite mysql-schema-startup -MySqlVersion 8.4
pwsh -File scripts\generate-api-client.ps1 -Check
pwsh -File scripts\run-ci-profile.ps1 -Profile frontend-full
git diff --check
git status --short
```

Also run the disposable deployment rehearsal twice: matching head succeeds; deliberately old schema remains unchanged while API/Worker refuse. Then run the explicit operations migration and prove the matching artifacts start. Capture command, start/end time, exit code, pass/fail/skip count, OS/Python/Node/MySQL versions and candidate SHA.

**Required completion evidence:**

- Nine-entry coverage matrix is 100% enforced.
- Missing/zero/multiple/old/new/unknown/unreadable/unavailable cases refuse.
- Supported API wrappers fail before Uvicorn/port binding; direct Uvicorn never becomes ready.
- Worker emits no ready event and performs zero claims/writes on mismatch.
- Runtime guard executes only read SQL and never changes `alembic_version`.
- Ordinary Compose startup cannot run migrate; explicit operations migration is separately visible.
- Current head succeeds on MySQL 8.0 and 8.4.
- Logs contain no credentials or business data.
- Offline OpenAPI generation remains database-free and no generated client drift exists.
- Canonical gates have zero unexplained skips, xfails or retry-only successes.
- Runbooks and rollback rehearsal are attached to the candidate SHA.

After evidence collection, use `finishing-a-development-branch` and present merge/review options. Do not merge to `master`, migrate any real database or start Stage 2 without a new explicit user decision.

## Risk and Rollback Boundaries

- **Expected fail-closed outage:** A mismatched deployment will not start. This is success of the safety control, not a reason to weaken it.
- **False mismatch on a valid database:** Stop the candidate artifact, retain the database unchanged, inspect closed code and exact revision with the migration account, then revert only the candidate code to the last artifact whose declared head matches. Never add a bypass.
- **Compose sequencing regression:** Revert the Compose/entrypoint commit as a unit only in a disposable environment. Do not restore the implicit migrate dependency in production; use the documented explicit migration sequence.
- **Direct Uvicorn lifecycle regression:** Revert the FastAPI runtime-app commit while retaining the process preflight wrappers only if the reverted artifact still matches the database. This is a temporary code rollback, not Stage 1 completion.
- **Worker startup regression:** Stop the candidate Worker before rollback, prove it holds no active claim, then deploy the matching prior artifact. Queue states are never mass-edited by rollback.
- **Test mutation leakage:** Abort the matrix, destroy only its verified disposable Compose project/volume, and recreate it. Never attempt cleanup against a non-disposable database.

## Plan Self-Review Record

- **Stage ordering:** Implements only schema fail-fast. Stage 2 heartbeats/monitoring remain blocked until this plan is complete and approved.
- **Entrance coverage:** Every one of the nine Stage 0 identities is assigned both a pre-process guard or explicit reason and an in-process defense.
- **No auto-migration:** Runtime code cannot run Alembic; ordinary Compose no longer depends on migrate; migration exists only as an explicit operations command.
- **Offline boundary:** `create_app` remains injectable/offline; only `create_runtime_app` owns the mandatory real-engine lifespan.
- **Failure matrix:** Includes missing, zero, multiple, old, new, unknown, unreadable, unavailable and matching cases with process and zero-side-effect evidence.
- **Security:** Safe URL only, closed codes, no raw exception payload, no bypass and no business data in logs.
- **Verification:** MySQL 8.0/8.4, canonical offline/frontend gates, OpenAPI no-drift, deployment rehearsal, diff/status and rollback are all required on one candidate SHA.
- **Unresolved values:** None. Stage 1 adds no H/S/O/R or Stage 2 schema values.
