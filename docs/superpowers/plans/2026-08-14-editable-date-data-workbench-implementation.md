# Editable Date Data Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the date route a table-first workspace where uploaded CSV data opens directly, every original column is versioned, standard and extension cells can be edited with optimistic autosave and undo, and published history is revised without in-place overwrite.

**Architecture:** Keep immutable raw files, parse baselines, typed report rows, draft pointers, validation, and publication pointers as the authority. Add a versioned table schema and sparse extension-cell snapshot beside the existing typed rows, expose a task-oriented workbench service/API, and let one idempotent import orchestration command advance only conflict-free uploads. React consumes that aggregate API and keeps unsaved editor state locally while every accepted value and undo is persisted as an append-only event.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy Core, Alembic, MySQL 8.0/8.4, Pydantic, React 19, TypeScript 5.9, Vitest, Playwright, pnpm.

## Implementation status (2026-08-14)

- Tasks 1-8: implemented. Dynamic columns, immutable snapshots, aggregate reads,
  optimistic standard/extension edits, undo/history, first-edit revisions, resumable
  import orchestration, structured duplicates, and candidate-date isolation are in
  place.
- Tasks 9-10: implemented in the date workbench. The generated client, table-first
  routes, direct CSV upload, recognition confirmation, autosave, undo, published
  revision entry, and same-page advanced validation/publication handoff are wired.
- Task 11: backend calendar ownership and responsive workbench behavior are covered;
  the existing strict-mock frontend suite passes. The disposable test database
  runtime and backup grants were synchronized from privilege manifest v5, and the
  runtime-account materialization/publication plus calendar isolation checks pass.
  A live browser E2E against the migrated local application database also passes:
  de-identified batch 45 opened dataset 12/version 13 for 2026-08-13 with all 22
  original columns and 2 rows; an edited title survived refresh, undo appended a
  `restore_previous` event and survived a second refresh, complete validation
  reported 0 blockers/0 warnings, and publication v1 rendered read-only without
  upload or write controls.
- Task 12: source gates pass (714 backend non-MySQL tests with 268 expected skips,
  95 frontend tests, Ruff, mypy, lint, typecheck, and production build). Focused
  MySQL workbench, orchestration, revision, and calendar tests pass. Full migration
  replay is pending
  an empty disposable MySQL database because the configured test database contains
  retained stage-6 demo versions and revision 0020 correctly refuses destructive
  downgrade when workbench rows exist. After synchronizing manifest v5 grants,
  12 focused MySQL checks passed: 6 workbench snapshot/import-orchestration checks,
  5 runtime-account draft/publication/calendar checks, and 1 viewer least-privilege
  check. The frontend suite passes all 95 tests. The live primary-database
  upload found and fixed a locking read against the immutable workbench operation
  token ledger; its regression test now proves the least-privilege runtime account
  can register, complete, and recover import operations without `UPDATE` permission.
  The primary database is now at revision 0020, and the authenticated browser flow
  completed upload, edit, undo, refresh, validation, publication, and viewer-style
  read-only verification without deleting business data or raw-file evidence.
- Follow-up UI containment verification reset the local primary business data only
  after encrypted backup `4a024703d60544f9b054f036681c53e6`; accounts, sessions,
  configuration, schema, and maintenance evidence were retained. Fresh de-identified
  batch 47 recreated a 22-column, 2-row draft. Every data column now has a stable
  180px boundary, clipped overflow, horizontal table scrolling, and full-value hover
  text. A 570px title edit survived refresh, stayed inside its cell, and undo restored
  the original value after another refresh.

## Global Constraints

- Never mutate immutable raw files, parsed source rows, parse baselines, sealed dataset versions, or append-only audit ledgers.
- Only current publication pointers feed the home ledger and analytics queries.
- Full tables are server-paginated; a browser request returns at most 100 rows and never downloads the whole CSV for editing.
- Original header text and order are preserved. Duplicate CSV headers remain a blocking parse error.
- A column mapped to a standard field writes the existing typed row; an unmapped column writes the extension-cell snapshot and never changes analytics.
- Every cell write carries the dataset/version head and the cell revision. Conflicts return the current server value without discarding user input.
- Undo appends a compensating change event; it never deletes or rewrites history.
- Automatic import orchestration stops at recognition confirmation, merge/replace decisions, or any active-draft/publication conflict.
- Admin and data_manager can edit and publish ordinary drafts; viewer access is read-only and never exposes draft/internal evidence.
- Do not stage or commit while the pre-existing ledger-home work remains uncommitted and overlaps the same frontend files. Use `git status --short` and `git diff --check` as checkpoints.

---

### Task 1: Migration and least-privilege contracts

**Files:**
- Create: `backend/alembic/versions/0020_editable_workbench_tables.py`
- Modify: `scripts/database-privileges.json`
- Modify: `backend/tests/contracts/test_migration_contract.py`
- Modify: `backend/tests/contracts/test_database_bootstrap_script.py`
- Modify: `backend/tests/integration/test_migrations.py`

**Interfaces:**
- Produces `version_table_columns(version_id, column_id, source_header, display_order, value_kind, standard_field_name, is_key, participates_in_statistics)`.
- Produces `version_extension_cells(version_id, row_id, column_id, base_value, current_value, cell_revision)`.
- Produces append-only `extension_cell_changes` and idempotent `workbench_operation_tokens/results`.
- Produces candidate ownership on `import_batches`: `candidate_report_date`; the legacy non-null `report_date` remains compatibility metadata, while `confirmed_at` plus `confirmed_report_type` are the only calendar-ownership signal.

- [ ] Add contract tests that expect revision `0020`, the five new tables, their unique/FK/check constraints, terminal-version mutation guards, and runtime privileges.
- [ ] Run `python -m pytest backend/tests/contracts/test_migration_contract.py backend/tests/contracts/test_database_bootstrap_script.py -q` and confirm the new expectations fail.
- [ ] Implement the `0020` migration with `utf8mb4`, bigint IDs, `BINARY(16)` column IDs, immutable append-only ledgers, and a downgrade refusal when workbench rows exist.
- [ ] Grant runtime `SELECT/INSERT` to append-only ledgers, `SELECT/INSERT/UPDATE` to extension snapshots and import orchestration state, and no runtime `DELETE` for historical cell data.
- [ ] Update migration head/order tests from `0019` to `0020` and verify offline DDL plus a disposable-MySQL upgrade when enabled.
- [ ] Run the contract tests and `git diff --check`.

### Task 2: Dynamic column domain and schema composition

**Files:**
- Create: `backend/app/workbench/__init__.py`
- Create: `backend/app/workbench/types.py`
- Create: `backend/app/workbench/schema.py`
- Test: `backend/tests/unit/workbench/test_schema.py`

**Interfaces:**
- Produces `TableColumn`, `TableSchema`, `ExtensionCellValue`, and `compose_table_schema(report_type, headers_and_mappings)`.
- `column_id` is UUIDv5 over report type plus the exact NFC-normalized header, so the same source column survives revisions and merge unions.
- `standard_field_name` is optional and must resolve through `get_report_field_contract(report_type)`.

- [ ] Write tests for exact source order, first-seen union order, deterministic IDs, standard-field mapping, key/statistics flags, Unicode normalization, and duplicate-header rejection.
- [ ] Run `python -m pytest backend/tests/unit/workbench/test_schema.py -q` and confirm the module is missing.
- [ ] Implement frozen dataclasses with strict validation and pure schema composition.
- [ ] Run the schema tests and Ruff/mypy on `backend/app/workbench backend/tests/unit/workbench`.

### Task 3: Persist schema and extension snapshots during version creation

**Files:**
- Create: `backend/app/workbench/repository.py`
- Modify: `backend/app/datasets/repository.py`
- Modify: `backend/app/publications/repository.py`
- Test: `backend/tests/unit/workbench/test_repository.py`
- Test: `backend/tests/integration/test_workbench_snapshots.py`

**Interfaces:**
- Produces `MySqlWorkbenchSnapshotRepository.materialize_from_baseline(connection, version_id, baseline_id, report_type)`.
- Produces `copy_from_parents(connection, version_id, parent_version_ids, row_lineage)` for revisions, merges, replacements, date moves, and rollbacks.
- Existing dataset/publication transactions call these methods before exposing the new draft/version pointer.

- [ ] Add repository SQL tests proving all original columns are read from parse-attempt field mappings and `parsed_source_rows.decoded_fields` without changing source evidence.
- [ ] Add MySQL tests for baseline materialization, multi-source first-seen union, missing sparse cells, parent revision copy, and rollback/date-move preservation.
- [ ] Implement schema and sparse extension snapshot insertion in the same transaction as typed version rows.
- [ ] Add terminal-version guards so extension snapshots can change only while the owning version is the active editable draft.
- [ ] Run workbench snapshot unit/integration tests and existing dataset/publication transaction tests.

### Task 4: Aggregate date workbench read model

**Files:**
- Create: `backend/app/workbench/queries.py`
- Create: `backend/app/api/workbench.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/unit/workbench/test_queries.py`
- Test: `backend/tests/unit/test_workbench_api.py`

**Interfaces:**
- Produces `GET /api/workbench/dates/{report_date}` for both writable and viewer roles.
- Query parameters: `report_type`, `page` (>=1), `page_size` (1..100), `search`, `sort_column_id`, `direction`, `changed_only`.
- Response includes both report tabs, selected source (`draft`, `published`, or `empty`), exact version head, ordered columns, paginated rows, validation summary, permissions, and allowed actions.
- Viewer responses select only current published versions and omit source/internal history.

- [ ] Write response-model and permission tests for empty, draft, published, partial report-day, viewer, and stale-version cases.
- [ ] Write query tests that combine typed and extension cells in schema order and sort/search safely through allow-listed column IDs.
- [ ] Implement the read service with one database session and bounded pagination.
- [ ] Register the router and add the endpoint to the OpenAPI contract test.
- [ ] Run the workbench query/API tests and existing authentication negative tests.

### Task 5: Optimistic standard and extension cell writes

**Files:**
- Create: `backend/app/workbench/commands.py`
- Create: `backend/app/workbench/service.py`
- Modify: `backend/app/workbench/repository.py`
- Modify: `backend/app/api/workbench.py`
- Test: `backend/tests/unit/workbench/test_commands.py`
- Test: `backend/tests/integration/test_workbench_cell_edits.py`

**Interfaces:**
- Produces `PATCH /api/workbench/versions/{version_id}/rows/{row_id}/cells/{column_id}`.
- Request includes `{value, reason, expected_data_revision, expected_cell_revision}` plus `Idempotency-Key`.
- Success returns `{head, cell}`. Conflict returns HTTP 409 code `workbench_cell_conflict` with authoritative `{head, cell}`.
- Standard columns delegate to existing typed validation/change-event logic; extension columns update `version_extension_cells` and append `extension_cell_changes` in the same transaction.

- [ ] Write command digest tests proving token reuse with different value/reason/head is rejected.
- [ ] Write MySQL tests for independent non-conflicting cells, same-cell conflict, invalid standard values, extension strings, sealed versions, permissions, retry recovery, and audit append-only behavior.
- [ ] Implement one lock order: operation token, actor snapshot, dataset lock, active draft pointer/version, row, cell.
- [ ] Return server state on conflict without applying a last-writer-wins overwrite.
- [ ] Run cell-edit tests and existing review mutation suites.

### Task 6: Server-restored undo and history

**Files:**
- Modify: `backend/app/workbench/commands.py`
- Modify: `backend/app/workbench/queries.py`
- Modify: `backend/app/workbench/repository.py`
- Modify: `backend/app/api/workbench.py`
- Test: `backend/tests/integration/test_workbench_undo.py`

**Interfaces:**
- Produces `POST /api/workbench/versions/{version_id}/undo` with expected head and `Idempotency-Key`.
- Produces `GET /api/workbench/versions/{version_id}/changes?page=&page_size=`.
- Undo selects the authenticated user's newest still-current cell change, applies its `before` value through the same optimistic write path, and appends `undoes_change_id`.

- [ ] Write tests for standard/extension undo, refresh recovery, another user's later edit, nothing-to-undo, retry idempotency, and immutable history pagination.
- [ ] Implement a single history ordering by `(occurred_at, ledger_kind, id)` without merging or deleting the underlying ledgers.
- [ ] Block undo when the selected change is no longer the current value and return its server cell state.
- [ ] Run undo/history tests and review-history regression tests.

### Task 7: Idempotent first-edit revision

**Files:**
- Modify: `backend/app/workbench/commands.py`
- Modify: `backend/app/workbench/service.py`
- Modify: `backend/app/api/workbench.py`
- Reuse: `backend/app/publications/service.py`
- Test: `backend/tests/integration/test_workbench_revision.py`

**Interfaces:**
- Produces `POST /api/workbench/dates/{report_date}/{report_type}/revision`.
- Request includes current `published_version_id`, reason, and `Idempotency-Key`.
- Returns the existing active draft when it is a child of the same publication; otherwise creates exactly one revision or returns a structured pointer conflict.

- [ ] Write tests for first edit, retry, existing matching draft, unrelated active draft, changed publication pointer, viewer denial, and extension snapshot copy.
- [ ] Delegate actual revision creation to the existing publication service so lock order, parent lineage, and operation results remain authoritative.
- [ ] Return the new workbench page/head after creation.
- [ ] Run revision tests and publication revision/rollback suites.

### Task 8: Import orchestration, duplicate recovery, and unassigned uploads

**Files:**
- Create: `backend/app/workbench/import_orchestration.py`
- Modify: `backend/app/api/imports.py`
- Modify: `backend/app/imports/types.py`
- Modify: `backend/app/imports/repository.py`
- Modify: `backend/app/parsers/workflow.py`
- Test: `backend/tests/unit/workbench/test_import_orchestration.py`
- Test: `backend/tests/integration/test_workbench_import_orchestration.py`

**Interfaces:**
- Produces `POST /api/workbench/imports` using the existing streamed CSV body and `Idempotency-Key`.
- Produces `GET /api/workbench/imports/{batch_id}` and `GET /api/workbench/imports/pending`.
- Terminal states are `workspace_ready`, `confirmation_required`, `conflict_required`, `duplicate`, and `failed`; processing states are recoverable from server rows.
- Duplicate responses include existing batch, confirmed report date/type, stage, and workspace URL.

- [ ] Write tests proving certain recognition automatically confirms/parses/materializes only when the target has no publication or active draft.
- [ ] Write tests proving uncertain recognition, active draft, existing publication, merge decision, duplicate content, and lost responses never create duplicate drafts.
- [ ] Store an unconfirmed detected/selected date in `candidate_report_date`; keep the legacy `report_date` only for compatibility and exclude it from every calendar/ledger query until `confirmed_at` and `confirmed_report_type` are present.
- [ ] Implement orchestration as resumable idempotent transitions using server state after every transaction; do not hold a database transaction while reading the file.
- [ ] Make legacy `/api/imports` return a structured duplicate body instead of an error string while keeping its HTTP 409 compatibility.
- [ ] Run orchestration, import, parsing, calendar, and raw-file integrity tests.

### Task 9: Generated client and frontend workbench state

**Files:**
- Create: `frontend/src/features/workbench/workbenchTypes.ts`
- Create: `frontend/src/features/workbench/workbenchState.ts`
- Create: `frontend/src/features/workbench/workbenchApi.ts`
- Test: `frontend/src/features/workbench/workbenchState.test.ts`
- Modify: `frontend/src/api/generated.ts` through `scripts/generate-api-client.ps1`

**Interfaces:**
- Produces pure URL parsing/serialization for report tab, search, sort, filters, page, and visible columns.
- Produces request functions only through `requestApi` and an editor state keyed by `versionId:rowId:columnId`.
- Editor states are `clean`, `editing`, `saving`, `saved`, `failed`, and `conflict`; failed/conflict states retain the draft input.

- [ ] Write reducer tests for keyboard commit, stale responses, retry, conflict adoption/resubmit, route refresh, and report-tab URL persistence.
- [ ] Generate the API client and derive frontend types from the generated contract.
- [ ] Implement reducer/selectors without storing authoritative server completion in session storage.
- [ ] Run frontend state tests and the API generation drift check.

### Task 10: Table-first date workspace UI

**Files:**
- Create: `frontend/src/features/workbench/DateWorkbenchPage.tsx`
- Create: `frontend/src/features/workbench/EditableDataGrid.tsx`
- Create: `frontend/src/features/workbench/WorkbenchToolbar.tsx`
- Create: `frontend/src/features/workbench/WorkbenchActionBar.tsx`
- Create: `frontend/src/features/workbench/DateWorkbenchPage.css`
- Test: matching `*.test.tsx` files
- Modify: `frontend/src/app/App.tsx`

**Interfaces:**
- `/review/:reportDate` renders the writable aggregate workspace; `/published/:reportDate` renders the same table component with viewer permissions.
- Grid implements click-to-edit, Enter/down, Tab/right, Escape/cancel, blur/save, fixed identity columns, horizontal overflow, and accessible table semantics.
- Published first edit calls the revision endpoint before sending the cell write.

- [ ] Write component tests for empty/upload, certain/uncertain import, both report tabs, all original columns/order, autosave, error retry, conflict choices, undo after reload, first-edit revision, offline, and viewer read-only state.
- [ ] Implement the compact toolbar, filters, paginated grid, save summary, and fixed bottom action bar.
- [ ] Keep only the active cell input local; refresh page data after accepted writes without erasing failed/conflicting input.
- [ ] Replace the route's import-step hero as the primary surface; retain advanced validation, notes, row state, and publication controls behind the bottom action bar/dialogs.
- [ ] Run workbench component tests, App route tests, lint, typecheck, and build.

### Task 11: Calendar ownership, responsive behavior, and E2E

**Files:**
- Modify: `backend/app/api/data_calendar.py`
- Modify: `backend/app/analytics/daily_ledger.py`
- Modify: `frontend/src/features/dashboard/PublishedDashboard.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/tests/e2e/import-review-publish.spec.ts`
- Modify: `docs/user-guide/stage9-local-demo.md`

**Interfaces:**
- Calendar and daily ledger ignore unconfirmed candidate dates and expose a separate pending-upload count.
- Home date rows keep role-based workbench navigation.

- [ ] Add backend tests proving candidate dates do not create draft/processing/incomplete day states.
- [ ] Add frontend/E2E tests for home-to-workbench, automatic import, autosave/undo, publish, viewer read-only, duplicate recovery, and account isolation.
- [ ] Verify 1280px/768px/390px behavior, visible keyboard focus, `aria-sort`, error alerts, reduced motion, and horizontal table scrolling.
- [ ] Update the local guide with the table-first flow and explain strict-mock E2E versus real MySQL evidence.
- [ ] Run the E2E test in Chromium.

### Task 12: Full gates and safe local experience

**Files:**
- Modify only documentation or tests needed to record verified results.

**Interfaces:**
- Produces no new product API; it proves the implementation and preserves existing data.

- [ ] Run Ruff format/check, mypy, all non-MySQL backend tests, generated-client drift, frontend lint/typecheck/tests/build/E2E, and `git diff --check`.
- [ ] With the disposable MySQL test database explicitly selected, run migration, workbench, review, publication, calendar, backup, and compatibility suites with `--run-mysql`/`--require-mysql` as configured by the repository.
- [ ] Use only repository de-identified fixtures to import one business and one return CSV into an explicit demo date; edit one non-sensitive cell, undo it, refresh, validate, and publish.
- [ ] Verify admin, data_manager, and viewer behavior and confirm no production database, existing batch, raw file, or backup was deleted or migrated.
- [ ] Record exact pass/skip counts and leave all pre-existing uncommitted changes intact.

## Completion Definition

- Uploading a conflict-free recognized CSV opens a server-backed editable table without exposing internal pipeline steps.
- Every original column is ordered, versioned, searchable, visible, and editable according to role; only mapped standard columns affect analytics.
- Autosave, retry, conflict resolution, history, and undo survive refresh and preserve append-only evidence.
- Editing a publication creates a child draft before the first write; publication pointers switch only through existing validated publication transactions.
- Duplicate and unassigned uploads have actionable server-owned states and cannot pollute a date ledger.
- All automated gates and the de-identified local experience pass.
