# Read-Only Agent Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independently deployed, read-only DeepSeek analysis experience that answers from one immutable published-data snapshot and renders only server-verified facts, claims, charts, and references.

**Architecture:** The existing FastAPI application remains the authority for sessions, object ownership, immutable snapshot capture, read-only tools, facts, claims, rendering, usage, and persistence. A separate no-database Runtime process uses `ChatDeepSeek.bind_tools` through LangChain and a bounded explicit loop over a narrow internal control protocol; the existing React application adds `/agent` as an authenticated page, while production isolates the Runtime with mTLS and deny-by-default egress.

**Tech Stack:** Python 3.14, FastAPI, synchronous SQLAlchemy 2, MySQL 8.0/8.4, Pydantic, LangChain Core, `langchain-deepseek`, React 19, TypeScript 5.9, React Router 7, Vitest, Playwright, Docker Compose, Nginx.

## Global Constraints

- The approved design is `docs/superpowers/specs/2026-08-12-read-only-agent-analysis-design.md`; any implementation choice that changes its data, security, retention, or deployment boundary requires a new design approval.
- Keep Python at `>=3.14,<3.15`, MySQL compatible with 8.0 and 8.4, synchronous SQLAlchemy/FastAPI database access, and the current React 19/TypeScript stack.
- `/agent` is in the existing React application and is available to authenticated `admin`, `data_manager`, and `viewer` roles; users may read only their own unexpired conversations and runs.
- Each question is an independent model run. Never send an older question, answer, fact, claim, or snapshot to the model, even when runs share a conversation.
- A run belongs to the request-time current site, covers one inclusive explicit date range of at most 366 days, and freezes the publication/configuration manifest before it becomes claimable.
- Snapshot capture must execute `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ` followed by `START TRANSACTION WITH CONSISTENT SNAPSHOT`; perform no prior consistency read and no locking read on that connection.
- Preserve `PublishedAnalyticsQueryService` as the current-publication dashboard reader. Agent tools must use an independent snapshot-scoped reader and an `agent_reader` engine; reader failure must never fall back to the main engine.
- Expose exactly `published_summary`, `product_performance`, and `return_breakdown`; reject extra fields, caller-supplied version IDs, SQL, paths, URLs, drafts, and unknown enum values.
- The model may select known `claim_id` values and controlled block order only. Numbers, dates, entities, directions, ranks, units, coverage, charts, links, and prose are generated and validated by versioned backend code.
- Treat all strings as untrusted. Reject likely secrets/PII in questions, normalize return dimensions, pseudonymize or hide suspect SKU values, allow only approved ASIN shapes, and withhold SKU/ASIN groups smaller than 3 from the provider.
- Hard run limits are 90 seconds, 6 tool attempts, 7 model calls, 32,000 cumulative input tokens, 4,096 cumulative output tokens, 200 rows and 256 KiB per tool result, 512 KiB total tool context, 2,000 Unicode characters per question, and 64 KiB each for the structured plan and final rendered answer.
- Admission limits are one active run per conversation, one active run per user, two global real-model slots, and six create attempts per user per rolling minute; enforce them in shared database state, not process-local locks.
- Once any provider attempt is `possible_charge` or has unknown usage, fail the run and permit exactly zero subsequent provider calls.
- Conversation content expires at the fixed creation time plus 30 days, with at most a 10-minute terminal grace. Content-free HMAC idempotency tombstones and usage remain for 12 months; never persist a bare question hash.
- `APP_AGENT_ENABLED=false` is the startup ceiling. The versioned persistent kill switch is checked at create, claim, model prepare/dispatch, tool execution, and answer commit; stop new work within 5 seconds and terminate in-flight work within 10 seconds.
- A server-side versioned role allowlist supports staged rollout: start with `admin,data_manager`, record each scope change, and add `viewer` only after observation gates pass. It constrains creation in addition to normal authorization; it never grants access beyond the three approved roles or hides already-owned answers.
- Runtime has no MySQL configuration, raw/backup/keyring mounts, Docker socket, business API access, or unrestricted egress. Production internal control traffic uses a dedicated mTLS listener/sidecar and never traverses edge Nginx.
- Agent/Runtime/DeepSeek health must not affect the existing public `/api/health/ready`; an Agent dependency failure disables only Agent creation.
- Ordinary tests block socket/HTTP egress and explicitly exclude `deepseek_live`. Live DeepSeek tests require both the marker and a CLI switch, use approved synthetic data, and never read the repository `.env` or a production database.
- Agent content tables are schema-only in long-term backup. Backup format v2 must classify every application table exactly once and prove via decrypted-artifact canaries that no Agent content entered SQL artifacts.
- The stage-17 performance protocol is an explicit target-environment acceptance test, not an ordinary correctness/load test and not a claim about current performance.
- Start production disabled. Do not enable it until deterministic, MySQL, privacy, network, provider-compliance, live synthetic, kill-switch, restore, and target-performance gates all pass.

---

## Locked File Structure and Interfaces

The following structure is fixed before task execution. Keep existing large files (`App.tsx`, deployment entrypoint, backup/restore) in their established style, but put new Agent responsibilities in focused files.

```text
backend/app/
├─ agent/
│  ├─ domain.py              # stable states, errors, events, immutable commands/results
│  ├─ settings.py            # API limits, versions, prices, retention, safe disabled status
│  ├─ idempotency.py         # canonical request bytes and versioned HMAC digests
│  ├─ repository.py          # main-engine state machine, slots, leases, events, usage
│  ├─ service.py             # admission, snapshot compensation, ownership, cleanup
│  ├─ privacy.py             # question/DLP checks and outbound value normalization
│  ├─ facts.py               # canonical facts, closed claims, display-plan validation
│  ├─ rendering.py           # versioned Chinese answer blocks and controlled links
│  ├─ monitoring.py          # content-free operational samples and rollups
│  └─ sse.py                 # persistent-event polling and SSE framing
├─ agent_control/
│  ├─ main.py                # separate internal FastAPI application/listener
│  ├─ auth.py                # development token or server mTLS identity boundary
│  ├─ contracts.py           # claim/heartbeat/model/tool/terminal DTOs
│  ├─ service.py             # fencing, kill-switch and possible-charge protocol
│  └─ cli.py                 # internal control listener entry point
├─ analytics/
│  ├─ snapshot_models.py     # manifest, expected grid, scanned/matching/contributor refs
│  └─ snapshot_service.py    # consistent capture and snapshot-scoped aggregate reader
├─ api/
│  ├─ agent.py               # public JSON/SSE endpoints
│  ├─ agent_admin.py         # content-free admin usage endpoints
│  └─ agent_dependencies.py  # main/reader factories without fallback
├─ db/agent_reader.py        # isolated reader engine and connection checks
└─ sites/query.py            # one shared current-site resolver

agent_runtime/
├─ pyproject.toml
├─ requirements.in
├─ requirements.lock
├─ Dockerfile
├─ clsen_agent_runtime/
│  ├─ contracts.py
│  ├─ settings.py
│  ├─ control_client.py
│  ├─ runtime.py             # AgentRuntime Protocol
│  ├─ langchain_deepseek.py  # bind_tools plus explicit bounded loop
│  ├─ token_budget.py
│  └─ cli.py
└─ tests/

frontend/src/features/agent/
├─ AgentAnalysisPage.tsx
├─ AgentAnalysisPage.css
├─ agentApi.ts
├─ agentEvents.ts
└─ corresponding Vitest files
```

Canonical cross-task Python interfaces are:

```python
class AgentRunStatus(StrEnum):
    PREPARING = "preparing"
    QUEUED = "queued"
    RUNNING = "running"
    VALIDATING = "validating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

@dataclass(frozen=True, slots=True)
class RunSnapshotManifest:
    snapshot_id: UUID
    site_id: int
    from_date: date
    to_date: date
    site_config: SiteConfigurationReference
    report_date_publications: tuple[PublicationReference, ...]
    event_date_return_candidate_publications: tuple[PublicationReference, ...]
    expected_grid: tuple[ExpectedPublicationCell, ...]
    runtime_version: str
    model_config_version: str
    prompt_version: str
    tool_schema_version: str
    normalization_version: NormalizationReference
    privacy_version: str
    validator_version: str
    manifest_sha256: str

class AgentSnapshotCaptureService:
    def capture(self, *, site_id: int, from_date: date, to_date: date) -> RunSnapshotManifest: ...

class SnapshotScopedAnalyticsQueryService:
    def __init__(self, reader: Connection, manifest: RunSnapshotManifest) -> None: ...
    def summary(self, from_date: date, to_date: date) -> AgentSummaryResult: ...
    def products(self, from_date: date, to_date: date, *, limit: int) -> AgentProductResult: ...
    def returns(self, from_date: date, to_date: date, *, basis: ReturnBasis) -> AgentReturnResult: ...

class AgentRuntime(Protocol):
    def run(self, task: RuntimeTask, control: AgentControlClient) -> RuntimeOutcome: ...
```

`RuntimeOutcome` is either a closed `DisplayPlan(claim_ids: tuple[str, ...], blocks: tuple[DisplayBlockKind, ...])` or a normalized failure. Public answers contain `RenderedAnswerBlock` values generated by FastAPI and never provider prose.

### Task 1: Lock Runtime Dependencies, Offline Network Policy, and Safe-Disabled Configuration

**Files:**
- Create: `agent_runtime/pyproject.toml`
- Create: `agent_runtime/requirements.in`
- Create: `agent_runtime/requirements.lock`
- Create: `agent_runtime/clsen_agent_runtime/__init__.py`
- Create: `agent_runtime/clsen_agent_runtime/settings.py`
- Create: `agent_runtime/tests/conftest.py`
- Create: `agent_runtime/tests/test_settings.py`
- Create: `backend/app/agent/__init__.py`
- Create: `backend/app/agent/settings.py`
- Create: `backend/tests/unit/agent/__init__.py`
- Create: `backend/tests/unit/agent/test_settings.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/requirements.in`
- Modify: `backend/requirements.lock`
- Modify: `.env.example`
- Modify: `.github/workflows/compatibility.yml`

**Interfaces:**
- Produces: `AgentApiSettings.from_env(environment: Mapping[str, str]) -> AgentApiSettings`, whose defaults are disabled and whose limits exactly match Global Constraints.
- Produces a closed staged-rollout ceiling `APP_AGENT_CREATE_ROLES`, defaulting to no enabled role while Agent is disabled and accepting only subsets of `{admin,data_manager,viewer}`; persistent scope changes are versioned alongside the kill switch before production use.
- Produces: `RuntimeSettings.from_env(environment: Mapping[str, str]) -> RuntimeSettings`, with one fixed provider/model/tokenizer combination, `max_retries=0`, tracing disabled, and secret paths hidden from `repr`.
- Produces: pytest option `--run-deepseek-live`; a test runs live only when both that option and `@pytest.mark.deepseek_live` are present.
- Produces: an autouse offline transport guard that raises `AssertionError("unexpected external network access")` for socket/HTTP calls outside the explicitly enabled live suite.

- [ ] **Step 1: Write failing settings, marker, and network-policy tests**

Add tests proving: API defaults to `APP_AGENT_ENABLED=false`; rollout roles reject unknown/duplicate values and can only narrow the three approved roles; missing/invalid Runtime, HMAC keyring, reader URL, or provider settings produce an Agent-disabled status rather than an application-startup exception; server mode rejects a stub provider; all numeric values may only tighten the hard defaults; Runtime has exactly one model and tokenizer version; secrets do not appear in `repr`; live tests need both gates; an ordinary test attempting `socket.create_connection(("example.com", 443))` fails immediately.

```python
def test_agent_api_defaults_to_safely_disabled() -> None:
    settings = AgentApiSettings.from_env({})
    assert settings.enabled is False
    assert settings.status_reason == "agent_disabled"

def test_unmarked_test_cannot_open_an_external_socket() -> None:
    with pytest.raises(AssertionError, match="unexpected external network access"):
        socket.create_connection(("example.com", 443))
```

- [ ] **Step 2: Run the focused tests and verify the contracts are absent**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/agent/test_settings.py agent_runtime/tests/test_settings.py -m "not mysql and not deepseek_live" -v`

Expected: FAIL because the Agent settings packages, `deepseek_live` marker, CLI option, and network guard do not exist.

- [ ] **Step 3: Resolve and lock only the Runtime dependency surface**

Pin compatible stable releases discovered at implementation time for Python 3.14, including `langchain-core`, `langchain-deepseek`, HTTP transport, and the exact verified tokenizer package; do not add `langgraph` or use `langchain.create_agent`. Generate both hash-locked requirement files with the existing `pip-compile --generate-hashes` convention, record the resolved versions in `RuntimeSettings.runtime_version`, and fail disabled when the configured model/tokenizer contract cannot be verified. The main backend may contain only shared DTO dependencies; provider libraries belong in `agent_runtime`.

- [ ] **Step 4: Implement safe settings and the default network guard**

Use frozen slotted dataclasses and explicit environment parsers. Keep the existing public application settings loadable when Agent-specific values are absent. Register `deepseek_live`, implement `--run-deepseek-live`, and make ordinary CI commands use `-m "not mysql and not deepseek_live"` on Windows and Linux.

```python
@dataclass(frozen=True, slots=True)
class AgentApiSettings:
    enabled: bool = False
    deadline_seconds: int = 90
    max_tool_attempts: int = 6
    max_model_calls: int = 7
    max_input_tokens: int = 32_000
    max_output_tokens: int = 4_096
```

- [ ] **Step 5: Run dependency, configuration, and offline checks**

Run: `.\.venv\Scripts\python.exe -m pip install --require-hashes -r backend/requirements.lock`

Run: `.\.venv\Scripts\python.exe -m pip install --require-hashes -r agent_runtime/requirements.lock`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/agent/test_settings.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest agent_runtime/tests/test_settings.py -m "not deepseek_live" -v`

Expected: PASS; test output contains no live DeepSeek attempt, and selecting `-m deepseek_live` without `--run-deepseek-live` skips the test.

- [ ] **Step 6: Commit the dependency and configuration boundary**

```powershell
git add backend/pyproject.toml backend/requirements.in backend/requirements.lock backend/app/agent backend/tests/conftest.py backend/tests/unit/agent .env.example .github/workflows/compatibility.yml agent_runtime
git commit -m "chore: lock agent runtime dependencies"
```

### Task 2: Pre-Provision Stable View Identities and the Dedicated Reader Account

**Files:**
- Modify: `scripts/database-privileges.json`
- Modify: `scripts/init-database.ps1`
- Modify: `scripts/sync-test-runtime-grants.ps1`
- Modify: `scripts/test-mysql-matrix.ps1`
- Modify: `ops/mysql/init-users.sh`
- Create: `ops/migrate-with-definer-privilege.ps1`
- Modify: `backend/app/deployment/entrypoint.py`
- Create: `backend/app/db/agent_reader.py`
- Create: `backend/tests/unit/db/test_agent_reader.py`
- Create: `backend/tests/integration/test_agent_reader_permissions.py`
- Modify: `backend/tests/contracts/test_database_bootstrap_script.py`
- Modify: `backend/tests/contracts/test_test_grant_sync_script.py`
- Modify: `backend/tests/contracts/test_server_deployment.py`
- Modify: `backend/tests/unit/deployment/test_entrypoint.py`
- Modify: `.env.example`

**Interfaces:**
- Produces a locked/no-login `clsen_view_definer` account before Alembic runs, with only the exact base-column SELECT privileges needed to resolve Task-3 views.
- Produces `clsen_agent_reader` before migration with no grants and a revision-aware synchronizer. At Alembic revisions before `0020`, the only valid reader object-grant set is empty; at `0020` or later, synchronization requires all six Task-3 views to exist and grants exactly those six, failing on a missing/partial set. Task 2 verifies the pre-`0020` state; Task 3 activates and verifies the six-view state.
- Produces privilege-manifest schema version 6 with `view_definer.base_select_columns` and `agent_reader.select_views`; neither account receives a schema wildcard.
- Produces a dedicated one-shot migration wrapper for server deployment, plus equivalent local/matrix control flows, that uses an administrator secret only inside the migration job: grant `SET_USER_ID` on MySQL 8.0 or `SET_ANY_DEFINER` on MySQL 8.4, verify, run Alembic as `clsen_migrator`, revoke in `finally`, and verify absence before any service becomes ready. Because the definer is pre-created, `ALLOW_NONEXISTENT_DEFINER` is never granted; public FastAPI and Runtime never receive the administrator secret.
- Extends the migrator's existing schema-scoped DDL grant with `CREATE VIEW` (and retains its existing schema-scoped `DROP` for downgrade); this is never a global grant and is not given to app, reader, definer, or Runtime identities.
- Produces `create_agent_reader_engine(settings: DatabaseSettings) -> Engine`, with a small isolated pool and no fallback to the main engine.
- Produces `APP_AGENT_READER_DATABASE_URL` for FastAPI only and `APP_TEST_AGENT_READER_DATABASE_URL` for disposable integration tests.

- [ ] **Step 1: Write failing two-phase account and manifest tests**

Require pre-migration creation/locking of the stable definer and unprivileged reader, a version-selected temporary migration grant, migration execution, unconditional temporary-grant revocation, then post-migration drift revocation and revision-aware exact grants. Stub pre-`0020`, complete-`0020`, partial-`0020`, successful migration, and failed migration states: pre-`0020` yields zero reader object grants; complete `0020` renders six; a partial six-view set fails; and the temporary global privilege is absent after both migration outcomes. Test manifest version 6, duplicate/unsafe identifier rejection, and explicit base columns rather than `database.*`. Test that the definer cannot authenticate and the Runtime receives neither account secret nor URL.

```python
def test_privilege_manifest_has_stable_agent_identities(manifest) -> None:
    assert manifest.version == 6
    assert manifest.agent_reader.select_views == SAFE_AGENT_VIEWS
    assert "*" not in repr(manifest.view_definer.base_select_columns)
```

- [ ] **Step 2: Run account contract tests and see the identities missing**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_database_bootstrap_script.py backend/tests/contracts/test_test_grant_sync_script.py backend/tests/contracts/test_server_deployment.py backend/tests/unit/deployment/test_entrypoint.py backend/tests/unit/db/test_agent_reader.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_reader_permissions.py --require-mysql -v`

Expected: FAIL because manifest version 6, the stable definer, reader account, versioned temporary migration privilege, and two-phase synchronizer do not exist.

- [ ] **Step 3: Implement pre-migration identities and post-migration synchronization**

Update PowerShell, shell, CI, and container code together. Before Alembic, create/alter a locked definer with no usable credential and the reader with a rotated TLS-required secret but no object grants; grant the definer only enumerated source columns, and add schema-scoped `CREATE VIEW` to the migrator's existing DDL privileges. Implement `ops/migrate-with-definer-privilege.ps1` as the server's one-shot Compose migration entry: it alone mounts the administrator and migrator secrets, queries `SELECT VERSION()` through the administrator connection, accepts only MySQL `8.0.*` or `8.4.*`, selects `SET_USER_ID` for 8.0 or `SET_ANY_DEFINER` for 8.4, grants and positively verifies that privilege, invokes the existing migration entrypoint with the migrator URL, then revokes and negatively verifies in `finally` even when Alembic fails. Backend startup depends on that job's successful post-revoke verification. Local bootstrap and matrix fixtures perform the same sequence in their existing administrator-controlled process. Do not grant legacy `SUPER`, `ALLOW_NONEXISTENT_DEFINER`, `SYSTEM_USER`, either version's nonselected definer privilege, or any global privilege to app/reader/Runtime identities. After Alembic, revoke all schema/table/column/routine drift from definer and reader, reapply exact definer columns, read `alembic_version`, and apply the reader rule atomically: before `0020`, require that none of the six names exists and grant none; at `0020` or later, require all six as `VIEW` objects before granting all six. Never accept or grant a partial set. Build the reader TLS URL only in FastAPI roles.

```sql
CREATE USER IF NOT EXISTS 'clsen_view_definer'@'%' ACCOUNT LOCK;
ALTER USER 'clsen_view_definer'@'%' ACCOUNT LOCK;
CREATE USER IF NOT EXISTS 'clsen_agent_reader'@'%' IDENTIFIED BY ? REQUIRE SSL;
-- Exact column grants are generated from database-privileges.json; no db.* grant.
-- Root orchestration selects exactly one statement from SELECT VERSION():
-- MySQL 8.0: GRANT SET_USER_ID ON *.* TO 'clsen_migrator'@'%';
-- MySQL 8.4: GRANT SET_ANY_DEFINER ON *.* TO 'clsen_migrator'@'%';
-- The matching REVOKE runs unconditionally after Alembic.
```

- [ ] **Step 4: Implement the no-fallback engine and disposable fixtures**

Make `create_agent_reader_engine` reject equality with the main application URL, use `pool_size=2/max_overflow=0`, and surface a stable Agent-disabled error on connection/permission failure. Provision both identities before `alembic upgrade` in MySQL fixtures and matrix jobs, then run the revision-aware synchronizer after migration. At the repository's Task-2 head (`0019`), the real integration fixture asserts zero reader object grants; Task 3 extends the same test to the six-view state.

- [ ] **Step 5: Verify pre/post migration account behavior**

Run: `pwsh -File scripts/test-mysql-matrix.ps1`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_reader_permissions.py --require-mysql -v`

Expected: PASS on MySQL 8.0 and 8.4 at revision `0019`, including a forced-Alembic-failure drill: the migrator has schema-scoped `CREATE VIEW`/`DROP` but post-window `SHOW GRANTS FOR 'clsen_migrator'@'%'` contains neither `SET_USER_ID`, `SET_ANY_DEFINER`, `ALLOW_NONEXISTENT_DEFINER`, nor `SUPER`; `SHOW GRANTS` for app/reader/definer contains no unexpected global privilege; the definer is locked; the reader has zero object grants and cannot read base tables; the partial/future-view unit contract fails closed; and Runtime configuration has no MySQL material. Six-view integration verification is intentionally owned by Task 3.

- [ ] **Step 6: Commit stable database identities**

```powershell
git add scripts/database-privileges.json scripts/init-database.ps1 scripts/sync-test-runtime-grants.ps1 scripts/test-mysql-matrix.ps1 ops/mysql/init-users.sh ops/migrate-with-definer-privilege.ps1 backend/app/deployment/entrypoint.py backend/app/db/agent_reader.py backend/tests/unit/db/test_agent_reader.py backend/tests/integration/test_agent_reader_permissions.py backend/tests/contracts backend/tests/unit/deployment/test_entrypoint.py .env.example
git commit -m "feat: provision isolated agent database identities"
```

### Task 3: Add the Safe Published Read Model and Immutable Configuration Guards

**Files:**
- Create: `backend/alembic/versions/0020_agent_safe_read_model.py`
- Create: `backend/tests/integration/test_agent_safe_read_model.py`
- Create: `backend/tests/integration/test_agent_site_config_immutability.py`
- Modify: `backend/tests/integration/test_agent_reader_permissions.py`
- Modify: `backend/tests/contracts/test_migration_contract.py`
- Modify: `backend/tests/integration/test_migrations.py`
- Modify: `backend/tests/integration/test_database_constraints.py`
- Modify: `backend/tests/integration/test_published_analytics.py`
- Modify: `backend/tests/integration/test_admin_management_api.py`
- Modify: `backend/tests/integration/test_parse_workflow.py`

**Interfaces:**
- Produces these six versioned views and no additional reader-visible object: `agent_current_publications_v1`, `agent_published_versions_v1`, `agent_business_rows_v1`, `agent_return_rows_v1`, `agent_site_config_versions_v1`, and `agent_dimension_normalization_versions_v1`. The site-config view exposes exactly `site_id`, `site_code`, `site_status`, `site_config_version_id`, `source_timezone`, `reporting_timezone`, `currency_code`, `effective_at`, and `is_current`; it excludes `change_reason`, `created_by_user_id`, `created_at`, and every other internal field. The normalization view includes only sealed version ID, mapping SHA-256, sealed time, and `is_current`.
- Produces tables `agent_dimension_normalization_versions`, `agent_dimension_normalization_entries`, and singleton `agent_dimension_normalization_current`. A version is created unsealed, receives its approved source-to-controlled-enum entries, stores the canonical entry-set SHA-256, is sealed once, and only then may become current. Sealed versions and their entries are append-only; the current pointer may switch only to a sealed version.
- Produces `agent_return_rows_v1` with `normalization_version_id` and controlled `reason_code`/`disposition_code` only. The definer view may compare source text internally, but never projects it; it yields the controlled/fallback mapping for every sealed normalization version so a reader filtering the manifest-owned version ID can replay an old run after the current pointer changes.
- Produces database guards that make every `site_config_versions` row append-only for ordinary accounts after revision `0020`; configuration changes use a new row and a pointer switch, while the existing migration/disaster-recovery bypass identity remains the only controlled escape hatch.

- [ ] **Step 1: Write failing migration and field-exposure tests**

Assert revision `0020` upgrades from `0019`; each of the six views reports `SECURITY_TYPE='DEFINER'`, uses `'clsen_view_definer'@'%'`, resolves on MySQL 8.0/8.4, and exposes only its exact allowlisted columns. Seed canaries in draft rows, raw/parsed source values, order IDs, comments, license plates, notes, configuration `change_reason`/`created_by_user_id`, and audit data; assert every safe view excludes them. Assert `agent_site_config_versions_v1` equals its nine-column allowlist exactly, `agent_return_rows_v1` exposes `normalization_version_id` plus controlled normalization keys rather than arbitrary source text, and a zero-row publication cannot hide the current sealed normalization metadata from its dedicated view. Extend Task-2's real permission test so post-`0020` synchronization gives the reader SELECT on exactly the six views while every base read/write and seventh-object read fails.

```python
def test_safe_views_have_exact_columns(connection) -> None:
    assert view_columns(connection, "agent_return_rows_v1") == {
        "dataset_id", "site_id", "report_date", "version_id", "row_ordinal",
        "return_date", "sku", "asin", "normalization_version_id",
        "reason_code", "disposition_code", "quantity",
    }
    assert view_security(connection, "agent_return_rows_v1") == (
        "clsen_view_definer@%", "DEFINER"
    )
```

- [ ] **Step 2: Write failing append-only configuration tests**

Cover `UPDATE` and `DELETE` rejection for unreferenced, current, import-referenced, published-version-referenced, and Agent-context-referenced configuration rows. For normalization, cover rejection of entry insert after seal, every sealed-version/entry UPDATE or DELETE, pointer-to-unsealed, hash mismatch at seal, and a valid create-entries-seal-switch sequence. Confirm creating a new configuration version plus switching `site_current_configs` still works. Update existing tests to stop deleting or mutating configuration-version rows; do not disable the trigger in cleanup.

- [ ] **Step 3: Run migration tests and observe the missing revision**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_migrations.py backend/tests/integration/test_agent_safe_read_model.py backend/tests/integration/test_agent_site_config_immutability.py --require-mysql -v`

Expected: FAIL because revision `0020`, safe views, normalization tables, and immutable-reference triggers are absent.

- [ ] **Step 4: Implement the minimal safe read model**

Create the tables with explicit keys and immutable version rows. Seed the first normalization version by inserting its entries, computing a canonical ordered entry-set hash, sealing it, and moving the singleton current pointer in one migration-controlled transaction. Create views with `DEFINER='clsen_view_definer'@'%' SQL SECURITY DEFINER`; project site, dataset, report date/type, immutable current and previously published version/row identity, published time, allowed decimal/count fields, return event timestamp, allowed SKU/ASIN, normalization version ID, and controlled dimension keys only. Inside the return view, join each active immutable return row to each sealed normalization version and its entries, mapping missing/unapproved values to controlled fallback enums without projecting source text. Build the published-version catalog from current pointers and immutable publication events so an old snapshot remains readable after replace/rollback/withdraw. Do not expose a base-table generic SELECT surface. Add triggers that enforce normalization sealing/current-pointer invariants and reject all ordinary-account configuration-version UPDATE/DELETE operations; honor only the existing `terminal_write_guard_bypass_accounts` migration/recovery identity where the approved disaster-recovery procedure requires it, and never grant that bypass to app or reader.

```sql
CREATE DEFINER='clsen_view_definer'@'%' SQL SECURITY DEFINER VIEW agent_published_versions_v1 AS
SELECT dataset_id, version_id FROM dataset_publications
UNION DISTINCT
SELECT dataset_id, previous_version_id FROM publication_events WHERE previous_version_id IS NOT NULL
UNION DISTINCT
SELECT dataset_id, next_version_id FROM publication_events WHERE next_version_id IS NOT NULL;
```

- [ ] **Step 5: Verify upgrade, downgrade, view leakage, and guards**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_migration_contract.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_migrations.py backend/tests/integration/test_agent_safe_read_model.py backend/tests/integration/test_agent_site_config_immutability.py backend/tests/integration/test_database_constraints.py --require-mysql -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_reader_permissions.py --require-mysql -v`

Run: `pwsh -File scripts/test-mysql-matrix.ps1`

Expected: PASS on the configured disposable database and MySQL 8.0/8.4 matrix; a clean `upgrade 0019→0020→downgrade 0019→upgrade 0020` round trip preserves the intended schema contracts, post-upgrade synchronization grants exactly six views, and downgrade synchronization returns the reader to zero object grants.

- [ ] **Step 6: Commit the safe database read model**

```powershell
git add backend/alembic/versions/0020_agent_safe_read_model.py backend/tests/contracts/test_migration_contract.py backend/tests/integration/test_migrations.py backend/tests/integration/test_agent_safe_read_model.py backend/tests/integration/test_agent_site_config_immutability.py backend/tests/integration/test_agent_reader_permissions.py backend/tests/integration/test_database_constraints.py backend/tests/integration/test_published_analytics.py backend/tests/integration/test_admin_management_api.py backend/tests/integration/test_parse_workflow.py
git commit -m "feat: add safe published agent read model"
```

### Task 4: Capture a Canonical Consistent Snapshot Manifest

**Files:**
- Create: `backend/app/sites/__init__.py`
- Create: `backend/app/sites/query.py`
- Create: `backend/app/analytics/snapshot_models.py`
- Create: `backend/app/analytics/snapshot_service.py`
- Create: `backend/tests/unit/analytics/test_snapshot_models.py`
- Create: `backend/tests/unit/analytics/test_snapshot_service.py`
- Create: `backend/tests/integration/agent_test_support.py`
- Create: `backend/tests/integration/test_agent_snapshot_capture.py`
- Modify: `backend/app/api/data_calendar.py`
- Modify: `backend/app/analytics/__init__.py`
- Modify: `backend/tests/unit/test_data_calendar.py`

**Interfaces:**
- Consumes: the six Task-3 views through the Task-2 reader engine.
- Produces: `resolve_current_site(session: Session) -> CurrentSiteContext` shared by `/api/data-calendar/site-context` and run creation.
- Produces: `NormalizationReference(version_id: int, mapping_sha256: str, sealed_at: datetime)`, `RunSnapshotManifest`, `ExpectedPublicationCell`, `AgentSnapshotCaptureService.capture(...)`, and `canonical_manifest_sha256(manifest_without_hash: Mapping[str, object]) -> str` as declared in Locked Interfaces.
- Produces: `project_expected_publications(manifest, *, tool_name, from_date, to_date, basis=None) -> tuple[PublicationReference, ...]`; event-date return projection always equals all frozen return candidates.

- [ ] **Step 1: Write failing canonical-model unit tests**

Test inclusive 1-day/366-day acceptance and 367-day rejection, deterministic order and SHA-256 across mapping insertion order, complete `{site, report_type, report_date, currency}` cells, site mismatch rejection, one current sealed normalization version with a matching canonical hash, and subrange projection. Reject absent, multiple-current, unsealed, or hash-mismatched normalization metadata. Assert event-date projection never shrinks even when no row matches.

```python
def test_event_date_projection_never_shrinks(manifest) -> None:
    refs = project_expected_publications(
        manifest, tool_name="return_breakdown", from_date=manifest.from_date,
        to_date=manifest.from_date, basis="event_date",
    )
    assert refs == manifest.event_date_return_candidate_publications
```

- [ ] **Step 2: Write failing transaction-order and concurrency integration tests**

Capture SQL events and assert the dedicated connection first sets `REPEATABLE READ`, then starts a consistent snapshot, then performs only nonlocking reads. With barriers, switch a publication, roll back a pointer, switch current configuration, and seal/switch the normalization pointer between manifest queries; each manifest must be wholly old or wholly new. Assert an out-of-range report date with an in-range return event remains in the candidate universe, and a zero-row dataset still captures normalization metadata from the dedicated view.

- [ ] **Step 3: Run snapshot tests and observe missing types/services**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/analytics/test_snapshot_models.py backend/tests/unit/analytics/test_snapshot_service.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_snapshot_capture.py --require-mysql -v`

Expected: FAIL because the canonical manifest, projector, shared site resolver, and consistent capture service are absent.

- [ ] **Step 4: Implement consistent capture and canonical hashing**

Open a fresh reader connection without an auth or health read, issue the two transaction statements in order, read the one current site/config, one current sealed normalization reference/hash, report-range current-publication grid, and all current published return versions for the site, then commit immediately. Normalize datetimes to UTC, decimal/date/UUID values to documented strings, sort arrays by stable identities, serialize compact UTF-8 JSON, and hash those bytes. Never infer candidate coverage or normalization identity from return rows.

```python
with reader_engine.connect() as connection:
    connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    connection.exec_driver_sql("START TRANSACTION WITH CONSISTENT SNAPSHOT")
    manifest = read_manifest_with_nonlocking_selects(connection, site_id, from_date, to_date)
    connection.commit()
```

- [ ] **Step 5: Run snapshot unit, integration, and existing dashboard tests**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/analytics/test_snapshot_models.py backend/tests/unit/analytics/test_snapshot_service.py backend/tests/unit/test_data_calendar.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_snapshot_capture.py backend/tests/integration/test_published_analytics.py --require-mysql -v`

Expected: PASS; existing dashboard tests retain current-pointer behavior while old Agent manifests remain unchanged.

- [ ] **Step 6: Commit immutable manifest capture**

```powershell
git add backend/app/sites backend/app/api/data_calendar.py backend/app/analytics backend/tests/unit/analytics backend/tests/unit/test_data_calendar.py backend/tests/integration/agent_test_support.py backend/tests/integration/test_agent_snapshot_capture.py
git commit -m "feat: freeze published agent snapshots"
```

### Task 5: Implement Snapshot-Scoped Aggregation and Reference Proofs

**Files:**
- Modify: `backend/app/analytics/snapshot_models.py`
- Modify: `backend/app/analytics/snapshot_service.py`
- Modify: `backend/app/agent_tools/service.py`
- Modify: `backend/app/agent_tools/__init__.py`
- Create: `backend/tests/unit/agent_tools/test_snapshot_tools.py`
- Create: `backend/tests/integration/test_agent_snapshot_analytics.py`
- Modify: `backend/tests/unit/agent_tools/test_service.py`

**Interfaces:**
- Consumes: `RunSnapshotManifest` and `project_expected_publications` from Task 4.
- Produces: `SnapshotScopedAnalyticsQueryService(reader: Connection, manifest: RunSnapshotManifest)` from Locked Interfaces; every method is permanently bound to that one immutable manifest and accepts only a manifest-contained subrange plus closed tool arguments.
- Produces: `ScannedAggregate(rows, total_group_count, truncated, coverage_refs, matching_refs, contributor_refs_by_row)`.
- Produces: `ReadOnlyAgentTools` with exactly three public methods; its constructor now requires a snapshot-scoped reader and a run-wide `ToolBudget`.

- [ ] **Step 1: Write failing aggregate and coverage tests**

Using fixed data, assert Decimal text, integers, null denominator semantics, negative revisions, deterministic product order/ties/top-N, `total_group_count`, and `truncated`. Cover `no_data`, one-report `unavailable`, partial cells, and a published zero. Assert construction without a manifest fails, method calls cannot supply or replace `version_id`, `site_id`, configuration, or another manifest, subranges outside the bound manifest fail, every scanned coverage set equals the independently projected expected refs, and every contributor set is an exactly recomputable subset.

```python
def test_coverage_is_query_proof_not_manifest_echo(reader, manifest) -> None:
    reader.omit_scan_sentinel_for(manifest.report_date_publications[-1])
    with pytest.raises(CoverageMismatch):
        reader.summary(manifest.from_date, manifest.to_date)
```

- [ ] **Step 2: Write failing event-date and frozen-version tests**

Seed several frozen return versions: one matching, one with rows outside the event range, and one with zero active rows. Assert all are coverage, only the first is matching, and row contributors are exact. Exercise DST folds, gaps, and local-midnight boundaries with a safe UTC envelope plus exact IANA local-date recheck. Publish V2 and switch normalization N1→N2 between tool calls; assert the old reader still returns V1 interpreted with N1 while a new manifest uses N2. A missing frozen normalization mapping/hash or deliberately omitted zero-match candidate must raise a safe coverage/version failure.

- [ ] **Step 3: Run focused tests and observe current-pointer leakage**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/agent_tools/test_snapshot_tools.py backend/tests/unit/agent_tools/test_service.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_snapshot_analytics.py --require-mysql -v`

Expected: FAIL because current `ReadOnlyAgentTools` delegates to current-publication DTOs and cannot prove scanned/matching/contributor coverage.

- [ ] **Step 4: Implement version-bound queries and the exact three-tool boundary**

Build every query from manifest-owned publication/configuration/normalization IDs, never Runtime-owned IDs. Explicitly join view rows to an expanding frozen version set, filter `agent_return_rows_v1.normalization_version_id` by the manifest reference, re-check the mapping SHA from the dedicated safe metadata view, and record distinct scanned publication identities from query execution. For event date, scan every candidate, apply the safe UTC prefilter, then exact local-date filtering. Enforce subrange, `limit 1..200`, six attempts including invalid/repeated attempts, 200 returned rows, canonical 256 KiB response, and complete truncation metadata. Do not modify `PublishedAnalyticsQueryService`.

```python
expected = project_expected_publications(manifest, tool_name=tool, **arguments)
result = execute_against_frozen_versions(expected)
if set(result.coverage_refs) != set(expected):
    raise CoverageMismatch
```

- [ ] **Step 5: Verify snapshot tools and dashboard isolation**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/agent_tools -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_snapshot_analytics.py backend/tests/integration/test_published_analytics.py --require-mysql -v`

Expected: PASS, including the public method whitelist `{published_summary, product_performance, return_breakdown}`.

- [ ] **Step 6: Commit snapshot-scoped analytics**

```powershell
git add backend/app/analytics/snapshot_models.py backend/app/analytics/snapshot_service.py backend/app/agent_tools backend/tests/unit/agent_tools backend/tests/integration/test_agent_snapshot_analytics.py
git commit -m "feat: query agent snapshots without pointer drift"
```

### Task 6: Build Privacy Normalization, Canonical Facts, Closed Claims, and Server Rendering

**Files:**
- Create: `backend/app/agent/privacy.py`
- Create: `backend/app/agent/facts.py`
- Create: `backend/app/agent/rendering.py`
- Create: `backend/tests/oracles/__init__.py`
- Create: `backend/tests/oracles/agent_facts.py`
- Create: `backend/tests/fixtures/synthetic/agent-oracle.json`
- Create: `backend/tests/unit/agent/test_privacy.py`
- Create: `backend/tests/unit/agent/test_facts.py`
- Create: `backend/tests/unit/agent/test_rendering.py`
- Create: `backend/tests/integration/test_agent_fact_oracle.py`
- Create: `backend/tests/integration/test_agent_leakage.py`

**Interfaces:**
- Consumes: `ScannedAggregate` results from Task 5.
- Produces: `validate_question(question: str) -> NormalizedQuestion`, `normalize_provider_dimensions(rows, *, snapshot_id, policy) -> tuple[ProviderDimension, ...]`, and `scan_outbound_payload(payload: object) -> None`.
- Produces: immutable `Fact`, `PublicationReference`, `ReferenceSet`, `Claim`, `DisplayPlan`, `RenderedAnswerBlock`, and `RenderedAnswer` types.
- Produces: `build_facts(result, manifest) -> tuple[Fact, ...]`, `build_claims(facts) -> tuple[Claim, ...]`, `validate_display_plan(plan, *, claims, snapshot_id) -> ValidatedDisplayPlan`, and `render_answer(plan, *, claims, role, current_publications) -> RenderedAnswer`; `current_publications` may mark superseded state and choose correction navigation only and must never alter fact, claim, reference, number, date, or coverage validation.

- [ ] **Step 1: Write failing independent-oracle tests**

Hand-code expected facts in `agent-oracle.json` and calculate them in `tests/oracles/agent_facts.py` without importing production aggregation, fact, or tool code. Cover Decimal/count/ratio/null/unit/currency, report/event dates and frozen timezone, zero versus missing, partial data, negative values, tie/truncation, current site, all three reference layers, and data-watermark language.

```python
def test_production_facts_equal_handwritten_oracle(seed_agent_oracle) -> None:
    actual = seed_agent_oracle.run_production_pipeline()
    expected = json.loads(ORACLE_PATH.read_text(encoding="utf-8"))
    assert canonicalize(actual) == expected
```

- [ ] **Step 2: Write failing privacy, injection, and rendering tests**

Test approved ASIN, allowed SKU, stable per-run alias, emails/phones/addresses/order-like long digits/API keys/database URLs/session/CSRF/password rejection, control-character limits, return-dimension enum mapping, unknown-to-hidden behavior, and groups of 1/2 folded into `低频项` without SKU/ASIN while 3 is retained. Inject prompt text, fake tool JSON, SQL, HTML, script, and `javascript:` strings into questions and published fields; assert they remain inert data. Reject a display plan that invents a claim, number, entity, order, link, reference, or causal conclusion.

- [ ] **Step 3: Run oracle/privacy tests and observe missing deterministic layer**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/agent/test_privacy.py backend/tests/unit/agent/test_facts.py backend/tests/unit/agent/test_rendering.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_fact_oracle.py backend/tests/integration/test_agent_leakage.py --require-mysql -v`

Expected: FAIL because privacy normalization, canonical facts/claims, closed rendering, and the independent oracle do not exist.

- [ ] **Step 4: Implement versioned privacy and fact policies**

Create policy constants whose hashes become manifest versions. Serialize money as decimal strings, count as integers, ratios with explicit numerator/denominator and `None` for zero denominators. Enforce `contributor ⊆ matching ⊆ coverage`, bind each claim to one deduplicated reference set, and generate only `metric_value`, `difference`, `ratio`, `rank`, `trend_direction`, `availability`, and `coverage_warning`. Reject completeness-dependent comparisons when the grid is incomplete.

```python
if not contributor_refs <= matching_refs <= coverage_refs:
    raise FactValidationError("publication reference sets are inconsistent")
if coverage_refs != expected_refs:
    raise FactValidationError("coverage is incomplete")
```

- [ ] **Step 5: Implement controlled Chinese templates and links**

Render conclusion, metric card, controlled SVG-series data, limitation, coverage/basis, reference summary, and correction action blocks using claim operands only. For causal questions, render the fixed disclaimer that published aggregates cannot prove cause. Generate only same-origin `/versions?...` and the existing root review-workspace handoff `/?...` from verified IDs; Task 12 adds exact query parsing. Mark old snapshots `superseded` without changing facts; expose create/continue-revision actions only to `admin`/`data_manager` and never execute them on this page.

- [ ] **Step 6: Verify deterministic truth and canary exclusion**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/agent/test_privacy.py backend/tests/unit/agent/test_facts.py backend/tests/unit/agent/test_rendering.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_fact_oracle.py backend/tests/integration/test_agent_leakage.py --require-mysql -v`

Expected: PASS with every oracle field equal; prohibited canaries occur zero times in provider payload candidates, API-safe answers, and captured logs.

- [ ] **Step 7: Commit the deterministic answer authority**

```powershell
git add backend/app/agent/privacy.py backend/app/agent/facts.py backend/app/agent/rendering.py backend/tests/oracles backend/tests/fixtures/synthetic/agent-oracle.json backend/tests/unit/agent backend/tests/integration/test_agent_fact_oracle.py backend/tests/integration/test_agent_leakage.py
git commit -m "feat: render agent answers from verified claims"
```

### Task 7: Add Persistent Run Records, Admission Invariants, HMAC Idempotency, and Retention

**Files:**
- Create: `backend/alembic/versions/0021_agent_runtime_records.py`
- Create: `backend/app/agent/domain.py`
- Create: `backend/app/agent/idempotency.py`
- Create: `backend/app/agent/repository.py`
- Create: `backend/app/agent/service.py`
- Create: `backend/tests/unit/agent/test_domain.py`
- Create: `backend/tests/unit/agent/test_idempotency.py`
- Create: `backend/tests/unit/agent/test_service.py`
- Create: `backend/tests/unit/agent/test_retention.py`
- Create: `backend/tests/integration/test_agent_idempotency.py`
- Create: `backend/tests/integration/test_agent_concurrency.py`
- Create: `backend/tests/integration/test_agent_retention.py`
- Modify: `backend/tests/contracts/test_migration_contract.py`
- Modify: `backend/tests/integration/test_migrations.py`

**Interfaces:**
- Consumes: `AgentSnapshotCaptureService.capture`, Task-1 settings, and the main engine's maintenance barrier.
- Produces revision `0021` with `down_revision = "0020"` and these exact tables: `agent_conversations`, `agent_messages`, `agent_runs`, `agent_run_contexts`, `agent_model_calls`, `agent_tool_calls`, `agent_reference_sets`, `agent_reference_items`, `agent_run_events`, `agent_conversation_active_runs`, `agent_user_active_runs`, `agent_runtime_slots`, `agent_create_rate_events`, `agent_operation_tokens`, `agent_runtime_versions`, `agent_runtime_current`, `agent_kill_switch`, and `agent_daily_usage`. Content tables inherit one immutable conversation `expires_at`; rate/idempotency/usage records carry bounded content-free expiry/partition fields.
- Seeds exactly two numbered runtime-slot rows, an empty `agent_runtime_current` singleton that fails creation closed until an approved runtime version is installed, and one `agent_kill_switch` singleton with `enabled=false`, `hide_existing_answers=false`, `allowed_create_roles=()` as a closed JSON/set value, constrained bootstrap reason, and version 1. Every role-scope change increments the switch version and records actor/time plus a closed rollout reason; downgrade returns to `0020` only after its explicit preflight rejects retained Agent rows rather than silently deleting production content.
- Produces: `canonical_request_hmac(keyring, *, key_version, user_id, operation, request) -> bytes`, `AgentRunService.create_conversation(command) -> AcceptedRun`, `create_run(command) -> AcceptedRun`, and `cleanup_expired(now) -> CleanupResult`.
- Produces: repository compare-and-set methods keyed by `run_id`, `attempt`, sequence, and fencing token; no service method accepts question/answer text as a log field.

- [ ] **Step 1: Write failing schema/state-machine tests**

Assert `0021` upgrades from `0020`, owns exactly the listed tables/singletons, and has an explicit guarded downgrade to `0020`. Test only the transitions `preparing→queued→running→validating→succeeded` plus allowed failure edges; one terminal row/event/answer; terminal immutability; monotonic event sequence; one active conversation run; one active user run; two global slots; a shared six-create rolling-minute counter; empty runtime current, disabled switch, and a role outside the environment/persistent rollout intersection all fail creation closed; every allowed-role scope change is versioned/audited without content; and all Agent main-engine writes acquire the maintenance barrier.

```python
def test_preparing_is_never_claimable(repository, reservation) -> None:
    assert repository.claim_next(worker_id="worker-1") is None
    repository.queue_prepared(reservation.run_id, manifest_hash=b"x" * 32)
    assert repository.claim_next(worker_id="worker-1").run_id == reservation.run_id
```

- [ ] **Step 2: Write failing idempotency and retention tests**

Require RFC UUIDv4, canonical JSON, HMAC-SHA-256 plus stored key version, constant-time comparison, and no bare SHA/question/run ID in a tombstone. Test same-key/same-body concurrent replay, same-key/different-body 409, content deletion followed by 410, key reuse only after 12 months, old-key validation through rotation, and failure when a still-referenced key is removed. With a fake clock, test fixed 30 days, no extension on activity, 10-minute terminal grace, 12-month usage/tombstone deletion, and all-or-nothing content cleanup.

- [ ] **Step 3: Run focused tests and observe missing persistence**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/agent/test_domain.py backend/tests/unit/agent/test_idempotency.py backend/tests/unit/agent/test_service.py backend/tests/unit/agent/test_retention.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_idempotency.py backend/tests/integration/test_agent_concurrency.py backend/tests/integration/test_agent_retention.py --require-mysql -v`

Expected: FAIL because revision `0021`, its exact tables/safe singleton seeds/downgrade, state storage, active pointers, slots, shared rate records, HMAC tombstones, and cleanup do not exist.

- [ ] **Step 4: Implement preparing reservation and compensating snapshot admission**

In one main-engine transaction, validate the persistent/env switches, rate record, operation token, user/conversation active pointers, and a global slot, then create an unclaimable `preparing` run. Capture the Task-4 snapshot on the separate reader connection. In a second main transaction, persist the immutable context/hash and atomically queue it; on any capture/persist timeout or error, CAS the run to failed, append one safe event, release pointers/slot, and bind the idempotent result. Never claim cross-engine atomicity and never expose a `preparing` run as accepted.

```python
reservation = repository.reserve_preparing(command)
try:
    manifest = snapshot_capture.capture(site_id=command.site_id, from_date=command.from_date, to_date=command.to_date)
    return repository.queue_prepared(reservation, manifest)
except BaseException:
    repository.fail_preparing_and_release(reservation, error_code="data_snapshot_unavailable")
    raise
```

- [ ] **Step 5: Implement terminal cleanup, usage, and tombstones**

Make terminal CAS release every active pointer/lease/slot and aggregate confirmed usage exactly once. Clean an expired conversation in one transaction after fencing or force-failing overdue active work. Convert operation records to content-free tombstones before deleting messages, contexts, tool payloads, reference sets, and events. Return uniform not-found for missing, other-owned, expired, or hidden content.

- [ ] **Step 6: Stress the database invariants**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_idempotency.py backend/tests/integration/test_agent_concurrency.py backend/tests/integration/test_agent_retention.py --require-mysql -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_migrations.py --require-mysql -v`

Expected: PASS including a clean `0020→0021→downgrade 0020→upgrade 0021` empty-schema round trip, downgrade preflight refusal when Agent content exists, 20 simultaneous users, competing workers/API replicas, and 50 fixed-seed rounds with no duplicate terminal, leaked pointer/slot, or event gap.

- [ ] **Step 7: Commit persistent run coordination**

```powershell
git add backend/alembic/versions/0021_agent_runtime_records.py backend/app/agent/domain.py backend/app/agent/idempotency.py backend/app/agent/repository.py backend/app/agent/service.py backend/tests/contracts/test_migration_contract.py backend/tests/integration/test_migrations.py backend/tests/unit/agent backend/tests/integration/test_agent_idempotency.py backend/tests/integration/test_agent_concurrency.py backend/tests/integration/test_agent_retention.py
git commit -m "feat: persist bounded agent runs"
```

### Task 8: Expose Owner-Scoped Public Agent APIs and Durable SSE

**Files:**
- Create: `backend/app/api/agent.py`
- Create: `backend/app/api/agent_admin.py`
- Create: `backend/app/api/agent_dependencies.py`
- Create: `backend/app/agent/sse.py`
- Create: `backend/tests/unit/agent/test_api.py`
- Create: `backend/tests/unit/agent/test_sse.py`
- Create: `backend/tests/integration/test_agent_api.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/tests/unit/test_openapi_contract.py`

**Interfaces:**
- Consumes: Task-7 services/repositories, Task-1 settings, the shared current-site resolver, and existing Session/CSRF principals.
- Produces the exact public endpoints in design section 10.1, with cursor pagination fixed at default 50/max 100 conversations, messages, and references.
- Produces strict `CreateAgentRunRequest(question, site_id, from_date, to_date)`, `AgentRunAcceptedResponse`, `AgentRunResponse`, `AgentReferencePageResponse`, `AgentStatusResponse`, and content-free `AgentUsagePageResponse` OpenAPI models.
- Produces `stream_run_events(*, session_factory, owner_user_id, run_id, after, clock) -> AsyncIterator[bytes]`; every poll creates and closes a short Session before yielding or waiting.

- [ ] **Step 1: Write failing auth, ownership, schema, and idempotency API tests**

Cover all three roles under the final full rollout, plus empty/admin-only/admin+manager staged scopes: roles outside the current environment/persistent intersection receive the same stable disabled response without creating a run, while owned-answer reads remain available. Cover unauthenticated 401, missing/invalid CSRF, absent/non-v4 idempotency keys, strict extra-field rejection, 2,000-character and 366-day boundaries, request `site_id` unequal to the freshly resolved current site, 202/replay/409/410/429 plus bounded `Retry-After`, and uniform 404 for other-owned/expired/missing resources. Assert admin usage never contains questions, answers, facts, tools, prompts, or provider errors.

```python
@pytest.mark.parametrize("role", ["admin", "data_manager", "viewer"])
def test_every_authenticated_role_can_create_own_run(agent_client, role) -> None:
    response = agent_client(role).post_run(valid_request(), idempotency_key=uuid4())
    assert response.status_code == 202
```

- [ ] **Step 2: Write failing SSE protocol and connection-lifetime tests**

Test `after=N`, `Last-Event-ID`, equal dual cursors, mismatched dual cursors as 422, LF framing, chunking, replay, duplicate delivery tolerance, multiple subscribers, monotonic IDs without gaps, terminal close, no business payload, keepalive comments without IDs, `Cache-Control: no-cache`, and `X-Accel-Buffering: no`. Instrument the pool to prove zero checked-out connections while the stream waits.

- [ ] **Step 3: Run API/SSE tests and observe missing routers**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/agent/test_api.py backend/tests/unit/agent/test_sse.py backend/tests/unit/test_openapi_contract.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_api.py --require-mysql -v`

Expected: FAIL because public Agent DTOs, routes, and durable SSE do not exist.

- [ ] **Step 4: Implement public routes as thin adapters**

Use `require_csrf_principal` plus explicit three-role authorization for POST and `require_principal` for GET. Re-resolve current site server-side, then require the caller role in `APP_AGENT_CREATE_ROLES ∩ agent_kill_switch.allowed_create_roles` for creation; GET ownership remains independent of rollout scope. Call the Task-7 service; do not put SQL in routes. Fetch run and references by `(resource_id, owner_user_id, expires_at > now)` and honor `hide_existing_answers`. `/api/agent/status` reads persisted heartbeat/switch/scope state without synchronously calling DeepSeek and returns whether this principal may create plus a closed disabled reason; missing Agent dependencies return a stable disabled reason without changing public readiness.

```python
@router.post("/conversations", status_code=status.HTTP_202_ACCEPTED)
def create_conversation(payload: CreateAgentRunRequest, principal=Depends(agent_writer)):
    return service.create_conversation(command_from(payload, principal))
```

- [ ] **Step 5: Implement short-poll durable SSE**

Use `StreamingResponse(media_type="text/event-stream")`. Query a bounded event page in a short Session, close it, yield ordered frames, and await an in-process notification or fake-clock poll interval without a DB connection. Treat GET run as authoritative and never stream model tokens or answer content.

- [ ] **Step 6: Regenerate and verify the public OpenAPI client contract**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/agent/test_api.py backend/tests/unit/agent/test_sse.py backend/tests/unit/test_openapi_contract.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_api.py --require-mysql -v`

Run: `pwsh -File scripts/generate-api-client.ps1`

Run: `pwsh -File scripts/generate-api-client.ps1 -Check`

Expected: backend tests PASS; generation updates `frontend/src/api/generated.ts`, and the immediately repeated check exits 0. Task 12 consumes this committed contract rather than relying on a deliberately failing verification step.

- [ ] **Step 7: Commit public Agent APIs**

```powershell
git add backend/app/api/agent.py backend/app/api/agent_admin.py backend/app/api/agent_dependencies.py backend/app/agent/sse.py backend/app/main.py backend/app/api/dependencies.py backend/tests/unit/agent backend/tests/integration/test_agent_api.py backend/tests/unit/test_openapi_contract.py frontend/src/api/generated.ts
git commit -m "feat: expose durable agent run APIs"
```

### Task 9: Implement the Separate Internal Control Plane, Leases, Fencing, and Recovery

**Files:**
- Create: `backend/app/agent_control/__init__.py`
- Create: `backend/app/agent_control/main.py`
- Create: `backend/app/agent_control/auth.py`
- Create: `backend/app/agent_control/contracts.py`
- Create: `backend/app/agent_control/service.py`
- Create: `backend/app/agent_control/cli.py`
- Create: `backend/tests/unit/agent_control/__init__.py`
- Create: `backend/tests/unit/agent_control/test_auth.py`
- Create: `backend/tests/unit/agent_control/test_protocol.py`
- Create: `backend/tests/unit/agent_control/test_recovery.py`
- Create: `backend/tests/integration/test_agent_runtime_leases.py`
- Modify: `backend/app/deployment/entrypoint.py`
- Modify: `backend/tests/unit/deployment/test_entrypoint.py`

**Interfaces:**
- Consumes: Task-7 repository, Task-5 tools, Task-6 claim validator/renderer, and the persistent kill switch.
- Produces a separate application factory `create_agent_control_app(settings, session_factory, reader_session_factory) -> FastAPI`; do not include this router in `backend/app/main.py`.
- Produces only claim, heartbeat, model-call prepare/dispatch/complete, tool, terminal actions, and read-only `GET /internal/agent/health` under `/internal/agent/*`; all mutations require `run_id`, `attempt`, and `fencing_token`.
- Produces `AgentControlHealthResponse(protocol_version, ready, provider_config_status, runtime_heartbeat_at)` with closed, non-secret status enums only. Health is protected by the internal worker/mTLS identity, performs no provider call, and has no question, prompt, tool, database URL, credential, hostname, or raw exception field.
- Produces lease records shorter than 90 seconds and `KillSwitchSnapshot(enabled, hide_existing_answers, allowed_create_roles, version)` on claim/heartbeat responses.

- [ ] **Step 1: Write failing internal-auth and reachability tests**

Development accepts a constant-time-verified token read from a protected file; server mode refuses bearer identity and trusts only the sidecar's verified Runtime identity header on a private listener. Test that user Sessions/CSRF, anonymous callers, wrong Runtime identity, and attempts to reach business/admin paths are rejected. Test authenticated health returns only the four closed fields, never calls DeepSeek, and reports stale/missing Runtime heartbeat as not ready. Assert the public application OpenAPI and route table contain no `/internal/agent/*` path.

```python
def test_public_app_has_no_internal_routes(public_app) -> None:
    assert not any(route.path.startswith("/internal/agent/") for route in public_app.routes)
```

- [ ] **Step 2: Write failing lease/fencing/model-attempt tests**

Cover competing claimers, heartbeat renewal, stale lease takeover with a higher fencing token, old-token heartbeat/tool/terminal rejection, duplicate/ordered terminal CAS, and cumulative budgets across attempts. Model calls follow `prepare` (known unsent), `dispatch` immediately before HTTP, and `complete` with confirmed usage. Crash a prepared call and allow safe recovery; crash a dispatched call before confirmed usage and require `possible_charge/unknown`, failed run, and zero future provider calls.

- [ ] **Step 3: Write failing kill-switch timing tests with a fake clock**

Check switch version at create (Task 8), claim, heartbeat, model prepare/dispatch, every tool, and answer commit. Advance 5 seconds and assert no new claim; advance to 10 seconds and assert recovery marks every in-flight run `agent_disabled`, discards late provider output, records confirmed usage or possible charge, and permits only terminal cleanup.

- [ ] **Step 4: Run protocol tests and observe missing control application**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/agent_control -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_runtime_leases.py --require-mysql -v`

Expected: FAIL because the separate listener, internal health route, fencing endpoints, and conservative recovery protocol are absent.

- [ ] **Step 5: Implement narrow endpoints and recoverable attempts**

Implement internal health as a bounded local projection of protocol/config validation and persisted Runtime heartbeat; it never performs a synchronous provider or business-data query. Claim only queued or safely recoverable work using a short transaction and fencing increment. Persist `started_at` before dispatch; after `dispatch`, any unconfirmed outcome is conservative possible charge. Retry at most once only for proven-unsent or provider-confirmed-safe transient failures, while preserving run-wide call/token/deadline counters. Tool requests are closed DTOs and are revalidated against the manifest and limits in FastAPI.

```python
prepared = service.prepare_model_call(run_id, attempt, fence, estimate)
service.mark_model_call_dispatched(prepared)
# Any lease expiry before complete_model_call now becomes possible_charge.
```

- [ ] **Step 6: Verify fencing, recovery, and application separation**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/agent_control backend/tests/unit/deployment/test_entrypoint.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_runtime_leases.py backend/tests/integration/test_agent_concurrency.py --require-mysql -v`

Expected: PASS with one terminal/result/usage accumulation, no new provider call after unknown/possible charge, protected content-free internal health, and no internal route on the public listener.

- [ ] **Step 7: Commit the internal control plane**

```powershell
git add backend/app/agent_control backend/app/deployment/entrypoint.py backend/tests/unit/agent_control backend/tests/unit/deployment/test_entrypoint.py backend/tests/integration/test_agent_runtime_leases.py
git commit -m "feat: add fenced agent runtime control plane"
```

### Task 10: Implement the LangChain DeepSeek Runtime as a Bounded Explicit Loop

**Files:**
- Create: `agent_runtime/clsen_agent_runtime/contracts.py`
- Create: `agent_runtime/clsen_agent_runtime/control_client.py`
- Create: `agent_runtime/clsen_agent_runtime/runtime.py`
- Create: `agent_runtime/clsen_agent_runtime/token_budget.py`
- Create: `agent_runtime/clsen_agent_runtime/langchain_deepseek.py`
- Create: `agent_runtime/clsen_agent_runtime/cli.py`
- Create: `agent_runtime/tests/test_control_client.py`
- Create: `agent_runtime/tests/test_tool_loop.py`
- Create: `agent_runtime/tests/test_budget.py`
- Create: `agent_runtime/tests/test_provider_errors.py`
- Create: `agent_runtime/tests/test_prompt_isolation.py`
- Create: `agent_runtime/tests/test_network_guard.py`

**Interfaces:**
- Consumes: Task-9 internal DTOs; it never imports FastAPI repositories, SQLAlchemy, PyMySQL, file-storage, backup, publication, or review packages.
- Produces: `AgentRuntime.run(task: RuntimeTask, control: AgentControlClient) -> RuntimeOutcome` and `LangChainDeepSeekRuntime` implementing it.
- Produces exactly three LangChain tool schemas matching Task-5 names/closed arguments; the control client posts tool calls back to FastAPI.
- Produces a final `DisplayPlan` containing known `claim_id` values and controlled block kinds only.

- [ ] **Step 1: Write failing tool-loop and prompt-isolation tests**

With a scripted fake `BaseChatModel`, assert `bind_tools` receives exactly the three schemas, no `create_agent`/LangGraph path exists, unknown/parallel/extra-argument tools are counted then rejected, and every new `RuntimeTask` message list contains only its system contract, current question/range, and current-run tool results. Test unresolved references such as `那个`, `继续`, and `上一个` are rejected before a model call.

```python
def test_runtime_binds_exactly_three_tools(fake_model, runtime):
    runtime.run(task(), fake_control())
    assert tuple(fake_model.bound_tool_names) == (
        "published_summary", "product_performance", "return_breakdown"
    )
```

- [ ] **Step 2: Write failing budget and deadline tests**

Use fake clock/tokenizer to cover 6 tool attempts, 7 model calls, 32,000 input, 4,096 output, context-window headroom, 256/512 KiB tool payload limits, 64 KiB plan, and the absolute 90-second deadline without sleep. Before each call, count the complete outbound messages and choose the greater of confirmed use and conservative estimate; refuse an uncountable model/tokenizer contract.

- [ ] **Step 3: Write failing provider-outcome tests**

Map provider 401, 429, 5xx, TLS, timeout, disconnect, malformed JSON, unknown tool, looping calls, oversized output, and missing usage to the approved stable error codes without persisting raw errors. Set provider transport retries to zero. For a dispatch with ambiguous disconnect, assert `possible_charge`, unknown usage, no retry, and zero subsequent provider calls.

- [ ] **Step 4: Run Runtime tests and observe missing implementation**

Run: `.\.venv\Scripts\python.exe -m pytest agent_runtime/tests -m "not deepseek_live" -v`

Expected: FAIL because `AgentRuntime`, control client, token budget, and bound DeepSeek loop are absent.

- [ ] **Step 5: Implement `ChatDeepSeek.bind_tools` and the explicit loop**

Instantiate one approved `ChatDeepSeek` with tracing/callback content logging disabled, TLS verification on, fixed deterministic parameters, explicit timeout, and `max_retries=0`. For every model call use Task-9 prepare/dispatch/complete, then either submit one validated tool request and append only its privacy-scanned facts/claims, or return a closed plan. Never form final prose, chart values, references, URLs, or database queries.

```python
model = ChatDeepSeek(model=settings.model_id, api_key=secret, max_retries=0)
bound = model.bind_tools(EXACT_THREE_TOOLS)
for sequence in range(1, settings.max_model_calls + 1):
    outcome = invoke_one_bounded_call(bound, sequence, messages, control, budget)
```

- [ ] **Step 6: Verify Runtime isolation and full offline behavior**

Run: `.\.venv\Scripts\python.exe -m pytest agent_runtime/tests -m "not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m ruff check agent_runtime`

Run: `.\.venv\Scripts\python.exe -m ruff format --check agent_runtime`

Run: `.\.venv\Scripts\python.exe -m mypy agent_runtime/clsen_agent_runtime agent_runtime/tests`

Expected: PASS with the transport guard proving zero real sockets and a package/import scan proving no MySQL or business-storage dependency.

- [ ] **Step 7: Commit the bounded LangChain Runtime**

```powershell
git add agent_runtime
git commit -m "feat: orchestrate DeepSeek with bounded LangChain tools"
```

### Task 11: Finalize Answers, Usage, Price Versions, Alerts, and Kill-Switch Administration

**Files:**
- Modify: `backend/app/agent/repository.py`
- Modify: `backend/app/agent/service.py`
- Modify: `backend/app/agent/rendering.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/db/engine.py`
- Modify: `backend/app/api/agent.py`
- Modify: `backend/app/api/agent_admin.py`
- Create after re-planning: `backend/alembic/versions/<actual-next>_agent_price_versions.py`
- Create: `backend/app/agent/monitoring.py`
- Create: `backend/tests/unit/agent/test_finalization.py`
- Create: `backend/tests/unit/agent/test_usage.py`
- Create: `backend/tests/unit/agent/test_monitoring.py`
- Modify: `backend/tests/unit/db/test_engine.py`
- Create: `backend/tests/unit/test_main.py`
- Create: `backend/tests/integration/test_agent_finalization.py`
- Create: `backend/tests/integration/test_agent_kill_switch.py`
- Modify: `backend/tests/contracts/test_migration_contract.py`
- Modify: `backend/tests/integration/test_migrations.py`

**Interfaces:**
- Consumes: a Task-10 `DisplayPlan` and Task-9 confirmed/unknown/possible-charge call records.
- Produces: `finalize_success(run_id, attempt, fencing_token, display_plan) -> RenderedAnswer` and `finalize_failure(...)`; both are terminal CAS operations.
- Produces a new revision after the actual head at execution time, adding append-only `agent_price_versions` with provider, provider model identity, currency, decimal input/output prices per million tokens, `effective_from`, optional `effective_to`, and uniqueness/nonoverlap guards; Task-7's daily usage rows reference the selected price version when cost is known. The former fixed `0022` reservation is archived: P0 owns `0022`, and this paused plan must be forward-renumbered before implementation without editing P0 or any applied revision.
- Produces content-free daily usage with confirmed cost, unknown count, possible-charge count, normalized failure counts, and warning state.
- Produces `AgentOperationalMetrics.snapshot(window, now) -> AgentMetricsSnapshot`, calculated from bounded content-free run/call/usage/state records: run-duration p50/p95, 90-second timeouts, 429/provider/validator/safe-failure rates, confirmed tokens/cost, unknown/possible-charge counts, superseded-answer rate, cleanup last-success/lag, per-user admission wait/rejection distribution, and configured alert states. No label or sample may contain user ID, site ID, conversation/run ID, question, answer, fact, claim, tool arguments/results, prompt, provider text, or raw exception.
- Produces a main-platform resource comparison record from existing request logs plus SQLAlchemy pool checkout/wait/timeout instrumentation for dashboard, review, and publication route families while Agent is enabled; export is an operator-only JSONL/metrics sink, not a public or admin content API.
- Produces: admin-only persistent switch update with `enabled`, `hide_existing_answers`, `allowed_create_roles`, constrained `reason_code`, actor, time, and version. Allowed roles must be exactly one of the staged closed sets `()`, `(admin)`, `(admin,data_manager)`, or `(admin,data_manager,viewer)` and must remain within the environment ceiling; it stores no free-form incident content.

- [ ] **Step 1: Write failing terminal validation and race tests**

Submit plans with wrong snapshot claims, omitted required reference/coverage warnings, altered order operands, causal blocks, invalid component combinations, and >64 KiB output; assert failure without partial answer. Race two workers, switch disablement, deadline expiry, and success commit; assert exactly one terminal result and only a fully validated answer can win.

```python
def test_deadline_or_disable_wins_over_late_success(service, late_plan) -> None:
    service.disable_agent(reason_code="incident")
    with pytest.raises(StaleFenceOrDisabled):
        service.finalize_success(run_id=1, attempt=1, fencing_token=7, display_plan=late_plan)
    assert service.get_run(1).answer is None
```

- [ ] **Step 2: Write failing usage/price/alert tests**

Assert the allocated revision upgrades from the actual execution-time head and has an explicit downgrade to that predecessor. Test rejection of overlapping ranges and UPDATE/DELETE, effective price lookup at model-call dispatch time, provider-returned model identity recording, exact Decimal cost for confirmed token counts, missing/mismatched/ambiguous price as `unknown` rather than zero, possible charge counted separately, exact-once daily accumulation across duplicate terminal requests, and configurable alert thresholds that never become a spend hard stop. Test the four valid staged role sets, explicit rollback to a narrower set, optimistic version conflicts, rejection of viewer-without-manager/unknown roles, and content-free scope audit. Assert the admin projection has no content fields.

- [ ] **Step 3: Write failing content-free monitoring tests**

With a fake clock and fixed run records, assert exact nearest-rank p50/p95, timeout/error-rate denominators, superseded and cleanup lag semantics, per-user fairness distribution, alert transitions, and main-route pool/error comparison. Insert unique question/answer/tool/prompt/provider/user/site canaries and assert the serialized metric names, labels, samples, logs, and admin DTO contain none. Bound windows/cardinality and reject arbitrary metric labels.

- [ ] **Step 4: Run finalization tests and observe incomplete terminal behavior**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/agent/test_finalization.py backend/tests/unit/agent/test_usage.py backend/tests/unit/agent/test_monitoring.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_finalization.py backend/tests/integration/test_agent_kill_switch.py --require-mysql -v`

Expected: FAIL because the newly allocated Agent revision, validated rendering, price versions, exact-once usage, alerts, and switch administration are not integrated.

- [ ] **Step 5: Implement validated finalization, usage, and operational metrics**

Allocate the next revision only after re-reading the actual Alembic head, with append-only effective-dated price rows and no seed that pretends to know current provider pricing; deployment must explicitly install an approved price version or known cost remains unavailable. At success commit, re-read the switch version and deadline, validate every claim/reference against the run context, render Task-6 templates, store the bounded answer, append `answer_ready`, terminal-CAS the run, release pointers/slot/lease, and aggregate usage once. Select price by the provider-returned model identity and the persisted dispatch timestamp, save its version ID, and mark cost unknown for no exact match. At any uncertainty, store only normalized failure. Build bounded content-free operational projections from persisted timestamps/status/error enums and instrument existing request/pool boundaries with closed route-family/status labels; never log or label content/identifiers. Never store model output or raw provider error.

```python
validated = validate_display_plan(display_plan, claims=claims, snapshot_id=context.snapshot_id)
answer = render_answer(validated, claims=claims, role=owner_role, current_publications=current_refs)
repository.commit_success_and_usage(run, fence, answer, usage)
```

- [ ] **Step 6: Implement switch administration and hiding behavior**

Allow only `admin` to update the singleton switch and staged role scope through CSRF/idempotent service paths. Intersect the persistent scope with the Task-1 environment ceiling at every create/claim checkpoint; scope removal stops new work for removed roles but does not cancel their already-running work unless the whole switch is disabled. Disabling rejects creates/claims and invokes Task-9 recovery. Preserve unexpired answers unless `hide_existing_answers=true`; when hidden, owner reads return the approved unavailable status without deleting evidence needed for incident response.

- [ ] **Step 7: Verify terminal, usage, and monitoring invariants**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/agent/test_finalization.py backend/tests/unit/agent/test_usage.py backend/tests/unit/agent/test_monitoring.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_finalization.py backend/tests/integration/test_agent_kill_switch.py backend/tests/integration/test_agent_concurrency.py --require-mysql -v`

Expected: PASS with no partial answers, duplicate usage, post-disable success commit, content-bearing metric, or unbounded metric label.

- [ ] **Step 8: Commit validated finalization and operations**

```powershell
git add backend/alembic/versions/<actual-next>_agent_price_versions.py backend/app/agent backend/app/main.py backend/app/db/engine.py backend/app/api/agent.py backend/app/api/agent_admin.py backend/tests/contracts/test_migration_contract.py backend/tests/integration/test_migrations.py backend/tests/unit/agent backend/tests/unit/db/test_engine.py backend/tests/unit/test_main.py backend/tests/integration/test_agent_finalization.py backend/tests/integration/test_agent_kill_switch.py
git commit -m "feat: finalize verified agent answers and usage"
```

### Task 12: Add the React `/agent` Workspace, Recoverable SSE Client, and Correction Handoff

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/client.test.ts`
- Regenerate: `frontend/src/api/generated.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/app/App.test.tsx`
- Modify: `frontend/src/features/versions/VersionHistory.tsx`
- Modify: `frontend/src/features/versions/VersionHistory.test.tsx`
- Create: `frontend/src/features/agent/agentTypes.ts`
- Create: `frontend/src/features/agent/agentApi.ts`
- Create: `frontend/src/features/agent/agentEvents.ts`
- Create: `frontend/src/features/agent/agentEvents.test.ts`
- Create: `frontend/src/features/agent/AgentAnalysisPage.tsx`
- Create: `frontend/src/features/agent/AgentAnalysisPage.css`
- Create: `frontend/src/features/agent/AgentAnalysisPage.test.tsx`
- Create: `frontend/tests/e2e/agent-analysis.spec.ts`

**Interfaces:**
- Consumes: Task-8/11 generated OpenAPI DTOs and the current `SiteContextResponse`.
- Produces: `AgentAnalysisPage({principal, siteContext, onCorrectionHandoff})`, available at `/agent` to all three authenticated roles.
- Produces: `subscribeAgentRunEvents({runId, after, signal, onEvent, onReconnect}) -> Promise<void>` using fetch streams, explicit cursor recovery, and per-run maximum event-ID deduplication.
- Produces: `AgentCorrectionTarget(reportDate, reportType, versionId, disposition)` handed to existing root review or `/versions` routes; Agent UI never performs a business write.

- [ ] **Step 1: Write failing client, route, state, and security tests**

Test strict bounded `Retry-After`; LF/CRLF, split chunks, multiline data, duplicate/out-of-order events, abort, and `after=N` reconnect. Test three-role navigation; dates; independent-question warning; queued/running/validating/succeeded/failed/disabled/429; confirmed/unknown/possible-charge display; superseded snapshots; reference paging; pure text; controlled blocks; and no arbitrary HTML/Markdown/link execution.

```tsx
it("deduplicates replayed events and treats GET run as authoritative", async () => {
  transport.emit({ id: 2, type: "validating" });
  transport.emit({ id: 2, type: "validating" });
  transport.emit({ id: 3, type: "answer_ready" });
  expect(await screen.findByText("已对照固定发布数据")).toBeVisible();
  expect(fetchRun).toHaveBeenCalledTimes(1);
});
```

- [ ] **Step 2: Run frontend tests and observe missing `/agent` components**

Run: `pnpm --dir frontend test --run src/api/client.test.ts src/features/agent/agentEvents.test.ts src/features/agent/AgentAnalysisPage.test.tsx src/app/App.test.tsx`

Run: `pnpm --dir frontend test:e2e -- agent-analysis.spec.ts`

Expected: FAIL because Agent UI/API/SSE modules and the route do not exist.

- [ ] **Step 3: Regenerate types and implement API/SSE transport**

Run `pwsh -File scripts/generate-api-client.ps1`, never hand-edit generated types. Parse a bounded integer `Retry-After`. Use same-origin `fetch` plus `ReadableStream`, `after=lastSeen`, credentials, AbortSignal, strict SSE fields, and last-ID update only after a valid event. On terminal progress, close the stream and fetch the authoritative run.

```ts
export async function subscribeAgentRunEvents(
  options: SubscribeAgentRunEventsOptions,
): Promise<void>;
```

- [ ] **Step 4: Implement a data-analysis workspace, not a generic chat renderer**

Reuse the existing application visual language: explicit range/question form, 30-day history, truthful progress, controlled metric cards/SVG chart data, coverage/basis/watermark, and paged references. Render strings as React text and only switch over generated block enums. Add visible keyboard focus, responsive layouts, and reduced-motion support.

```tsx
switch (block.kind) {
  case "metric_card": return <MetricCard block={block} />;
  case "chart": return <ControlledChart block={block} />;
  case "limitation": return <p>{block.text}</p>;
}
```

- [ ] **Step 5: Implement role-safe correction and exact-version handoff**

Parse server-generated `/versions?report_date=...&report_type=...&version_id=...` and root review query parameters in `App.tsx`; pass `initialVersionId` into `VersionHistory`. Viewer gets view/copy/reanalyze only. Manager/admin hand off create/continue review to existing workflows, which remain responsible for edits, notes, validation, and publication.

- [ ] **Step 6: Verify frontend behavior and browser fixture flow**

Run: `pnpm --dir frontend lint`

Run: `pnpm --dir frontend typecheck`

Run: `pnpm --dir frontend test --run`

Run: `pnpm --dir frontend test:e2e -- agent-analysis.spec.ts`

Run: `pnpm --dir frontend build`

Expected: PASS. The Playwright test is labeled fixture/mock API browser E2E and is not reported as FastAPI/MySQL full-stack coverage.

- [ ] **Step 7: Commit the Agent analysis workspace**

```powershell
git add frontend/src frontend/tests/e2e/agent-analysis.spec.ts
git commit -m "feat(frontend): add verified agent analysis workspace"
```

### Task 13: Add Content-Free Administrator Usage and Switch Controls

**Files:**
- Modify: `frontend/src/features/admin/AdminConsole.tsx`
- Modify: `frontend/src/features/admin/AdminConsole.css`
- Modify: `frontend/src/features/admin/AdminConsole.test.tsx`
- Modify: `frontend/src/features/agent/agentApi.ts`

**Interfaces:**
- Consumes: Task-8/11 admin usage and versioned switch endpoints.
- Produces: an admin-only lazy `agent-usage` tab showing date, calls, confirmed token/cost, unknown count, possible-charge count, normalized failure counts, alerts, and switch state.
- Produces: switch/scope changes that require `expected_version`, one of the four closed rollout role sets, a constrained reason code, CSRF, and stable UUIDv4 operation key.

- [ ] **Step 1: Write failing admin projection and optimistic-update tests**

```tsx
it("never renders another user's agent content", async () => {
  render(<AdminConsole principal={admin} />);
  await user.click(screen.getByRole("tab", { name: "Agent 用量" }));
  expect(screen.queryByText(/question-canary|answer-canary|tool-canary/)).toBeNull();
  expect(screen.getByText("可能额外计费 1 次")).toBeVisible();
});
```

Also test non-admin absence, lazy loading, unknown cost not rendered as zero, 409 version refresh, the four closed rollout stages, final viewer enablement, rollback to a narrower stage, disable/hide confirmations, and no free-text incident field.

- [ ] **Step 2: Run the admin test and observe the missing tab**

Run: `pnpm --dir frontend test --run src/features/admin/AdminConsole.test.tsx`

Expected: FAIL because usage and persistent switch controls are absent.

- [ ] **Step 3: Implement the minimal content-free admin tab**

Use only generated admin DTOs. Keep question, answer, tool, provider text, and cross-user links out of component props and DOM. Present only the four server-approved rollout stages, explain that scope affects new runs rather than answer ownership, and require confirmation before adding viewer. Make cost labels explicitly “已确认”, “未知”, and “可能额外计费”, and state that local totals are not the provider bill.

```ts
type AgentUsageView = Pick<AgentDailyUsage, "date" | "calls" | "known_cost" |
  "unknown_count" | "possible_charge_count" | "failure_counts">;
```

- [ ] **Step 4: Verify role and content boundaries**

Run: `pnpm --dir frontend test --run src/features/admin/AdminConsole.test.tsx src/app/App.test.tsx`

Run: `pnpm --dir frontend typecheck`

Expected: PASS with no content-field dependency in the admin feature.

- [ ] **Step 5: Commit admin Agent operations**

```powershell
git add frontend/src/features/admin frontend/src/features/agent/agentApi.ts
git commit -m "feat(frontend): add content-free agent operations"
```

### Task 14: Upgrade Backup Format v2 with Exact Table Classification and Artifact Canary Proofs

**Files:**
- Create: `backend/app/maintenance/data_classification.py`
- Create: `backend/app/maintenance/backup-data-classification.json`
- Modify: `backend/app/maintenance/backup.py`
- Modify: `backend/app/maintenance/restore.py`
- Create: `backend/tests/unit/maintenance/test_data_classification.py`
- Modify: `backend/tests/unit/maintenance/test_backup.py`
- Modify: `backend/tests/unit/maintenance/test_restore.py`
- Create: `backend/tests/integration/test_agent_backup_privacy.py`
- Modify: `backend/tests/integration/test_backup_write_barrier.py`
- Modify: `backend/tests/integration/test_backup_key_rotation.py`
- Modify: `backend/tests/contracts/test_maintenance_scripts.py`
- Modify: `scripts/backup.ps1`
- Modify: `scripts/restore-verify.ps1`

**Interfaces:**
- Produces: `BackupDataMode(INCLUDE, SCHEMA_ONLY)` and `BackupDataClassification.validate_exactly(discovered_tables)`.
- Produces: manifest/catalog format `clsen-local-backup-*-v2` with classification version/SHA and one encrypted `classified_mysql_dump` containing full schema plus data only for allowlisted tables; v1 remains restore-only compatible and unknown versions fail.
- Classifies conversations, messages, runs, contexts, model/tool calls, references, and run events as schema-only; runtime versions, current pointer, daily usage, switch state, and content-free idempotency tombstones are included.

- [ ] **Step 1: Write failing classification, format, and canary tests**

```python
def test_every_application_table_is_classified_exactly_once(discovered_tables):
    classification = load_backup_data_classification(PATH)
    classification.validate_exactly(discovered_tables)
    assert classification.mode("agent_messages") is BackupDataMode.SCHEMA_ONLY
    assert classification.mode("agent_daily_usage") is BackupDataMode.INCLUDE
```

Cover duplicate JSON keys, invalid/missing/extra tables, unknown modes, backup failure before dump on drift, one barrier around classification/manifest/all dumps, v1/v2 dispatch, unknown/duplicate/missing artifacts, and every distinct content-table canary occurring zero times in every decrypted SQL artifact.

- [ ] **Step 2: Run backup tests and observe v1-only assumptions**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/maintenance/test_data_classification.py backend/tests/unit/maintenance/test_backup.py backend/tests/unit/maintenance/test_restore.py backend/tests/contracts/test_maintenance_scripts.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_backup_privacy.py backend/tests/integration/test_backup_write_barrier.py backend/tests/integration/test_backup_key_rotation.py --require-mysql -v`

Expected: FAIL because exact classification and v2 artifacts do not exist.

- [ ] **Step 3: Implement fail-closed classification and one protected snapshot window**

Strictly parse the versioned JSON and enumerate every application base table from `information_schema`. Hold the existing maintenance write barrier for classification, manifest capture, and one `mysqldump --single-transaction` process. Pass one `--ignore-table-data=<db>.<table>` argument for every schema-only table, yielding full schema plus allowlisted data from one real consistent snapshot; do not split schema/data across independent dump sessions.

```python
classification.validate_exactly(discover_application_tables(connection))
arguments = ["--single-transaction", *classification.ignore_table_data_args(database)]
classified_dump = run_one_mysqldump(arguments)
```

- [ ] **Step 4: Implement explicit v2 restoration and decrypted-artifact inspection**

Restore the one classified SQL artifact, then verify Agent content tables exist and are empty while included operational rows and main business data match the manifest. Tests decrypt every SQL artifact (one in v2, potentially different known layouts in v1) into a protected temporary stream/path and scan before deletion; never infer privacy merely from an empty restored table.

- [ ] **Step 5: Verify backup and isolated restoration**

Run the two Step-2 commands again.

Expected: PASS. A real `scripts/restore-verify.ps1` run remains an environment-specific acceptance command and must not be reported as run unless it actually executes against a disposable restore target.

- [ ] **Step 6: Commit classified backup v2**

```powershell
git add backend/app/maintenance backend/tests/unit/maintenance backend/tests/integration/test_agent_backup_privacy.py backend/tests/integration/test_backup_write_barrier.py backend/tests/integration/test_backup_key_rotation.py backend/tests/contracts/test_maintenance_scripts.py scripts/backup.ps1 scripts/restore-verify.ps1
git commit -m "feat(backup): exclude transient agent content"
```

### Task 15: Deploy the Runtime behind mTLS and Deny-by-Default Egress

**Files:**
- Create: `agent_runtime/Dockerfile`
- Create: `ops/nginx/agent-internal.conf`
- Create: `ops/egress/squid.conf`
- Create: `ops/bootstrap-agent-secrets.ps1`
- Create: `ops/rotate-agent-certificates.ps1`
- Modify: `ops/bootstrap-secrets.ps1`
- Modify: `ops/docker-compose.yml`
- Modify: `ops/nginx/default.conf`
- Modify: `ops/nginx/verification.conf`
- Modify: `ops/verify-deployment.ps1`
- Modify: `backend/app/deployment/entrypoint.py`
- Create: `backend/tests/contracts/test_agent_deployment.py`
- Create: `backend/tests/integration/test_agent_container_smoke.py`
- Create: `backend/tests/integration/test_agent_network_isolation.py`
- Modify: `backend/tests/contracts/test_server_deployment.py`
- Modify: `backend/tests/unit/deployment/test_entrypoint.py`
- Modify: `.env.example`

**Interfaces:**
- Produces `agent-runtime`, `agent-internal`, and `agent-egress-proxy` services; Runtime joins only internal `agent_control`/`agent_egress`, while the proxy is the only service with external uplink.
- Produces a backend-side control listener reachable only through the mTLS sidecar; Runtime cannot address public backend or the MySQL `data` network directly.
- Produces a minimal Runtime image containing only `agent_runtime`, its locked dependencies, CA/cert/key files, and DeepSeek secret file; it contains no MySQL client/package or application content.
- Produces a precise Nginx public SSE location with buffering/cache off and a read timeout longer than the 90-second run deadline; edge explicitly rejects `/internal/agent/*`.

- [ ] **Step 1: Write failing topology, image, mTLS, readiness, and egress tests**

```python
def test_runtime_has_no_database_or_content_capability(compose):
    runtime = compose["services"]["agent-runtime"]
    assert "data" not in runtime["networks"]
    assert not any("MYSQL" in key or "DATABASE_URL" in key for key in runtime["environment"])
    assert runtime["read_only"] is True
    assert "/var/lib/clsen" not in repr(runtime.get("volumes", []))
```

Also test no/wrong/expired Runtime client certificate, controlled old/new certificate overlap then revocation, edge route absence, authenticated internal health reachability through the sidecar, health payload field allowlist, Runtime/mTLS/proxy/DeepSeek faults disabling only Agent, and public readiness remaining 200.

- [ ] **Step 2: Run deployment contracts and observe missing topology**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_agent_deployment.py backend/tests/contracts/test_server_deployment.py backend/tests/unit/deployment/test_entrypoint.py -m "not mysql and not deepseek_live" -v`

Expected: FAIL because Runtime services, mTLS identity, egress proxy, and SSE exceptions do not exist.

- [ ] **Step 3: Implement the minimal image and non-bypassable internal topology**

Build from a whitelist COPY, install only `agent_runtime/requirements.lock`, run as non-root with read-only root/cap-drop/no-new-privileges, and mount secrets read-only. Put Runtime on internal networks with no default Internet route. Ensure it can resolve only the mTLS sidecar and egress proxy; the sidecar allowlists only Task-9 paths and reaches the separate control listener over a backend-only network.

```yaml
agent-runtime:
  networks: [agent_control, agent_egress]
agent-egress-proxy:
  networks: [agent_egress, external_uplink]
```

- [ ] **Step 4: Implement mTLS lifecycle, proxy allowlist, SSE routing, and safe health**

Use a dedicated CA and short-lived server/client certificates in Docker Secrets. Route only the authenticated `GET /internal/agent/health` and Task-9 action paths through the internal sidecar, while edge rejects all internal paths. Configure Squid to allow CONNECT only to the approved DeepSeek host on 443, deny IP literals/private/link-local/loopback/host gateway and all other traffic, and revalidate redirect destinations. Keep LangChain tracing false. Do not make Runtime health a public backend `depends_on` startup condition or part of `/api/health/ready`.

- [ ] **Step 5: Run container smoke and actual negative network probes**

Run: `docker compose -f ops/docker-compose.yml config --quiet`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_agent_container_smoke.py backend/tests/integration/test_agent_network_isolation.py -v`

Expected: PASS using real FastAPI, disposable MySQL, and stub Runtime. From the Runtime container, approved proxied host succeeds; another domain, direct IP, RFC1918, loopback, host gateway, non-443, and redirect target fail. No probe uses production data or key.

- [ ] **Step 6: Extend the protected deployment drill**

Make `ops/verify-deployment.ps1` verify reader grants/definer resolution, Runtime isolation, SSE, log canaries, switch disable within 5 seconds, in-flight terminal within 10 seconds, hide/reopen, and separate failure injection for Runtime/mTLS/proxy/DeepSeek while public readiness remains healthy.

- [ ] **Step 7: Commit isolated deployment**

```powershell
git add agent_runtime/Dockerfile ops backend/app/deployment/entrypoint.py backend/tests/contracts/test_agent_deployment.py backend/tests/contracts/test_server_deployment.py backend/tests/unit/deployment/test_entrypoint.py backend/tests/integration/test_agent_container_smoke.py backend/tests/integration/test_agent_network_isolation.py .env.example
git commit -m "feat(ops): isolate agent runtime and egress"
```

### Task 16: Enforce Offline CI, MySQL 8.0/8.4 Coverage, and Explicit DeepSeek Live Smoke

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/security/test_agent_no_network.py`
- Create: `backend/tests/contracts/test_agent_ci.py`
- Create: `backend/tests/live/test_deepseek_agent_smoke.py`
- Create: `backend/tests/fixtures/synthetic/agent-evaluation.json`
- Create: `docs/operations/agent-evaluation-rubric.md`
- Create: `backend/tests/contracts/test_agent_evaluation_assets.py`
- Create: `.github/workflows/deepseek-live.yml`
- Create: `ops/verify-agent-live.ps1`
- Modify: `.github/workflows/compatibility.yml`
- Modify: `scripts/test-mysql-matrix.ps1`

**Interfaces:**
- Consumes: Task-1 marker/guard and all Agent suites.
- Produces a manual/protected live workflow requiring `@pytest.mark.deepseek_live` plus `--run-deepseek-live`, `DEEPSEEK_API_KEY_FILE`, and a versioned synthetic fixture; it does not load `.env` or connect to a business database.
- Produces content-free live evidence: fixture SHA, provider-returned model ID, observed tool names, normalized outcome, usage/charge status, and version hashes.
- Produces a separate versioned synthetic evaluation set and fixed human rubric. Before a larger evaluation starts, product/data owners record the question-set SHA, prompt/tool/model versions, repetition count, raw denominator, per-risk-category zero-tolerance gates, and a usability threshold; two reviewers independently score claim selection completeness/relevance and rendered-template readability, then a named arbitrator resolves disagreements. LLM-as-judge may annotate but cannot replace either human score.

- [ ] **Step 1: Write failing CI and live-gate contract tests**

```python
def test_ordinary_jobs_explicitly_exclude_live(workflow):
    commands = workflow.pytest_commands()
    assert all('not deepseek_live' in command for command in commands)
    assert all('not mysql' in command for command in workflow.offline_pytest_commands())
```

Test that merely setting a key never enables live tests; the CLI option cannot grant network to an unmarked test; MySQL jobs allow only validated disposable DB connections; both database versions provision/synchronize reader/definer and explicitly run snapshot, permission, concurrency, backup, and control-plane files. Validate evaluation fixture/rubric schema, required two reviewer identities plus arbitrator, pre-registered threshold timestamp before results, raw denominators, normalized safe-failure categories, and zero-tolerance fields for wrong number/version/reference/access/leakage. Assert the container job probes authenticated internal health and proves an Agent dependency failure leaves public readiness healthy. Assert every ordinary CI path runs both `backend/tests` and the independent `agent_runtime/tests` suite, and type-checks both packages.

- [ ] **Step 2: Run CI contracts and the complete offline suite**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_agent_ci.py backend/tests/security/test_agent_no_network.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests -m "not mysql and not deepseek_live"`

Run: `.\.venv\Scripts\python.exe -m pytest agent_runtime/tests -m "not deepseek_live"`

Run: `.\.venv\Scripts\python.exe -m mypy --config-file backend/pyproject.toml backend/app backend/tests`

Run: `.\.venv\Scripts\python.exe -m mypy agent_runtime/clsen_agent_runtime agent_runtime/tests`

Expected: initial contract FAIL until workflow/matrix updates are present; after implementation backend and Runtime tests/type checks PASS without external sockets.

- [ ] **Step 3: Implement explicit MySQL and container jobs**

Update every ordinary command to exclude both inapplicable markers. Generate ephemeral definer/reader identities, perform pre/post migration sync, and list Agent MySQL suites explicitly. Run Task-15 container smoke with stub Runtime and no DeepSeek key.

- [ ] **Step 4: Implement the bounded live synthetic harness**

Ask three fixed synthetic questions and require observation of each tool at least once, plus one multi-tool question. Allow at most two fixed attempts only when the expected tool was not selected; unknown usage or possible charge stops immediately. Validate bound tools, structured plan, deadline/budget, SSE contract, and no content logging; do not golden-test natural model output. Keep the larger evaluation as a separate protected procedure over `agent-evaluation.json`: store only synthetic question IDs, version hashes, repetitions, normalized outcomes, raw counts, two blinded rubric scores, disagreements, and arbitration—not model prose or any production content.

```powershell
python -m pytest backend/tests/live/test_deepseek_agent_smoke.py `
  -m deepseek_live --run-deepseek-live
```

- [ ] **Step 5: Verify offline and matrix gates**

Run: `pwsh -File scripts/test-mysql-matrix.ps1`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/live/test_deepseek_agent_smoke.py --collect-only`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_agent_evaluation_assets.py -m "not mysql and not deepseek_live" -v`

Expected: MySQL 8.0/8.4 PASS; live tests collect but remain skipped without both gates. The actual live command runs only in the protected target environment and is not claimed successful here.

- [ ] **Step 6: Commit explicit test gates**

```powershell
git add backend/pyproject.toml backend/tests/conftest.py backend/tests/security backend/tests/contracts/test_agent_ci.py backend/tests/contracts/test_agent_evaluation_assets.py backend/tests/live backend/tests/fixtures/synthetic/agent-evaluation.json docs/operations/agent-evaluation-rubric.md .github/workflows ops/verify-agent-live.ps1 scripts/test-mysql-matrix.ps1
git commit -m "test(agent): enforce offline and live provider gates"
```

### Task 17: Add Target-Environment Performance Acceptance and Release Evidence

**Files:**
- Create: `tools/agent_performance.py`
- Create: `backend/tests/unit/performance/__init__.py`
- Create: `backend/tests/unit/performance/test_agent_acceptance.py`
- Create: `ops/verify-agent-performance.ps1`
- Create: `backend/tests/contracts/test_agent_release_evidence.py`

**Interfaces:**
- Produces a formal mode locked to 120-second warmup, 600-second measurement, 3 rounds per scenario, 20 continuous viewers, one repeatable publisher, and global Agent concurrency 2.
- Produces per-request JSONL samples and a content-free manifest with environment, image digest, fixture SHA, versions, error counts, and per-round/type p95; it compares the median of three p95 values.
- Pass condition for each existing business request type is zero 5xx/pool timeout/oracle/publish error and candidate p95 both `<= baseline × 1.25` and `<= 2.0 seconds`.

- [ ] **Step 1: Write failing statistics, protocol, and safety tests**

```python
def test_gate_uses_median_round_p95_and_both_thresholds():
    baseline = [0.8, 1.0, 1.2]
    assert evaluate(baseline, [0.9, 1.1, 1.24]).passed
    assert not evaluate(baseline, [1.3, 1.3, 1.3]).passed
    assert not evaluate([1.9, 1.9, 1.9], [2.01, 2.01, 2.01]).passed
```

Test rejection of non-HTTPS/unknown/production targets, missing CA, mutable image tags, nonempty output, non-synthetic fixture, reduced formal durations, missing raw samples, and business content in evidence.

- [ ] **Step 2: Run performance unit/contracts and observe missing harness**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/performance/test_agent_acceptance.py backend/tests/contracts/test_agent_release_evidence.py -m "not mysql and not deepseek_live" -v`

Expected: FAIL because the dedicated acceptance harness and evidence schema are absent.

- [ ] **Step 3: Implement deterministic sample collection and gates**

Run disabled baseline first, then enabled Agent scenario against the same HTTPS URI/image/fixture/request mix in the same acceptance window. Warm before collecting. Save every non-warmup sample with UTC timestamp, round, scenario, request type, latency, HTTP/error, but no question/answer. Calculate nearest-rank p95 per type/round, then median across three rounds.

- [ ] **Step 4: Implement protected PowerShell orchestration**

Require explicit CA, pinned `sha256:` image digest, new empty output directory, synthetic fixture, and acceptance-environment marker. Formal evidence cannot lower timings/counts; a separately labeled test mode may shorten them but can never produce a production-pass manifest.

```powershell
pwsh ./ops/verify-agent-performance.ps1 -WarmupSeconds 120 `
  -MeasureSeconds 600 -Rounds 3 -ViewerCount 20 -AgentConcurrency 2
```

- [ ] **Step 5: Verify the harness without claiming target performance**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/performance/test_agent_acceptance.py backend/tests/contracts/test_agent_release_evidence.py -m "not mysql and not deepseek_live" -v`

Expected: PASS for deterministic unit/contract fixtures. The formal PowerShell command is run and reported only on the target server; existing correctness load tests are never used as performance evidence.

- [ ] **Step 6: Commit target acceptance tooling**

```powershell
git add tools/agent_performance.py backend/tests/unit/performance backend/tests/contracts/test_agent_release_evidence.py ops/verify-agent-performance.ps1
git commit -m "test(agent): add target performance acceptance"
```

### Task 18: Document User Boundaries, Operations, Incident Response, and Final Gates

**Files:**
- Create: `docs/user-guide/agent-analysis.md`
- Create: `docs/operations/agent-runtime.md`
- Create: `docs/operations/agent-release-gates.md`
- Modify: `docs/user-guide/dashboard.md`
- Modify: `docs/user-guide/import-review.md`
- Modify: `docs/operations/local-maintenance.md`
- Modify: `docs/operations/authentication.md`
- Modify: `ops/DEPLOYMENT.md`
- Create: `backend/tests/contracts/test_agent_release_docs.py`

**Interfaces:**
- Produces one user guide for the frozen-published-data limitation, independent questions, provider data warning, 30-day retention, statuses, references, superseded reruns, and role-specific correction workflow.
- Produces one operator guide for configuration, price versions, metrics, mTLS/secret/HMAC/cert rotation, reader/definer verification, proxy tests, cleanup, backup v2, switch/hide, incident response, recovery, image rollback, and readiness isolation.
- Produces one release checklist mapping every design section-17 gate to an exact command/evidence artifact, requiring owner sign-off for current DeepSeek retention/training/region terms, and requiring the pre-registered human-evaluation threshold, two blinded reviewer records, disagreement arbitration, raw denominators, and zero-tolerance safety result.

- [ ] **Step 1: Write failing documentation-contract tests**

```python
def test_release_checklist_names_every_external_gate():
    text = RELEASE_GATES.read_text(encoding="utf-8")
    for phrase in ("DeepSeek 条款", "mTLS", "出站代理", "备份 canary",
                   "kill switch", "20 viewer", "镜像 digest"):
        assert phrase in text
```

Also require exact offline/MySQL/container/live/performance/evaluation commands, explicit “not absolute truth”, “not a billing total”, no invented provider policy, no claimed test/performance result, two human reviewers plus arbitrator, a threshold timestamp earlier than evaluation results, and production default disabled.

- [ ] **Step 2: Run documentation contracts and observe missing guides**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_agent_release_docs.py -m "not mysql and not deepseek_live" -v`

Expected: FAIL because the guides/checklist do not exist.

- [ ] **Step 3: Write user and operator guides from verified contracts**

Document that Agent reads only a frozen published snapshot and cannot establish real-world truth or write data. Explain each question is independent, cloud processing boundaries, privacy caveat for group threshold 3, fixed retention, reference inspection, viewer contact flow, and manager/admin create-revision→review→validate→publish flow. Document the recorded rollout sequence `disabled → admin → admin+data_manager → all three roles`, the observation evidence required before adding viewer, final viewer E2E, safe rollback to a narrower create scope, and that scope changes never expand answer ownership.

- [ ] **Step 4: Write disable/recovery and release-evidence procedures**

Give exact safe commands/queries for status, persisted disable/hide, in-flight observation, restoration, HMAC/cert/key rotation, backup/restore canary, synthetic live, protected human evaluation, formal performance, and rollback. Define the two-reviewer blinded rubric, threshold preregistration, disagreement arbitration, raw denominator/failure categories, and zero-tolerance wrong-number/version/reference/access/leakage gates. Require content-free evidence only. State that missing proxy, incomplete human evaluation, or unconfirmed provider terms means code may be deployed but Agent stays disabled.

- [ ] **Step 5: Run final deterministic quality gates**

Run: `.\.venv\Scripts\python.exe -m ruff check backend agent_runtime`

Run: `.\.venv\Scripts\python.exe -m ruff format --check backend agent_runtime`

Run: `.\.venv\Scripts\python.exe -m mypy --config-file backend/pyproject.toml backend/app backend/tests`

Run: `.\.venv\Scripts\python.exe -m mypy agent_runtime/clsen_agent_runtime agent_runtime/tests`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests -m "not mysql and not deepseek_live"`

Run: `.\.venv\Scripts\python.exe -m pytest agent_runtime/tests -m "not deepseek_live"`

Run: `pnpm --dir frontend lint`

Run: `pnpm --dir frontend typecheck`

Run: `pnpm --dir frontend test --run`

Run: `pnpm --dir frontend build`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_agent_release_docs.py -m "not mysql and not deepseek_live" -v`

Expected: PASS. MySQL matrix, container isolation, backup restore, live DeepSeek, and formal target performance remain separately recorded gates and must not be claimed by these commands.

- [ ] **Step 6: Commit documentation and final gate mapping**

```powershell
git add docs ops/DEPLOYMENT.md backend/tests/contracts/test_agent_release_docs.py
git commit -m "docs: add agent operation and release guides"
```

## Implementation Completion Checklist

- [ ] Execute Tasks 1–18 in order, allowing only tests within a task to drive implementation; never edit an already applied migration.
- [ ] Confirm every ordinary test run blocks external network and excludes `deepseek_live` explicitly.
- [ ] Confirm MySQL 8.0 and 8.4 evidence covers fixed-definer views, exact reader grants, snapshots, tools, state/fencing, backup privacy, and concurrency.
- [ ] Confirm final API answers equal the independent oracle field by field and all prohibited-content/log canaries occur zero times.
- [ ] Confirm Runtime image/control/egress tests demonstrate no database, content volume, business API, direct Internet, or edge-internal path.
- [ ] Confirm target-environment provider terms, synthetic live smoke, kill-switch drill, backup restore, and formal performance evidence before enabling production.
- [ ] Keep production `APP_AGENT_ENABLED=false` if any external or acceptance gate lacks current evidence.
