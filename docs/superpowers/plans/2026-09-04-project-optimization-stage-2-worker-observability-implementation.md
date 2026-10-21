# Project Optimization Stage 2 Worker Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build database-authoritative Worker heartbeats, four-queue operational metrics, safe structured Worker logs, and an administrator runtime-status view without changing any queue state machine.

**Architecture:** Add an explicit additive `0023` migration containing Worker instance and per-consumer state, then make a dedicated heartbeat controller use its own short-lived database connection and monotonic local freshness gate. Keep queue aggregation read-only and isolated per queue, append the result to the existing maintenance API, and render it through a focused React component. The migration-only commit is the Stage 2 application rollback anchor because Stage 1 code at schema `0022` cannot run against schema `0023`.

**Tech Stack:** Python 3, FastAPI, Pydantic, SQLAlchemy Core, Alembic, MySQL 8.0/8.4, pytest, React, TypeScript, Vitest, Testing Library, Playwright, PowerShell CI runners.

## Global Constraints

- The approved baseline is commit `f07646d797e30e04494add4d0a669df938bd9824`, run `stage0-fb3871dc26cd`, approved by `项目负责人管理员` under `项目审批单 PROJ-2026-0903-01`.
- Effective values are fixed at heartbeat `H=10s`, stale `S=30s`, offline `O=60s`, refresh `R=15s`, and retention `30 days`; require `S >= 3H`, `O > S`, and crash visibility within `O+R=75s`.
- Never read, enumerate, modify, stage, or commit anything under `data/`.
- Never migrate a real or user-owned database. All migration and integration checks use disposable MySQL 8.0/8.4 databases.
- Do not push or merge unless the user separately requests it.
- Do not introduce Redis, RabbitMQ, Prometheus, Grafana, an external alerting service, or a new message broker.
- Do not move browser batch-review work to Worker and do not add cancel, force-retry, or failed-record deletion controls.
- Do not change the native state machine, lease, fencing, retry, or recovery behavior of `return_dedup`, `publication_outbox`, `catalog_export`, or `catalog_import`.
- Do not persist or log payloads, raw filenames, order numbers, customer data, credentials, database URLs, usernames, or exception input.
- `online` means only that the process recently wrote a database heartbeat; it never asserts that all consumers are progressing.
- Heartbeat health and `maintenance_active` stay orthogonal. Maintenance never upgrades a stale/offline process to healthy, and recovery requires a real new heartbeat.
- Database timestamps and `observed_at` come from `UTC_TIMESTAMP(6)`; browser and Worker wall clocks do not decide health.
- Existing `GET /api/admin/maintenance` fields remain present and compatible, the route stays admin-only, and the response remains `Cache-Control: private, no-store`.
- Development validation is risk-based: each task runs only focused lint/type/unit tests plus at most one disposable MySQL version when its database behavior changes. MySQL 8.0/8.4, full profiles, deployment rehearsal, and three-round performance evidence run only in Task 8.
- Work inline in this task by default. Do not delegate to subagents unless the user explicitly changes that instruction.

---

## Planned File Set

### Create

- `backend/alembic/versions/0023_worker_observability.py` — additive Worker observability tables, constraints, indexes, upgrade, and downgrade.
- `backend/app/logging.py` — shared JSON formatter and logger configuration used by API and Worker.
- `backend/app/worker/observability.py` — frozen constants, queue identifiers, safe result/failure codes, protocols, and event helpers.
- `backend/app/worker/heartbeat.py` — MySQL repository, heartbeat thread, monotonic claim gate, lifecycle writes, and bounded pruning.
- `backend/app/maintenance/worker_status.py` — database-time Worker and four-queue read models and partial-failure aggregation.
- `backend/tests/unit/test_logging.py` — API logging compatibility and field allowlist tests.
- `backend/tests/unit/worker/test_observability.py` — enum, safe-code, and structured-event tests.
- `backend/tests/unit/worker/test_heartbeat.py` — scheduler, claim-gate, long-task, failure, stop, and pruning tests.
- `backend/tests/unit/maintenance/test_worker_status.py` — health thresholds, capabilities, mapping, and failure isolation tests.
- `backend/tests/integration/test_worker_observability.py` — MySQL persistence, database-time, lifecycle, privileges, retention, and Runner integration.
- `backend/tests/integration/test_worker_observability_api.py` — admin API, status mapping, cache, authorization, and partial query failure tests.
- `frontend/src/features/admin/WorkerObservabilityPanel.tsx` — Worker fleet and four queue cards with accessible status semantics.
- `frontend/src/features/admin/WorkerObservabilityPanel.test.tsx` — component state, null-capability, maintenance, and refresh tests.
- `frontend/tests/e2e/admin-worker-observability.spec.ts` — one focused administrator browser flow.
- `scripts/project-optimization-stage2-manifest.json` — same-SHA Stage 2 gate and evidence contract.
- `scripts/run-project-optimization-stage2.ps1` — collect/validate Stage 2 evidence without reading `data/`.
- `backend/tests/contracts/test_project_optimization_stage2_contract.py` — Stage 2 runner, evidence, ceilings, and redaction contract.
- `docs/operations/worker-observability.md` — operations, diagnosis, retention, and rollback runbook.

### Modify

- `backend/app/maintenance/schema_revision.py` — advance runtime head and backup-reader set to `0023`.
- `backend/tests/contracts/test_migration_contract.py` — register `0023` and assert its exact schema contract.
- `backend/tests/contracts/test_schema_revision_contract.py` — assert the new head and backup-reader compatibility.
- `backend/tests/integration/test_migrations.py` — exercise `0022 -> 0023 -> 0022 -> 0023` on disposable MySQL.
- `backend/tests/integration/historical_schema_support.py` — include `0023` in disposable backup/restore schema fixtures.
- `backend/tests/integration/test_product_catalog_backup_restore.py` — prove backup/restore carries both observability tables.
- `scripts/database-privileges.json` — grant runtime `SELECT/INSERT/UPDATE/DELETE` only where required by the new repositories.
- `backend/app/main.py` — import shared logging while preserving current API output.
- `backend/app/worker/runner.py` — apply the heartbeat claim gate and record per-consumer poll state while retaining exception isolation.
- `backend/app/worker/cli.py` — generate one instance UUID, configure JSON logging, register before claim, run the independent heartbeat, stop cleanly, and dispose after shutdown.
- `backend/app/api/maintenance.py` — append Worker and queue fields using the read-only aggregator.
- `backend/tests/unit/worker/test_runner.py` — lock ordering, skip-on-telemetry-failure, isolation, and result semantics.
- `backend/tests/unit/worker/test_cli.py` — registration-before-ready/claim, drain, failure, interrupt, and cleanup ordering.
- `backend/tests/unit/test_openapi_contract.py` — assert the appended schema remains generated and stable.
- `frontend/src/api/generated.ts` — regenerate from OpenAPI; never hand-edit.
- `frontend/src/features/admin/AdminConsole.tsx` — render the extracted panel and own the 15-second refresh lifecycle.
- `frontend/src/features/admin/AdminConsole.css` — Stage 2 blue/white status layout, non-color indicators, and narrow-screen behavior.
- `frontend/src/features/admin/AdminConsole.test.tsx` — update the maintenance fixture and integration assertions.
- `frontend/tests/e2e/project-optimization-baseline.spec.ts` — keep the frozen maintenance scenario compatible with appended fields without changing its Stage 0 baseline meaning.
- `backend/tests/performance/test_project_optimization_baseline.py` — measure the real heartbeat repository and final queue/API queries against frozen ceilings.
- `scripts/ci-suite-manifest.json` — add the canonical MySQL Stage 2 suite and release evidence suite.
- `backend/tests/fixtures/ci/mysql-compatibility-nodeids.txt` — regenerate only after collection is reviewed.
- `backend/tests/fixtures/ci/offline-backend-nodeids.txt` — add new non-MySQL unit/contract nodes after review.
- `backend/tests/fixtures/ci/windows-smoke-nodeids.txt` — add only deterministic cross-platform Stage 2 nodes.
- `docs/operations/local-maintenance.md` — link the Worker status and deployment/rollback sequence.

## Fixed Contracts

### Database contract

`worker_instances` has no business payload and stores one non-reusable process identity:

```text
instance_id            BINARY(16) primary key
role                   VARCHAR(32) ASCII, fixed value "local_worker"
build_id               VARCHAR(64) ASCII
supported_queues       JSON array of exactly the four fixed queue names
lifecycle_status       VARCHAR(16) ASCII: running | stopped
heartbeat_sequence     BIGINT UNSIGNED, starts at 0 and only increases
started_at             DATETIME(6), database generated
last_heartbeat_at      DATETIME(6), database generated
stopped_at             DATETIME(6), nullable
last_result_code       VARCHAR(64) ASCII, nullable and allowlisted
```

Indexes are `ix_worker_instances_lifecycle_heartbeat(lifecycle_status, last_heartbeat_at, instance_id)` and `ix_worker_instances_retention(stopped_at, last_heartbeat_at, instance_id)`. Health is derived at query time; `online`, `stale`, and `offline` are never persisted lifecycle values.

`worker_consumer_states` stores one row per instance and supported queue:

```text
worker_instance_id          BINARY(16), foreign key worker_instances(instance_id) ON DELETE CASCADE
queue_name                  VARCHAR(32) ASCII
last_poll_started_at        DATETIME(6), nullable
last_poll_completed_at      DATETIME(6), nullable
last_poll_succeeded_at      DATETIME(6), nullable
last_poll_failed_at         DATETIME(6), nullable
consecutive_failures        BIGINT UNSIGNED, default 0
last_result_code            VARCHAR(64) ASCII, nullable and allowlisted
last_failure_code           VARCHAR(64) ASCII, nullable and allowlisted
PRIMARY KEY (worker_instance_id, queue_name)
```

The queue-name check constraint permits exactly `return_dedup`, `publication_outbox`, `catalog_export`, and `catalog_import`. The migration is additive, seeds no rows, creates `worker_instances` before its child, drops the child first on downgrade, and performs no application-data scan.

### Python interface contract

Define these public names once in `backend/app/worker/observability.py` and use them verbatim in later tasks:

```python
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

QueueName = Literal[
    "return_dedup",
    "publication_outbox",
    "catalog_export",
    "catalog_import",
]
QUEUE_NAMES: tuple[QueueName, ...] = (
    "return_dedup",
    "publication_outbox",
    "catalog_export",
    "catalog_import",
)
HEARTBEAT_SECONDS = 10
STALE_SECONDS = 30
OFFLINE_SECONDS = 60
REFRESH_SECONDS = 15
RETENTION_DAYS = 30
RETENTION_DELETE_LIMIT = 500

@dataclass(frozen=True, slots=True)
class PollOutcome:
    result_code: str
    did_work: bool

class WorkerTelemetry(Protocol):
    def can_claim(self) -> bool: ...
    def poll_started(self, queue_name: QueueName) -> None: ...
    def poll_succeeded(self, queue_name: QueueName, outcome: PollOutcome) -> None: ...
    def poll_failed(self, queue_name: QueueName, failure_code: str) -> None: ...
```

`safe_failure_code(error, queue_name)` maps exception classes to closed values such as `consumer_unexpected_error`, `heartbeat_write_failed`, `consumer_state_write_failed`, and known domain codes. It never returns `str(error)`.

Define the repository and controller in `backend/app/worker/heartbeat.py`:

```python
class WorkerHeartbeatRepository:
    def register(self, *, instance_id: UUID, role: str, build_id: str,
                 supported_queues: tuple[QueueName, ...]) -> datetime: ...
    def heartbeat(self, *, instance_id: UUID, sequence: int,
                  result_code: str) -> datetime: ...
    def poll_started(self, *, instance_id: UUID, queue_name: QueueName) -> datetime: ...
    def poll_succeeded(self, *, instance_id: UUID, queue_name: QueueName,
                       result_code: str) -> datetime: ...
    def poll_failed(self, *, instance_id: UUID, queue_name: QueueName,
                    failure_code: str) -> datetime: ...
    def stop(self, *, instance_id: UUID, result_code: str) -> datetime: ...
    def prune(self, *, retention_days: int = RETENTION_DAYS,
              limit: int = RETENTION_DELETE_LIMIT) -> int: ...

class WorkerHeartbeatController(WorkerTelemetry):
    def __init__(self, repository: WorkerHeartbeatRepository, *, instance_id: UUID,
                 build_id: str, monotonic: Callable[[], float],
                 wait: Callable[[float], bool]) -> None: ...
    def start(self) -> None: ...
    def can_claim(self) -> bool: ...
    def stop(self, *, result_code: str = "worker_stopped") -> None: ...
```

Registration must succeed before `start()` returns. `can_claim()` is true only after the most recent successful heartbeat and while its monotonic age is at most `HEARTBEAT_SECONDS`. A write failure sets it false immediately. The daemon heartbeat thread performs only heartbeat writes and wait operations; it never runs queue work. `stop()` joins the thread with a bounded timeout and attempts a final database `stopped` write.

`WorkerRunner` accepts `telemetry: WorkerTelemetry` and, before each consumer call, executes `can_claim()` then `poll_started()`. If either denies/fails, that consumer is not invoked. Business exceptions call `poll_failed()` with a safe code and do not stop the remaining queues. Successful calls, including a `None` no-work result, call `poll_succeeded()` with `queue_idle` or `queue_work_completed`.

### Administrator API contract

Keep `backups`, `restores`, `outbox`, and `write_lock` unchanged. Append exactly these top-level fields:

```python
class HeartbeatThresholdsResponse(BaseModel):
    heartbeat_seconds: Literal[10]
    stale_seconds: Literal[30]
    offline_seconds: Literal[60]
    refresh_seconds: Literal[15]

class WorkerConsumerStatusResponse(BaseModel):
    queue_name: QueueName
    consumer_health: Literal["healthy", "failing", "unknown", "not_observed"]
    last_poll_started_at: datetime | None
    last_poll_completed_at: datetime | None
    last_poll_succeeded_at: datetime | None
    last_poll_failed_at: datetime | None
    consecutive_failures: int
    failure_code: str | None

class WorkerInstanceStatusResponse(BaseModel):
    instance_id: str
    role: str
    build_id: str
    supported_queues: list[QueueName]
    lifecycle_status: Literal["running", "stopped"]
    heartbeat_status: Literal["online", "stale", "offline", "stopped", "unknown"]
    heartbeat_sequence: int
    last_heartbeat_at: datetime | None
    heartbeat_age_seconds: float | None
    last_result_code: str | None
    consumers: list[WorkerConsumerStatusResponse]

class WorkerFleetStatusResponse(BaseModel):
    query_health: Literal["healthy", "unknown"]
    failure_code: str | None
    thresholds: HeartbeatThresholdsResponse
    instances: list[WorkerInstanceStatusResponse]

class QueueCapabilitiesResponse(BaseModel):
    actionable: bool
    in_flight: bool
    retry_wait: bool
    stale: bool
    stuck: bool

class QueueStatusResponse(BaseModel):
    queue_name: QueueName
    query_health: Literal["healthy", "unknown"]
    consumer_health: Literal["healthy", "failing", "unknown", "not_observed"]
    failure_code: str | None
    native_status_counts: dict[str, int] | None
    actionable: int | None
    in_flight: int | None
    retry_wait: int | None
    stale: int | None
    stuck: int | None
    failed: int | None
    unresolved_building: int | None
    oldest_work_at: datetime | None
    next_retry_at: datetime | None
    last_succeeded_at: datetime | None
    last_failed_at: datetime | None
    consecutive_failures: int | None
    capabilities: QueueCapabilitiesResponse

class MaintenanceStatusResponse(BaseModel):
    backups: list[BackupSnapshotStatus]
    restores: list[RestoreVerificationStatus]
    outbox: OutboxStatus
    write_lock: MaintenanceWriteLockStatus
    observed_at: datetime
    maintenance_active: bool
    worker: WorkerFleetStatusResponse
    queues: list[QueueStatusResponse]
```

`read_worker_observability(engine, *, maintenance_active: bool) -> tuple[datetime, WorkerFleetStatusResponse, list[QueueStatusResponse]]` obtains `observed_at` once with `SELECT UTC_TIMESTAMP(6)`, passes it as a bound parameter to all status queries, and opens an independent connection/transaction for the Worker fleet and each queue. A failed queue query returns a fully null metric row with `query_health="unknown"` and a closed `failure_code`; other rows remain intact.

Queue mapping is fixed:

| Queue | Actionable | In flight | Retry/stale/stuck | Unavailable capabilities |
| --- | --- | --- | --- | --- |
| `publication_outbox` | `pending AND available_at <= observed_at` | `processing` with non-expired lock under the existing stale threshold | future `pending` is retry wait; expired `processing` is stale | none |
| `return_dedup` | `building` with no lease or expired lease | `building` with valid lease | expired lease is also stale | retry wait and stuck |
| `catalog_import` | `uploaded` | `parsing` with latest running parse-attempt lease valid | expired `parsing` is stuck and is never actionable | retry wait and stale |
| `catalog_export` | no proven claimable count; expose `building` as `unresolved_building` | null | null | actionable, in-flight, retry wait, stale, and stuck |

Every native status has an explicit count. `failed` means `failed` for outbox/return/export and `parse_failed` for import. `ready`, `superseded`, and other terminal states stay only in `native_status_counts`. A capability that is false always yields null, never zero.

### Structured logging contract

Each Worker line is JSON and includes these keys, using null where a key is inapplicable:

```json
{"timestamp":"2026-09-04T00:00:00.000000+00:00","level":"INFO","event":"worker_heartbeat_succeeded","worker_instance_id":"32-lowercase-hex","queue_name":null,"outcome":"succeeded","duration_ms":4.2,"attempt":7,"failure_code":null}
```

The formatter accepts only the current API request fields plus `event`, `worker_instance_id`, `queue_name`, `outcome`, `duration_ms`, `attempt`, `failure_code`, and an internal numeric `item_id`. It does not serialize arbitrary `LogRecord` attributes. Tracebacks remain server-side JSON `exception` text and are never placed in the API response.

---

### Task 1: Add the `0023` schema and establish the rollback anchor

**Files:**
- Create: `backend/alembic/versions/0023_worker_observability.py`
- Modify: `backend/app/maintenance/schema_revision.py`
- Modify: `backend/tests/contracts/test_migration_contract.py`
- Modify: `backend/tests/contracts/test_schema_revision_contract.py`
- Modify: `backend/tests/integration/test_migrations.py`
- Modify: `backend/tests/integration/historical_schema_support.py`
- Modify: `backend/tests/integration/test_product_catalog_backup_restore.py`
- Modify: `scripts/database-privileges.json`

**Interfaces:**
- Consumes: Stage 1 exact-schema guard and `CURRENT_SCHEMA_REVISION`.
- Produces: revision `0023`, the two tables in the fixed database contract, runtime grants, and a migration-only application rollback anchor.

- [x] **Step 1: Add failing migration contract assertions.**

```python
EXPECTED_MIGRATIONS = (*EXPECTED_MIGRATIONS, ("0023", "0022", "0023_worker_observability.py"))

def test_worker_observability_migration_is_additive_and_bounded() -> None:
    source = (VERSIONS_DIRECTORY / "0023_worker_observability.py").read_text(encoding="utf-8")
    assert _create_table_position(source, "worker_instances") < _create_table_position(source, "worker_consumer_states")
    assert 'ondelete="CASCADE"' in source
    assert "RETENTION" not in source.upper()
```

- [x] **Step 2: Run only the migration and revision contracts and confirm they fail because `0023` is absent.**

```powershell
python -m pytest backend/tests/contracts/test_migration_contract.py backend/tests/contracts/test_schema_revision_contract.py -q
```

- [x] **Step 3: Implement `0023` exactly as the database contract specifies.** Use MySQL `BINARY(16)`, `DATETIME(fsp=6)`, ASCII binary-collated code fields, named checks, and deterministic index names. `upgrade()` creates no rows and `downgrade()` drops only `worker_consumer_states` then `worker_instances`.

```python
revision = "0023"
down_revision = "0022"

def upgrade() -> None:
    op.create_table("worker_instances", ...)
    op.create_table("worker_consumer_states", ...)

def downgrade() -> None:
    op.drop_table("worker_consumer_states")
    op.drop_table("worker_instances")
```

- [x] **Step 4: Advance the exact runtime head and backup-reader support.**

```python
CURRENT_SCHEMA_REVISION = "0023"
BACKUP_READER_SCHEMA_REVISIONS = ("0020", "0021", "0022", "0023")
```

- [x] **Step 5: Update the privilege manifest and tests.** Runtime requires `SELECT`, `INSERT`, `UPDATE`, and bounded `DELETE` on `worker_instances`; it requires `SELECT`, `INSERT`, and `UPDATE` on `worker_consumer_states`. Backup schema access already covers all tables and must be asserted rather than widened with global DML.

```json
"mutable_insert": ["worker_instances", "worker_consumer_states"],
"update": ["worker_instances", "worker_consumer_states"],
"delete": ["worker_instances"]
```

- [x] **Step 6: Add disposable migration and backup/restore checks.** Prove `0022 -> 0023 -> 0022 -> 0023`, exact columns/checks/indexes/FK, empty-table creation, restored rows, and no changes to existing business rows.

```powershell
python -m pytest backend/tests/contracts/test_migration_contract.py backend/tests/contracts/test_schema_revision_contract.py -q
```

- [x] **Step 7: Run the one-version database checkpoint only if the disposable MySQL 8.0 test service is already available.** Do not start the 8.4 matrix here. No disposable service or test environment was already active, so this conditional checkpoint is deferred to Task 8's canonical matrix.

```powershell
python -m pytest backend/tests/integration/test_migrations.py backend/tests/integration/test_product_catalog_backup_restore.py -q --require-mysql
```

- [x] **Step 8: Commit the rollback anchor without any Worker/API/UI behavior.**

```powershell
git add backend/alembic/versions/0023_worker_observability.py backend/app/maintenance/schema_revision.py backend/tests/contracts/test_migration_contract.py backend/tests/contracts/test_schema_revision_contract.py backend/tests/integration/test_migrations.py backend/tests/integration/historical_schema_support.py backend/tests/integration/test_product_catalog_backup_restore.py scripts/database-privileges.json
git commit -m "feat: add worker observability schema"
```

Record this commit SHA as `STAGE2_SCHEMA_ANCHOR`. Emergency application rollback after the database reaches `0023` targets this commit, not Stage 1 `0022`. Never hand-edit `alembic_version`.

### Task 2: Share JSON logging and define safe Worker events

**Files:**
- Create: `backend/app/logging.py`
- Create: `backend/app/worker/observability.py`
- Create: `backend/tests/unit/test_logging.py`
- Create: `backend/tests/unit/worker/test_observability.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: current `JsonFormatter` and `configure_logging` behavior from `app.main`.
- Produces: `JsonFormatter`, `configure_logging(settings, *, logger_name="app")`, fixed observability constants, `PollOutcome`, `WorkerTelemetry`, `safe_failure_code`, and `worker_log_extra`.

- [x] **Step 1: Write failing tests that freeze existing API JSON and the new Worker allowlist.**

```python
def test_worker_log_extra_contains_only_fixed_safe_fields() -> None:
    payload = worker_log_extra(event="worker_poll_failed", instance_id=UUID(int=1),
                               queue_name="catalog_import", outcome="failed",
                               duration_ms=2.5, attempt=3,
                               failure_code="consumer_unexpected_error")
    assert set(payload) == {"event", "worker_instance_id", "queue_name", "outcome", "duration_ms", "attempt", "failure_code"}
    assert "password" not in json.dumps(payload).lower()
```

- [x] **Step 2: Run the two new unit files and confirm import failures.**

```powershell
python -m pytest backend/tests/unit/test_logging.py backend/tests/unit/worker/test_observability.py -q
```

- [x] **Step 3: Extract logging with no API output drift.** Move formatter/configuration code to `app.logging`, retain timestamp/level/message/request fields and exception formatting, and re-export nothing from `app.main` unless an existing test imports it.

```python
_SAFE_EXTRA_FIELDS = (
    "request_id", "method", "path", "status_code", "duration_ms",
    "event", "worker_instance_id", "queue_name", "outcome",
    "attempt", "failure_code", "item_id",
)
```

- [x] **Step 4: Implement fixed constants, protocols, safe-code mapping, and event construction.** Reject unknown queue names and result/failure codes at the call boundary. Use a closed fallback and never include exception text.

```python
def safe_failure_code(error: BaseException, queue_name: QueueName) -> str:
    for exception_type, code in _QUEUE_FAILURE_CODES[queue_name]:
        if isinstance(error, exception_type):
            return code
    return "consumer_unexpected_error"
```

- [x] **Step 5: Run focused unit, lint, and type checks.**

```powershell
python -m pytest backend/tests/unit/test_logging.py backend/tests/unit/worker/test_observability.py -q
python -m ruff check --config backend/pyproject.toml backend/app/logging.py backend/app/worker/observability.py backend/app/main.py backend/tests/unit/test_logging.py backend/tests/unit/worker/test_observability.py
python -m mypy --config-file backend/pyproject.toml backend/app/logging.py backend/app/worker/observability.py backend/app/main.py
```

- [x] **Step 6: Commit.**

```powershell
git add backend/app/logging.py backend/app/worker/observability.py backend/app/main.py backend/tests/unit/test_logging.py backend/tests/unit/worker/test_observability.py
git commit -m "feat: standardize worker observability logs"
```

### Task 3: Implement database heartbeat lifecycle and claim gating

**Files:**
- Create: `backend/app/worker/heartbeat.py`
- Create: `backend/tests/unit/worker/test_heartbeat.py`
- Modify: `backend/app/worker/cli.py`
- Modify: `backend/tests/unit/worker/test_cli.py`
- Create: `backend/tests/integration/test_worker_observability.py`

**Interfaces:**
- Consumes: the Task 1 tables and Task 2 constants/events.
- Produces: `WorkerHeartbeatRepository`, `WorkerHeartbeatController`, independent 10-second heartbeats, immediate claim denial on write failure, stopped lifecycle, and bounded pruning.

- [x] **Step 1: Write deterministic controller tests with fake monotonic time and a non-sleeping wait function.** Cover registration success, registration failure, heartbeat sequence, age boundary at 10 seconds, failure/recovery, long queue work, bounded stop, and stop-write failure.

```python
def test_failed_heartbeat_closes_claim_gate_until_real_success() -> None:
    controller.start()
    assert controller.can_claim()
    repository.heartbeat.side_effect = OSError("database unavailable")
    trigger_heartbeat()
    assert not controller.can_claim()
    repository.heartbeat.side_effect = None
    trigger_heartbeat()
    assert controller.can_claim()
```

- [x] **Step 2: Run the focused tests and confirm failure.**

```powershell
python -m pytest backend/tests/unit/worker/test_heartbeat.py backend/tests/unit/worker/test_cli.py -q
```

- [x] **Step 3: Implement repository SQL as independent short transactions using bound parameters and database time.** Sequence updates must be monotonic and affect exactly one live instance; consumer updates target the exact `(instance_id, queue_name)` row.

```sql
UPDATE worker_instances
SET heartbeat_sequence = :sequence,
    last_heartbeat_at = UTC_TIMESTAMP(6),
    last_result_code = :result_code
WHERE instance_id = :instance_id
  AND lifecycle_status = 'running'
  AND heartbeat_sequence < :sequence
```

- [x] **Step 4: Implement bounded pruning.** Select at most 500 eligible instance IDs older than 30 days, then delete exactly those IDs in one short transaction. Cascading removes child rows. Never issue an unbounded delete.

```sql
SELECT instance_id
FROM worker_instances
WHERE COALESCE(stopped_at, last_heartbeat_at) < UTC_TIMESTAMP(6) - INTERVAL :retention_days DAY
ORDER BY COALESCE(stopped_at, last_heartbeat_at), instance_id
LIMIT :limit
```

- [x] **Step 5: Implement the controller with a dedicated daemon thread and monotonic freshness.** Registration performs the first successful database write. A heartbeat failure logs `worker_heartbeat_failed` and closes the claim gate synchronously before another queue can start.

```python
def can_claim(self) -> bool:
    with self._state_lock:
        return self._last_success_monotonic is not None and (
            self._monotonic() - self._last_success_monotonic <= HEARTBEAT_SECONDS
        )
```

- [x] **Step 6: Wire CLI ordering.** After Stage 1 schema compatibility succeeds, configure Worker JSON logging, create a UUID4 instance, resolve the build ID from the approved release environment or current Git SHA helper, register/start heartbeat, then construct/run `WorkerRunner`. In `finally`, stop the controller before disposing the engine. No ready text or claim occurs before registration.

```python
controller.start()
runner = WorkerRunner(..., telemetry=controller)
try:
    ...
finally:
    controller.stop()
    engine.dispose()
```

- [x] **Step 7: Add MySQL integration cases for database time, sequence monotonicity, consumer persistence, normal stop, and bounded pruning.** No disposable MySQL service was already active, so execution is reserved for Task 8's canonical 8.0/8.4 matrix; barrier and crash aging assertions are completed with the Task 5 query-time aggregator.

```powershell
python -m pytest backend/tests/unit/worker/test_heartbeat.py backend/tests/unit/worker/test_cli.py backend/tests/integration/test_worker_observability.py -q --require-mysql
```

- [x] **Step 8: Commit.**

```powershell
git add backend/app/worker/heartbeat.py backend/app/worker/cli.py backend/tests/unit/worker/test_heartbeat.py backend/tests/unit/worker/test_cli.py backend/tests/integration/test_worker_observability.py
git commit -m "feat: add worker database heartbeat lifecycle"
```

### Task 4: Record all four consumer polling states in `WorkerRunner`

**Files:**
- Modify: `backend/app/worker/runner.py`
- Modify: `backend/tests/unit/worker/test_runner.py`
- Modify: `backend/tests/integration/test_worker_observability.py`

**Interfaces:**
- Consumes: `WorkerTelemetry`, `PollOutcome`, and safe failure codes.
- Produces: per-queue start/success/failure records while preserving `WorkerPass` and independent exception handling.

- [x] **Step 1: Add failing ordering and isolation tests for every queue.** Assert `can_claim -> poll_started -> consumer.run_once -> poll_succeeded`, no consumer call when the gate is false or `poll_started` fails, `None` maps to `queue_idle`, work maps to `queue_work_completed`, and one consumer error still permits the other three.

```python
assert calls == [
    "can_claim:return_dedup",
    "poll_started:return_dedup",
    "run:return_dedup",
    "poll_failed:return_dedup:consumer_unexpected_error",
    "can_claim:publication_outbox",
]
```

- [x] **Step 2: Run only Runner tests and confirm the new expectations fail.**

```powershell
python -m pytest backend/tests/unit/worker/test_runner.py -q
```

- [x] **Step 3: Replace repeated try/except blocks with one private typed helper without changing queue order.** The order remains return dedup, publication outbox, catalog export, catalog import. Optional consumers still return `None` in `WorkerPass`.

```python
def _run_consumer(self, queue_name: QueueName, operation: Callable[[], T | None]) -> T | None:
    if not self._telemetry.can_claim():
        return None
    try:
        self._telemetry.poll_started(queue_name)
    except Exception:
        logger.exception("Consumer state start write failed", extra=...)
        return None
    try:
        result = operation()
    except Exception as error:
        self._telemetry.poll_failed(queue_name, safe_failure_code(error, queue_name))
        logger.exception("Worker consumer failed", extra=...)
        return None
    self._telemetry.poll_succeeded(
        queue_name,
        PollOutcome("queue_work_completed" if result is not None else "queue_idle", result is not None),
    )
    return result
```

- [x] **Step 4: Make telemetry completion failure safe.** A failed post-work status update emits `consumer_state_write_failed`; it must not re-run the completed business item or mutate its native state. The next queue may proceed only if `can_claim()` still passes.

- [x] **Step 5: Add one integration case showing overall heartbeat remains online while one consumer has increasing failures and the other three retain independent success timestamps.** The fixture stores only safe codes. The disposable MySQL execution remains deferred to Task 8 under the approved minimal-test policy; local collection skipped all four MySQL cases as expected.

```powershell
python -m pytest backend/tests/unit/worker/test_runner.py backend/tests/integration/test_worker_observability.py -q --require-mysql
python -m ruff check --config backend/pyproject.toml backend/app/worker/runner.py backend/tests/unit/worker/test_runner.py
python -m mypy --config-file backend/pyproject.toml backend/app/worker/runner.py
```

- [x] **Step 6: Commit.**

```powershell
git add backend/app/worker/runner.py backend/tests/unit/worker/test_runner.py backend/tests/integration/test_worker_observability.py
git commit -m "feat: track worker consumer polling health"
```

### Task 5: Build database-authoritative Worker and queue aggregation

**Files:**
- Create: `backend/app/maintenance/worker_status.py`
- Create: `backend/tests/unit/maintenance/test_worker_status.py`
- Modify: `backend/tests/integration/test_worker_observability.py`

**Interfaces:**
- Consumes: Task 1 tables, frozen thresholds, and existing queue schemas.
- Produces: `read_worker_observability(engine, *, maintenance_active)` with one database `observed_at`, Worker fleet status, four ordered queue statuses, capabilities, and per-query isolation.

- [x] **Step 1: Write unit tests for boundary classification and null semantics.** Use `29.999 -> online`, `30 -> stale`, `59.999 -> stale`, `60 -> offline`, explicit stopped, failed fleet query -> unknown, and maintenance true with offline unchanged.

```python
@pytest.mark.parametrize(("age", "expected"), [(29.999, "online"), (30, "stale"), (60, "offline")])
def test_heartbeat_boundaries(age: float, expected: str) -> None:
    assert classify_heartbeat(age_seconds=age, lifecycle_status="running") == expected
```

- [x] **Step 2: Write mapping tests for empty, actionable, active, retry, stale/stuck, failed, and terminal native states.** Assert every false capability has a null metric.

```python
assert export.capabilities.in_flight is False
assert export.in_flight is None
assert export.unresolved_building == 2
assert catalog_import.stuck == 1
assert catalog_import.actionable == uploaded_count
```

- [x] **Step 3: Run the unit file and confirm it fails before implementation.**

```powershell
python -m pytest backend/tests/unit/maintenance/test_worker_status.py -q
```

- [x] **Step 4: Implement one observed time and five isolated reads.** Fetch `UTC_TIMESTAMP(6)` first. Read Worker rows in one connection and each queue in its own connection. Catch and classify query failures only at those boundaries.

```python
with engine.connect() as connection:
    observed_at = _required_utc(connection.scalar(sa.text("SELECT UTC_TIMESTAMP(6)")))
workers = _read_workers(engine, observed_at=observed_at)
queues = [_read_queue_isolated(engine, queue_name=name, observed_at=observed_at) for name in QUEUE_NAMES]
```

- [x] **Step 5: Implement SQL from native state, never from Worker memory.** Bind `observed_at` into each query. For imports, join only the latest `catalog_parse_attempts` revision for parsing rows to evaluate lease expiry and recoverability. For exports, never infer an owner or lease.

```sql
SUM(status='uploaded') AS actionable,
SUM(status='parsing' AND latest.lease_expires_at > :observed_at) AS in_flight,
SUM(status='parsing' AND latest.lease_expires_at <= :observed_at) AS stuck,
SUM(status='parse_failed') AS failed
```

- [x] **Step 6: Derive queue-level consumer health only from visible instance consumer rows.** Any online instance with consecutive failures greater than zero makes that queue `failing`; an online success with zero failures makes it `healthy`; no observed consumer is `not_observed`; fleet query failure is `unknown`. Include latest success/failure timestamps and highest current failure streak without hiding per-instance rows.

- [x] **Step 7: Add disposable MySQL fixture reconciliation and single-query-failure injection.** Verify the shared database `observed_at`, direct-SQL native counts, null metrics for an unknown queue, and isolation of the other healthy queue queries. Disposable MySQL execution remains deferred to Task 8 under the approved minimal-test policy.

```powershell
python -m pytest backend/tests/unit/maintenance/test_worker_status.py backend/tests/integration/test_worker_observability.py -q --require-mysql
```

- [x] **Step 8: Commit.**

```powershell
git add backend/app/maintenance/worker_status.py backend/tests/unit/maintenance/test_worker_status.py backend/tests/integration/test_worker_observability.py
git commit -m "feat: aggregate worker and queue health"
```

### Task 6: Append observability to the administrator maintenance API

**Files:**
- Modify: `backend/app/api/maintenance.py`
- Create: `backend/tests/integration/test_worker_observability_api.py`
- Modify: `backend/tests/unit/test_openapi_contract.py`
- Modify (generated): `frontend/src/api/generated.ts`

**Interfaces:**
- Consumes: `read_worker_observability` and all fixed response models.
- Produces: backward-compatible `MaintenanceStatusResponse` fields and generated TypeScript types.

- [x] **Step 1: Add failing API tests.** Assert existing fields are byte-shape compatible, appended fields exist, queue order is fixed, maintenance flags are orthogonal, non-admin receives 403, unauthenticated receives 401, and successful responses contain `private, no-store`.

```python
assert response.headers["cache-control"] == "private, no-store"
payload = response.json()
assert list(payload) == ["backups", "restores", "outbox", "write_lock", "observed_at", "maintenance_active", "worker", "queues"]
assert [item["queue_name"] for item in payload["queues"]] == list(QUEUE_NAMES)
```

- [x] **Step 2: Run only the API and OpenAPI contract tests and confirm the new fields are absent.** The OpenAPI assertion failed on the missing appended fields; disposable MySQL execution remains deferred to Task 8 under the approved minimal-test policy.

```powershell
python -m pytest backend/tests/integration/test_worker_observability_api.py backend/tests/unit/test_openapi_contract.py -q --require-mysql
```

- [x] **Step 3: Add the response models and call the aggregator after the existing lock probe.** Set `maintenance_active=lock.held`; do not collapse it into Worker status. Preserve the existing `outbox` projection for old clients even though `publication_outbox` also appears in `queues`.

```python
observed_at, worker, queues = read_worker_observability(
    database_engine,
    maintenance_active=lock.held,
)
response = MaintenanceStatusResponse(..., observed_at=observed_at,
                                     maintenance_active=lock.held,
                                     worker=worker, queues=queues)
```

- [x] **Step 4: Add a FastAPI `Response` parameter and set the explicit cache header at the route response boundary.** Test the effective response, not just source text.

```python
def maintenance_status(request: Request, response: Response, ...) -> MaintenanceStatusResponse:
    ...
response.headers["Cache-Control"] = "private, no-store"
```

- [x] **Step 5: Regenerate the TypeScript client and prove no drift.**

```powershell
pwsh -File scripts/generate-api-client.ps1
pwsh -File scripts/generate-api-client.ps1 -Check
```

- [x] **Step 6: Run focused API verification and static checks.** OpenAPI and generated-contract tests passed; MySQL-backed authorization/response tests were collected and skipped pending Task 8.

```powershell
python -m pytest backend/tests/integration/test_worker_observability_api.py backend/tests/unit/test_openapi_contract.py -q --require-mysql
python -m ruff check --config backend/pyproject.toml backend/app/api/maintenance.py backend/app/maintenance/worker_status.py backend/tests/integration/test_worker_observability_api.py
python -m mypy --config-file backend/pyproject.toml backend/app/api/maintenance.py backend/app/maintenance/worker_status.py
```

- [x] **Step 7: Commit generated and source changes together.**

```powershell
git add backend/app/api/maintenance.py backend/tests/integration/test_worker_observability_api.py backend/tests/unit/test_openapi_contract.py frontend/src/api/generated.ts
git commit -m "feat: expose worker observability to admins"
```

### Task 7: Render the administrator runtime-status view with bounded refresh

**Files:**
- Create: `frontend/src/features/admin/WorkerObservabilityPanel.tsx`
- Create: `frontend/src/features/admin/WorkerObservabilityPanel.test.tsx`
- Create: `frontend/tests/e2e/admin-worker-observability.spec.ts`
- Modify: `frontend/src/features/admin/AdminConsole.tsx`
- Modify: `frontend/src/features/admin/AdminConsole.css`
- Modify: `frontend/src/features/admin/AdminConsole.test.tsx`
- Modify: `frontend/tests/e2e/project-optimization-baseline.spec.ts`

**Interfaces:**
- Consumes: generated `MaintenanceStatusResponse`, `WorkerInstanceStatusResponse`, and `QueueStatusResponse`.
- Produces: an accessible status panel, manual refresh, active-tab-only 15-second automatic refresh, and a single focused Playwright flow.

- [x] **Step 1: Expand fixtures with one online Worker, one failing consumer, all four queues, one false capability, and maintenance-off.** Keep the existing backup/outbox/write-lock fixture values.

```ts
const workerStatus = {
  observed_at: "2026-09-04T08:00:00Z",
  maintenance_active: false,
  worker: { query_health: "healthy", failure_code: null, thresholds: {
    heartbeat_seconds: 10, stale_seconds: 30, offline_seconds: 60, refresh_seconds: 15,
  }, instances: [] },
  queues: [],
};
```

- [x] **Step 2: Write failing component tests.** Cover text+icon+color status, online disclaimer, timestamps, thresholds, queue null as `不适用`, unknown as `无法确认`, catalog import stuck, catalog export unresolved building, consumer failure code, maintenance ambiguity copy, and page-last-refresh time.

```tsx
expect(screen.getByText("在线仅表示最近成功写入数据库心跳")).toBeVisible();
expect(screen.getAllByText("不适用").length).toBeGreaterThan(0);
expect(screen.getByText("进程在线，catalog_import 消费者失败")).toBeVisible();
```

- [x] **Step 3: Add fake-timer tests for refresh ownership.** The first request occurs only after opening the maintenance tab, repeats every 15 seconds while visible, does not overlap an in-flight request, stops after changing tabs/unmount, and manual refresh remains available. A failed refresh preserves the last rendered response but labels it stale and shows the error.

```ts
vi.useFakeTimers();
await vi.advanceTimersByTimeAsync(15_000);
expect(fetchMock).toHaveBeenCalledTimes(2);
```

- [x] **Step 4: Run only the two admin unit files and confirm failure.**

```powershell
Set-Location frontend
pnpm exec vitest run src/features/admin/WorkerObservabilityPanel.test.tsx src/features/admin/AdminConsole.test.tsx
Set-Location ..
```

- [x] **Step 5: Implement `WorkerObservabilityPanel` as a pure presentational component.** Props are `status`, `pageRefreshedAt`, `refreshing`, `refreshError`, and `onRefresh`. Use semantic headings/lists, `aria-live="polite"` only for refresh summary, visible icons or glyphs, status text, CSS classes, and `<time dateTime>`. Do not add operational mutation buttons.

```tsx
type Props = {
  status: MaintenanceStatusResponse;
  pageRefreshedAt: Date;
  refreshing: boolean;
  refreshError: string | null;
  onRefresh: () => void;
};
```

- [x] **Step 6: Keep request lifecycle in `AdminConsole`.** Use the API-provided `refresh_seconds` and clamp it to the approved maximum of 15 seconds; clear the interval when the tab is inactive. Track a request-in-flight ref to prevent overlap and never derive Worker health from the browser clock.

```ts
const refreshMs = Math.min(maintenance.worker.thresholds.refresh_seconds, 15) * 1_000;
const timer = window.setInterval(() => { void loadMaintenance({ background: true }); }, refreshMs);
return () => window.clearInterval(timer);
```

- [x] **Step 7: Add responsive blue/white styles.** At desktop, show fleet summary then four queue cards; at 768px use two columns; at 390px use one column with no hidden operational fact. Every severity uses class, icon, and text; focus remains visible; no animation is required.

- [x] **Step 8: Add one Playwright test.** Mock only authenticated admin/API responses, open `/admin`, click `备份与任务`, assert Worker/queue/maintenance semantics, advance or wait for one refresh, and verify another tab stops polling. Use no screenshot baseline in Stage 2.

```powershell
Set-Location frontend
pnpm exec vitest run src/features/admin/WorkerObservabilityPanel.test.tsx src/features/admin/AdminConsole.test.tsx
pnpm exec eslint src/features/admin/WorkerObservabilityPanel.tsx src/features/admin/WorkerObservabilityPanel.test.tsx src/features/admin/AdminConsole.tsx src/features/admin/AdminConsole.test.tsx tests/e2e/admin-worker-observability.spec.ts
pnpm typecheck
pnpm exec playwright test tests/e2e/admin-worker-observability.spec.ts --project=chromium --workers=1
Set-Location ..
```

- [x] **Step 9: Commit.**

```powershell
git add frontend/src/features/admin/WorkerObservabilityPanel.tsx frontend/src/features/admin/WorkerObservabilityPanel.test.tsx frontend/src/features/admin/AdminConsole.tsx frontend/src/features/admin/AdminConsole.css frontend/src/features/admin/AdminConsole.test.tsx frontend/tests/e2e/admin-worker-observability.spec.ts frontend/tests/e2e/project-optimization-baseline.spec.ts
git commit -m "feat: show worker health in admin console"
```

### Task 8: Canonical suites, performance evidence, runbook, and same-SHA acceptance

**Files:**
- Create: `scripts/project-optimization-stage2-manifest.json`
- Create: `scripts/run-project-optimization-stage2.ps1`
- Create: `backend/tests/contracts/test_project_optimization_stage2_contract.py`
- Create: `docs/operations/worker-observability.md`
- Modify: `scripts/ci-suite-manifest.json`
- Modify: `backend/tests/fixtures/ci/mysql-compatibility-nodeids.txt`
- Modify: `backend/tests/fixtures/ci/offline-backend-nodeids.txt`
- Modify: `backend/tests/fixtures/ci/windows-smoke-nodeids.txt`
- Modify: `backend/tests/performance/test_project_optimization_baseline.py`
- Modify: `docs/operations/local-maintenance.md`

**Interfaces:**
- Consumes: Tasks 1–7 and the Stage 0 approved ceilings.
- Produces: canonical MySQL coverage, real implementation performance comparisons, redacted evidence, rollback/deployment instructions, and one final clean candidate SHA.

- [ ] **Step 1: Add a dedicated canonical MySQL suite and contract tests.** Add `mysql-worker-observability` containing exactly the two new integration files and include it in `mysql-compatibility.suites`. Add the new offline unit/contract files to their applicable profiles, then regenerate node lists through the existing list/identity mechanism and review every addition.

```json
"mysql-worker-observability": [
  "backend/tests/integration/test_worker_observability.py",
  "backend/tests/integration/test_worker_observability_api.py"
]
```

- [ ] **Step 2: Replace the temporary heartbeat probe measurement with the real repository/controller path while preserving Stage 0 scenario IDs and sample protocol.** Add measurements for the final four queue queries and maintenance API. The three warmups, twenty samples, and three independent rounds remain unchanged.

```python
SCENARIO_CEILINGS_MS = {
    "admin-maintenance-api": {"8.0": 50, "8.4": 28},
    "heartbeat-single-update": {"8.0": 57, "8.4": 22},
    "heartbeat-long-task": {"8.0": 12028, "8.4": 12052},
    "heartbeat-maintenance-barrier": {"8.0": 27, "8.4": 21},
    "worker-idle-pass": {"8.0": 11, "8.4": 10},
    "queue-publication-outbox": {"8.0": 1, "8.4": 1},
    "queue-return-dedup": {"8.0": 2, "8.4": 1},
    "queue-catalog-import": {"8.0": 2, "8.4": 2},
    "queue-catalog-export": {"8.0": 1, "8.4": 2},
    "ui-admin-maintenance-load": {"chromium": 283},
}
```

- [ ] **Step 3: Create the Stage 2 evidence manifest and runner.** Require a 40-character source SHA, clean tracked workspace, MySQL version, environment fingerprint, exact command, start/end time, exit code, node count/digest, performance raw results, EXPLAIN output, screenshots, and redaction scan. Evidence is written to a caller-supplied directory outside `data/` and never overwrites existing files.

```powershell
param(
    [ValidatePattern('^[0-9a-f]{40}$')][string]$SourceSha,
    [ValidateSet('Collect','Validate')][string]$Mode,
    [string]$EvidenceRoot
)
```

- [ ] **Step 4: Write the operational runbook.** Document start/stop, heartbeat meanings, queue mappings, unknown/maintenance interpretation, safe failure-code lookup, bounded 30-day pruning, performance ceilings, and incident checks. The deployment order is: stop old API/Worker; back up; run explicit `0023` migration and privilege sync; verify exact head; deploy matching API/Worker; verify a real heartbeat; inspect all four queues.

- [ ] **Step 5: Document rollback precisely.** UI can revert independently. API/Worker rollback at schema `0023` targets `STAGE2_SCHEMA_ANCHOR`; stop new Workers first and wait for existing native leases/claims to reach their established recovery condition. Do not change processing rows manually. Dropping observability tables requires a separately approved migration and never occurs during emergency application rollback.

- [ ] **Step 6: Run fast manifest/evidence self-checks before the expensive gate.**

```powershell
python -m pytest backend/tests/contracts/test_ci_suite_manifest.py backend/tests/contracts/test_project_optimization_stage2_contract.py -q
pwsh -File scripts/run-ci-profile.ps1 -Profile ubuntu-full -ListOnly
pwsh -File scripts/run-ci-profile.ps1 -Profile windows-smoke -ListOnly
pwsh -File scripts/run-ci-profile.ps1 -Profile mysql-compatibility -MySqlVersion 8.0 -ListOnly
pwsh -File scripts/generate-api-client.ps1 -Check
```

- [ ] **Step 7: Commit suite, evidence, performance, and runbook changes.**

```powershell
git add scripts/project-optimization-stage2-manifest.json scripts/run-project-optimization-stage2.ps1 scripts/ci-suite-manifest.json backend/tests/contracts/test_project_optimization_stage2_contract.py backend/tests/fixtures/ci/mysql-compatibility-nodeids.txt backend/tests/fixtures/ci/offline-backend-nodeids.txt backend/tests/fixtures/ci/windows-smoke-nodeids.txt backend/tests/performance/test_project_optimization_baseline.py docs/operations/worker-observability.md docs/operations/local-maintenance.md
git commit -m "test: gate stage 2 worker observability"
```

- [ ] **Step 8: Freeze the candidate SHA and do not amend commits after evidence starts.**

```powershell
$stage2Sha = (git rev-parse HEAD).Trim()
if ($stage2Sha -notmatch '^[0-9a-f]{40}$') { throw 'Invalid candidate SHA.' }
if (git status --porcelain --untracked-files=no) { throw 'Tracked workspace is not clean.' }
```

- [ ] **Step 9: Run the full same-SHA quality profiles exactly once.** These are the only full-suite executions in the implementation plan.

```powershell
pwsh -File scripts/run-ci-profile.ps1 -Profile ubuntu-full
pwsh -File scripts/run-ci-profile.ps1 -Profile windows-smoke
pwsh -File scripts/run-ci-profile.ps1 -Profile frontend-full
pwsh -File scripts/run-ci-profile.ps1 -Profile mysql-compatibility -MySqlVersion 8.0
pwsh -File scripts/run-ci-profile.ps1 -Profile mysql-compatibility -MySqlVersion 8.4
pwsh -File scripts/run-ci-profile.ps1 -Profile release-only -ReleaseSuite generated-contract -SourceSha $stage2Sha
```

- [ ] **Step 10: Run Stage 2 evidence, performance, privilege, backup/restore, and deployment rehearsal on the same SHA.** Use disposable databases only. The runner must reject a mismatched SHA, dirty tracked workspace, missing 8.0/8.4 result, unexplained skip/xfail/retry, or a result above an approved ceiling.

```powershell
$evidenceRoot = Join-Path ([IO.Path]::GetTempPath()) "clsen-stage2-$stage2Sha"
pwsh -File scripts/run-project-optimization-stage2.ps1 -SourceSha $stage2Sha -Mode Collect -EvidenceRoot $evidenceRoot
pwsh -File scripts/run-project-optimization-stage2.ps1 -SourceSha $stage2Sha -Mode Validate -EvidenceRoot $evidenceRoot
```

- [ ] **Step 11: Verify the required human-readable evidence.** Capture migration/rollback rehearsal, grants, backup/restore, fake-time thresholds, live stop/crash/barrier behavior, real recognition timing, shared `observed_at`, four-queue SQL reconciliation, isolated consumer failure, authorization denial, redacted JSON logs, administrator page screenshot, Playwright output, EXPLAIN plans, performance comparison, and canonical node collection.

- [ ] **Step 12: Stop at local completion.** Report the candidate SHA, schema anchor SHA, evidence directory, suite outcomes, elapsed time, and any residual operational risk. Do not push or merge.

## Self-Review Checklist

- [ ] Stage 2 roadmap lines 557–617 map to Tasks 1–8 with no omitted migration, lifecycle, queue, API, UI, retention, logging, permissions, backup/restore, performance, or evidence requirement.
- [ ] Every created or modified path is listed in the Planned File Set and each task owns an explicit subset.
- [ ] All names in Tasks 3–7 match the Fixed Contracts: `QUEUE_NAMES`, `PollOutcome`, `WorkerTelemetry`, `WorkerHeartbeatRepository`, `WorkerHeartbeatController`, and `read_worker_observability`.
- [ ] Health and maintenance remain separate; queue query failures preserve nulls and do not poison other queues.
- [ ] `catalog_export` unsupported metrics are null with false capabilities and `catalog_import` expired parsing is stuck, not actionable.
- [ ] Heartbeat registration precedes claim, write failure closes the gate, long work does not block the heartbeat thread, and native queue state is never rewritten by monitoring.
- [ ] Runtime grants are table-specific and pruning is bounded to 500 parent rows per call.
- [ ] The API is additive, admin-only, private/no-store, and generated TypeScript is updated from OpenAPI.
- [ ] The UI refreshes only while active, no faster than 15 seconds, prevents overlapping fetches, and uses text+icon+color.
- [ ] Tasks 1–7 contain only focused validation; all dual-version/full/performance/deployment work is confined to Task 8.
- [ ] Rollback at schema `0023` points to `STAGE2_SCHEMA_ANCHOR`; Stage 1 `0022` is never described as compatible with schema `0023`.
- [ ] All database and browser fixtures are synthetic and disposable, and no instruction accesses `data/`.
- [ ] Final acceptance uses one frozen clean SHA and does not reuse evidence from another commit.
