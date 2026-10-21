# Switchable Application Release Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a host-operated, auditable application release system that can publish any still-approved and database-compatible `v11A.1.N` release, automatically restore the operation's frozen source application when that is provably safe, and otherwise remain in maintenance without ever downgrading MySQL.

**Architecture:** GitHub builds and signs immutable multi-component releases from protected `master`; a PowerShell controller on the server verifies the signed catalog and exact OCI digests, then drives a durable 20-step single-slot transaction over a stable MySQL/edge base and a replaceable application Compose project. Every side effect has intent/completion journal evidence. A dedicated fence-holder keeps the MySQL named lock and barrier-row lock on one connection across migration and target validation. The application, worker, browser, and Agent runtime expose release identity, admission, drain, and compatibility evidence but never receive Docker or package-publishing authority.

**Tech Stack:** Python 3.14, FastAPI, synchronous SQLAlchemy 2, Alembic, MySQL 8.0/8.4, React 19, TypeScript 5.9, Docker Compose, Nginx, PowerShell 7, GitHub Actions, GHCR, OCI digests/referrers, Sigstore-compatible signing, pytest, Vitest, and Playwright.

## Prerequisites and Stop Conditions

- The approved design is `docs/superpowers/specs/2026-08-12-switchable-application-release-management-design.md`. A change to its data, security, recovery, trust, or deployment boundary requires a design amendment before implementation continues.
- Complete all 18 tasks in `docs/superpowers/plans/2026-08-12-read-only-agent-analysis-implementation.md` first. In particular, 11B depends on backup format v2, the one-shot definer migration privilege flow, Agent Runtime mTLS/fencing/current-pointer behavior, MySQL 8.0/8.4 coverage, and the target acceptance harness.
- Do not edit an applied Alembic revision. The former assumption that 11A owns `0022` is archived because P0 now owns that revision. Before any 11A/11B implementation, re-plan both paused plans against the actual single Alembic head; the first 11B migration must use the next unoccupied revision after the completed 11A graph, with its filename and `down_revision` assigned only then.
- The existing `ops/DEPLOYMENT.md` procedure remains the only supported production upgrade path until every task and external gate in this plan is complete.
- Task 15 proves only the normal deploy path. Do not claim version switching is supported after Task 15. Tasks 16, 18, and 19 plus the target-equivalent rehearsal are mandatory completion gates.
- No ordinary release command may expose `SkipBackup`, `SkipSignature`, `SkipCompatibility`, `SkipMigrationCheck`, `SkipHealth`, `ForceDeploy`, a fault-injection flag, or an automatic database downgrade/overwrite path.
- Every test must assert both the required state and forbidden side effects: no production database downgrade, no business publication/configuration pointer change, no real daily-data edit, no unauthorized write, no speculative traffic restoration, and no Secret/business content in evidence.

## Current Evidence and External Gates

The following observations were made read-only on 2026-08-12 and are not completion claims:

- The repository is private and its default branch is `master`.
- GitHub currently reports no repository rulesets, and branch protection for `master` is absent.
- `.github/workflows/compatibility.yml` still uses movable Action references such as `actions/checkout@v4` and `actions/setup-python@v5`.
- `ops/docker-compose.yml` is one project and production application services still use local `build:`.
- The current maintenance barrier is a context manager; it cannot survive the controller process or prove a cross-step connection identity.

Four gates deliberately sit outside ordinary repository implementation:

| Gate | Owner and required evidence | Blocks |
|---|---|---|
| P0 — 11A complete | Engineering: all 18 11A commits and their stated deterministic, MySQL, container, backup, Agent, and target evidence | Every 11B implementation task that consumes 11A; no production activation |
| G1 — GitHub trust | Repository owner: exported API evidence for protected `master`, stable required check, no force-push/delete or silent admin bypass, protected `v11A.1.*`, catalog/controller/`deployment-ledger/*` namespaces, reviewed Action allowlist/default token permissions, ledger dispatcher/workflow identities, signing identity, and GHCR permissions | Real ledger records or package publication in Tasks 9–18 |
| G2 — host trust | Server administrator: one exact signed controller/base bundle source SHA and digest, complete inventory/dependency graph, dedicated release OS identity, approved tool hashes/absolute paths, Docker membership/context, protected state/credential ACLs, read-only registry identity, receipt-only identity, and backup/key fault-domain checks | Installation/use of that exact controller bundle and any real deploy in Tasks 11–19 |
| G3 — signed baseline takeover | Release administrator using the exact G2-approved controller bundle: a healthy running stack whose actual component digests and runtime pointer exactly equal one approved signed manifest, followed by one-time genesis-state adoption or strict read-only revalidation of an existing genesis/current chain; never infer a version from a local build or tag | First normal `deploy`/`recover`, and G4 after any controller/base change |
| G4 — target-equivalent rehearsal | Release owner and server administrator: signed baseline → expand release → compatible older release → target failure recovery → partial-DDL maintenance, with content-free signed evidence | Declaring 11B production-supported |

G1 is currently known to fail. Repository tests must fail closed when its exported evidence is absent or nonconforming; workflow YAML must not pretend that external protection exists.

G2 and the controller-dependent proof of G3 are **artifact-scoped, not once-per-host approvals**. Any later commit that changes a file in the controller/base bundle inventory, its locked dependency/tool graph, installer, stable-base/edge configuration, policy/schema, or verification path invalidates the earlier G2 evidence and the use of its G3 proof for later deployment/support claims. The changed bundle receives a new immutable controller/base version and must repeat the complete G2 checks. Before G4, the final Task-19 source SHA and signed bundle digest must have fresh G2 evidence, then the same installed bundle must establish G3 or strictly revalidate the immutable existing genesis/current chain without writing a second genesis. A mismatch blocks deployment/rehearsal; it is never repaired by blessing the observed host.

## Locked Identity and State Rules

- `v11A.1.N` accepts only a positive base-10 integer `N` with no leading zero. Sort by integer ordinal. A successfully created version ref permanently occupies the number even if the release later fails.
- GitHub Release is the atomic visibility boundary for a complete release; the signed chained catalog is the only authority for current `approved`, `revoked`, `archived`, and `long_term_retained` status.
- Production consumes only `repository@sha256:<digest>` values present in one verified manifest. A tag is diagnostic only.
- Canonical records use a versioned, restricted JSON profile: UTF-8, sorted object keys, no insignificant whitespace, no duplicate keys, no floats/NaN/infinity, RFC 3339 UTC timestamps, and `additionalProperties: false`. A record digest is calculated over the object without its own digest field.
- Avoid cryptographic self-reference across both images and Compose. Images embed an immutable `release_build_identity` (repository, protected source SHA, workflow identity, component role, protocol versions). The application manifest binds exact image digests plus a **version/manifest-independent** Compose template digest, renderer/toolchain digest, and rendering schema version; the template itself contains no release version or final manifest digest. After ordinal allocation and all component/evidence digests exist, Task 10 is the only place that creates and signs the final application manifest. The verified controller then derives one rendered Compose file and read-only runtime identity file from that manifest. Their operation-specific digests are journal/receipt evidence and are never fed back into the manifest. The browser must load the runtime identity before enabling writes.
- A release operation freezes `source_release` from committed journal state **and** actual running digest/labels at operation creation. It never substitutes the older `previous_stable` value.
- `current` and `previous_stable` are derived caches. The append-only journal plus actual container, edge, fence, and database facts decide recovery.
- The database is only upgraded along an approved forward Alembic graph path. Application rollback never invokes Alembic downgrade and never overwrites production from backup.
- From `source_stopped_and_writer_fenced` through `writer_fence_released`, one dedicated fence-holder connection is the only authoritative owner of both locks. Holder disappearance is an unknown fact, not successful release evidence.
- `list`, `inspect`, `status`, `history`, and `deploy -WhatIf` do not acquire a write lock, write state/cache/journal, pull images, create a backup, start/stop a container, change admission, or reload edge.
- All release evidence is content-free and follows an explicit field allowlist. It may contain version, manifest/image digest, Git SHA, database revision/fingerprint, operation UUID, state/result code, actor identity, timestamps, and evidence digests; it may not contain business values, filenames from imports, raw provider errors, credentials, token values, or Secret file contents.

## Locked File Structure and Public Interfaces

Implementation may add small focused helpers, but responsibilities must remain within these boundaries:

```text
release/
├─ schemas/
│  ├─ release-manifest.schema.json
│  ├─ release-build-descriptor.schema.json
│  ├─ release-catalog.schema.json
│  ├─ deployment-operation-hold.schema.json
│  ├─ deployment-receipt.schema.json
│  ├─ controller-base-inventory.schema.json
│  └─ controller-base-bundle.schema.json
├─ policies/
│  ├─ github-repository-policy.json
│  ├─ trusted-release-identities.json
│  ├─ controller-base-inventory.json
│  └─ release-security-policy.json
├─ compatibility/database-revisions.json
└─ fixtures/                         # synthetic/golden records only

tools/releases/
├─ canonical_json.py
├─ versioning.py
├─ records.py
├─ catalog.py
├─ github_policy.py
├─ supply_chain.py
├─ publish.py
└─ retention.py

ops/
├─ release.ps1                       # strict parsing and command dispatch only
├─ install-release-controller.ps1
├─ verify-release-deployment.ps1
├─ docker-compose.base.yml
├─ docker-compose.app.template.yml
├─ nginx/
│  ├─ edge.conf
│  ├─ maintenance.html
│  └─ modes/{app-upstream,maintenance}.conf
└─ release/
   ├─ Contracts.psm1
   ├─ Catalog.psm1
   ├─ HostSecurity.psm1
   ├─ State.psm1
   ├─ Journal.psm1
   ├─ Locks.psm1
   ├─ Docker.psm1
   ├─ Edge.psm1
   ├─ Database.psm1
   ├─ BackupRestore.psm1
   ├─ Transaction.psm1
   └─ Recovery.psm1

backend/app/deployment/
├─ release_identity.py
├─ release_admission.py
├─ release_probe.py
└─ database_compatibility.py

backend/app/maintenance/fence_holder.py
```

The protected server root defaults to `C:\ProgramData\CLSEN\ReleaseController` and is configurable only at installation. It contains `journal/`, derived `state/`, verified `catalog-cache/`, operation work directories, rendered Compose files, approved tool policy, and content-free logs. It is never a repository directory or application mount. The application receives only narrowly scoped read-only identity/admission files and per-role status paths; it never receives journal, registry credentials, receipt credentials, host tool policy, or Docker socket.

Canonical cross-language interfaces are:

```python
@dataclass(frozen=True, slots=True, order=True)
class ReleaseVersion:
    ordinal: int

    @classmethod
    def parse(cls, value: str) -> "ReleaseVersion": ...

    def __str__(self) -> str: ...  # v11A.1.N

def load_strict_json(data: bytes) -> Mapping[str, object]: ...
def canonical_json_bytes(value: Mapping[str, object]) -> bytes: ...
def canonical_record_digest(value_without_digest: Mapping[str, object]) -> str: ...

class CatalogStatus(StrEnum):
    APPROVED = "approved"
    REVOKED = "revoked"
    ARCHIVED = "archived"

@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    version: str
    manifest_digest: str
    build_identity: str
    browser_protocol: str

class ReleaseAdmissionMode(StrEnum):
    ACTIVE = "active"
    DRAINING = "draining"
    FENCED = "fenced"
```

```powershell
Get-ReleaseCatalog -Fresh -NoStateWrite
Test-ReleaseManifest -Version <version> -ManifestDigest <sha256>
Read-DeploymentJournal -OperationId <uuid>
Test-DeploymentFacts -OperationId <uuid>
Invoke-ReleaseDeploy -Version <version> [-WhatIf]
Invoke-ReleaseRecovery -OperationId <uuid>
```

`release.ps1` initially exposes these user commands:

```powershell
pwsh .\ops\release.ps1 list
pwsh .\ops\release.ps1 inspect -Version v11A.1.23
pwsh .\ops\release.ps1 status
pwsh .\ops\release.ps1 history
pwsh .\ops\release.ps1 initialize -Version v11A.1.1 -WhatIf
pwsh .\ops\release.ps1 initialize -Version v11A.1.1
pwsh .\ops\release.ps1 deploy -Version v11A.1.23 -WhatIf
pwsh .\ops\release.ps1 deploy -Version v11A.1.23
pwsh .\ops\release.ps1 recover -OperationId <uuid>
pwsh .\ops\release.ps1 prune -WhatIf
pwsh .\ops\release.ps1 prune
```

`initialize` is a one-time signed-baseline adoption command, not a way to bless a local build. It refuses if any deployment journal/current state exists or if one actual container digest, label, database fingerprint, Agent runtime pointer, edge target, or signed-manifest value differs.

---

### Task 1: Establish Repository Trust Prerequisites and a Stable Required Gate

**Depends on:** none for repository changes; G1 remains external.

**Files:**
- Modify: `.github/workflows/compatibility.yml`
- Create: `release/policies/github-repository-policy.json`
- Create: `tools/releases/__init__.py`
- Create: `tools/releases/github_policy.py`
- Create: `tools/releases/audit_github_settings.py`
- Create: `tools/tests/test_release_github_policy.py`
- Create: `backend/tests/contracts/test_release_workflows.py`
- Create: `docs/operations/github-release-trust-prerequisites.md`

**Interfaces:**
- Produces a versioned closed repository policy for default branch `master`, required check name `release-required`, protected `v11A.1.*`, catalog/controller and `deployment-ledger/*` tag namespaces, allowed Action repositories, default token permissions, trusted release/ledger workflow paths and actors, and no silent bypass. Ledger creation and update/delete controls must be separate: only the dedicated protected ledger workflow identity may create ledger refs, while no ordinary actor/workflow may update or delete them.
- Produces `python -m tools.releases.audit_github_settings --repository OWNER/REPO --policy release/policies/github-repository-policy.json --evidence-directory <protected-path>`, which exports only configuration metadata, returns nonzero for missing/unknown settings, and never prints tokens.
- Keeps every `uses:` reference at a reviewed 40-hex commit SHA. Floating tags, local unreviewed composite Actions, and mutable container actions fail the contract.
- Adds one stable `release-required` aggregator job which fails unless every required offline, MySQL, frontend, container, migration, backup, and later release gate succeeds. A skipped required dependency is failure unless the policy explicitly identifies a non-applicable event.

- [ ] **Step 1: Write failing workflow and policy tests**

Test full-SHA `uses:` references, explicit top-level/job permissions, no write permission on PR/untrusted refs, stable required job identity, `master`-only release eligibility, schema-closed policy JSON, and redaction of authorization headers. Add fixtures for missing protection, admin bypass, application/catalog/controller/ledger tag update or deletion, ledger creation by a non-ledger actor, overly broad Actions, and valid exported settings.

- [ ] **Step 2: Run the contracts and record the expected current failure**

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests/test_release_github_policy.py backend/tests/contracts/test_release_workflows.py -m "not mysql and not deepseek_live" -v`

Expected: FAIL because existing Actions use movable version tags and there is no stable required-release aggregator or repository policy.

- [ ] **Step 3: Pin reviewed workflow dependencies and add the stable aggregator**

Resolve each Action to a full upstream commit SHA, verify its repository and release provenance, record its owner/repository in the closed allowlist, and replace all movable references. Do not invent SHA values or accept a SHA copied from untrusted workflow output. Keep ordinary jobs at `contents: read`; do not grant package, ID token, attestation, Release, or tag write authority in `compatibility.yml`.

- [ ] **Step 4: Implement the read-only GitHub settings auditor and operator checklist**

Parse exported API documents into typed policy facts. Reject absent fields as unknown rather than treating them as false/safe. The guide must give exact `gh api` export commands for repository/default branch, rulesets, branch protection, Actions permissions/allowlist, environments, and package permissions, plus the expected nonzero audit before G1 is configured. Evidence goes outside Git and contains no credential or response body unrelated to settings.

- [ ] **Step 5: Verify repository-local contracts and G1 failure behavior**

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests/test_release_github_policy.py backend/tests/contracts/test_release_workflows.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m tools.releases.audit_github_settings --repository dulanjy/CLSEN_Data_Web --policy release/policies/github-repository-policy.json --evidence-directory "$env:TEMP\clsen-github-policy-audit"`

Expected: unit/contract tests PASS. The live audit is an external G1 check and currently exits nonzero with closed reason codes for missing `master`/tag protection; do not report G1 as passed until the owner changes GitHub settings and saves fresh API evidence.

- [ ] **Step 6: Commit the repository trust boundary**

```powershell
git add .github/workflows/compatibility.yml release/policies/github-repository-policy.json tools/releases tools/tests/test_release_github_policy.py backend/tests/contracts/test_release_workflows.py docs/operations/github-release-trust-prerequisites.md
git commit -m "ci: establish release trust prerequisites"
```

**External G1 action after this commit:** The repository owner configures and audits the rulesets, required check, Actions allowlist/default permission, signing identity, GHCR package association, and actor bypass rules. A release workflow added later must consume the auditor result and fail before any tag/package write when G1 evidence is absent or stale.

### Task 2: Define Canonical Release Versions, Manifests, Catalogs, and Receipts

**Depends on:** Task 1 for policy vocabulary.

**Files:**
- Create: `release/schemas/release-manifest.schema.json`
- Create: `release/schemas/release-catalog.schema.json`
- Create: `release/schemas/deployment-operation-hold.schema.json`
- Create: `release/schemas/deployment-receipt.schema.json`
- Create: `release/schemas/controller-base-bundle.schema.json`
- Create: `release/policies/trusted-release-identities.json`
- Create: `release/policies/release-security-policy.json`
- Create: `release/fixtures/canonical-record-vectors.json`
- Create: `release/fixtures/tampered-record-vectors.json`
- Create: `tools/releases/canonical_json.py`
- Create: `tools/releases/versioning.py`
- Create: `tools/releases/records.py`
- Create: `tools/tests/test_release_canonical_json.py`
- Create: `tools/tests/test_release_versioning.py`
- Create: `tools/tests/test_release_records.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/requirements.in`
- Modify: `backend/requirements.lock`

**Interfaces:**
- Implements the locked `ReleaseVersion`, strict JSON loader, canonical bytes, and record digest interfaces.
- Manifest format `clsen.release-manifest.v1` contains series/ordinal, repository/ref/SHA/workflow identity, `release_build_identity`, exact role-to-platform OCI digest map, version-independent Compose template digest plus renderer/toolchain digest and rendering schema version, configuration/Secret-name contracts, Alembic target/support graph digest, API/browser/Agent protocols, runtime bundle, SBOM/provenance/signature/scan subjects, policy exception records, and its canonical digest. A rendered Compose digest is deliberately excluded because it contains operation/final-manifest identity and belongs only in the deployment journal/receipt.
- Catalog format `clsen.release-catalog.v1`, operation-hold format `clsen.deployment-operation-hold.v1`, receipt format `clsen.deployment-receipt.v1`, and controller/base bundle format `clsen.controller-base-bundle.v1` are schema-closed. A hold binds environment, operation UUID, source/target manifest digests, catalog generation, monotonic heartbeat sequence, issue/expiry time, signer identity, prior ledger-record digest, prior environment-head digest, and transition kind (`register` or `renew`). A terminal receipt is the single `close` ledger transition and binds the same hold plus database before/after revision/fingerprint, terminal result, and evidence digest. The bounded canonical signed record is stored directly in the immutable annotated-tag message of `deployment-ledger/<environment>/<fixed-width-environment-sequence>` created only by the protected ledger workflow; the ref name deliberately excludes record digest so competing writers for one sequence collide on the same ref. Sequence width and maximum are closed policy, parsing is strict decimal/integer, and overflow is a design stop. No deletable Release asset, Deployment status, external blob, or GitHub-reserialized JSON is authoritative. Records exceeding the reviewed annotated-tag/API byte limit are rejected rather than split or truncated. The controller/base format binds source/workflow identity, OS/platform, state schema compatibility, and an exact file-digest inventory without embedding any Secret.
- Trusted identity policy matches exact repository, workflow file, protected ref, issuer, subject/source SHA, and artifact subject digest. A matching repository name alone is insufficient.
- Security policy uses closed severity/exception codes, named owner, expiry, and affected digest. Free-text bypasses are not executable policy.
- Lock a maintained Python JSON Schema validator (Draft 2020-12 or the exact draft declared by these schemas) in `requirements.in`/hash-locked `requirements.lock` and project dependencies. Do not hand-roll schema semantics. The ordinary offline suite installs it from the locked dependency set. PowerShell validates canonical records through repository-owned code/fixtures or an explicitly locked offline validator; it does not fetch a schema/module at runtime.

- [ ] **Step 1: Write failing version and canonicalization tests**

Cover `v11A.1.1`, integer ordering of 9/10, gaps, and the rejection of zero, negatives, leading zero, whitespace, other prefixes, SemVer inference, and integers outside the policy maximum. Golden vectors must be independently readable by Python and PowerShell later. Reject duplicate JSON keys, unknown fields/formats, floats, non-UTC timestamps, noncanonical digest fields, and Unicode/line-ending drift.

- [ ] **Step 2: Write failing schema, digest, and identity tests**

Build a complete synthetic manifest/catalog/hold/receipt/controller-base record set and fixed tamper vectors changing one image, Compose template/renderer/schema subject, SBOM, provenance, source SHA, trusted workflow, database support digest, hold sequence/expiry, controller file/state schema, or canonical byte. Assert each mutation changes the record digest and fails subject/identity validation. Prove the signed template has no ordinal, version, final-manifest digest, or operation UUID and can render two different manifests without changing its own digest; prove neither rendered digest is accepted as a manifest input. Scan all fixtures for Secret and business-data canaries.

- [ ] **Step 3: Run the focused tests and observe missing contracts**

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests/test_release_canonical_json.py tools/tests/test_release_versioning.py tools/tests/test_release_records.py -v`

Expected: FAIL because schemas, strict canonical records, version parsing, and identity policies do not exist.

- [ ] **Step 4: Implement the smallest closed canonical record layer**

Use a duplicate-key-detecting decoder before the hash-locked JSON Schema validator/model construction. Permit only JSON strings, booleans, null, bounded integers, arrays, and objects; do not silently coerce. Calculate `sha256:<lowercase-hex>` over the object with its digest member omitted. Validate schema and every referenced subject before returning a domain object. Keep signature cryptography in the supply-chain/client layers; this task defines what bytes and identity constraints they must verify.

Document and implement the non-circular identity rule: component images bind `release_build_identity`; the version-neutral template/renderer bind structure; the final manifest binds their digests and image digests; final manifest identity is injected only during verified operation rendering. Never weaken the manifest by substituting a tag/source SHA for an OCI digest or by hashing a rendered file back into its own manifest.

- [ ] **Step 5: Verify records and cross-language golden vectors**

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests/test_release_canonical_json.py tools/tests/test_release_versioning.py tools/tests/test_release_records.py -v`

Run: `.\.venv\Scripts\python.exe -m ruff check tools/releases tools/tests`

Run: `.\.venv\Scripts\python.exe -m mypy --config-file backend/pyproject.toml tools/releases tools/tests`

Expected: PASS; every tamper vector is rejected, schemas contain `additionalProperties: false`, and fixtures contain no Secret/business canary.

- [ ] **Step 6: Commit canonical release records**

```powershell
git add release tools/releases tools/tests backend/pyproject.toml backend/requirements.in backend/requirements.lock
git commit -m "feat: define canonical release records"
```

### Task 3: Validate Chained Catalog Generations and Closed Release States

**Depends on:** Task 2.

**Files:**
- Create: `tools/releases/catalog.py`
- Create: `release/fixtures/catalog-chain-valid.json`
- Create: `release/fixtures/catalog-chain-invalid.json`
- Create: `tools/tests/test_release_catalog.py`
- Modify: `tools/releases/records.py`
- Modify: `release/schemas/release-catalog.schema.json`

**Interfaces:**
- Produces `validate_catalog(candidate, *, trusted_identity, now, last_accepted) -> CatalogValidation` and `apply_catalog_transition(previous, candidate) -> CatalogSnapshot`.
- `generation` is a positive monotonic integer; every generation after genesis binds exactly the prior accepted canonical digest. Equal generation is idempotent only when the digest is identical.
- Registration transitions are closed: absent/building is CI-private; centrally visible releases enter `approved`; `approved → revoked` and `approved → archived` are allowed with closed reason/time evidence; `revoked` is permanent; archived artifacts cannot silently become approved.
- `long_term_retained` is audited metadata and does not revive revoked/archived releases.
- Expired or not-yet-valid catalog, chain gap, rollback, identity mismatch, unknown state/reason, or changed record at the same generation fails closed. Only `list` may display a clearly marked stale local snapshot; `inspect`, `WhatIf`, and `deploy` require fresh validation.

- [ ] **Step 1: Write failing chain and transition-table tests**

Cover genesis, monotonic advance, exact replay, generation rollback, skipped generation, wrong previous digest, same-generation content drift, expiry boundary, clock-skew policy, unknown status, revoked resurrection, archive ordering, retain/unretain audit, and a stale display projection which cannot be used as deploy input.

- [ ] **Step 2: Run the catalog tests and observe the absent validator**

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests/test_release_catalog.py -v`

Expected: FAIL because catalog chain verification and the closed transition table are absent.

- [ ] **Step 3: Implement pure catalog validation**

Keep the validator deterministic and side-effect free. Require the caller to provide trusted time and last-accepted evidence. Return a typed reason code for every refusal, never a permissive boolean default. Verify manifest digest uniqueness, ordinal/version agreement, immutable source binding, and status timestamp monotonicity in addition to the chain envelope.

- [ ] **Step 4: Verify rollback, replay, and terminal revocation behavior**

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests/test_release_catalog.py tools/tests/test_release_records.py -v`

Expected: PASS, including rejection before any artifact or host action for every invalid chain vector.

- [ ] **Step 5: Commit the catalog state core**

```powershell
git add tools/releases/catalog.py tools/releases/records.py tools/tests/test_release_catalog.py release/schemas/release-catalog.schema.json release/fixtures/catalog-chain-valid.json release/fixtures/catalog-chain-invalid.json
git commit -m "feat: validate chained release catalogs"
```

### Task 4: Enforce Application and Browser Release Identity Before Writes

**Depends on:** P0 and Task 2.

**Files:**
- Create: `backend/app/deployment/release_identity.py`
- Create: `backend/app/api/release_identity.py`
- Create: `backend/tests/unit/deployment/test_release_identity.py`
- Create: `backend/tests/integration/test_release_browser_session_compatibility.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/unit/test_config.py`
- Modify: `backend/tests/unit/test_main.py`
- Modify: `backend/tests/integration/test_authentication_api.py`
- Modify: `backend/tests/unit/test_openapi_contract.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/client.test.ts`
- Create: `frontend/src/release/releaseIdentity.ts`
- Create: `frontend/src/release/releaseIdentity.test.ts`
- Create: `frontend/src/release/ReleaseMismatchNotice.tsx`
- Create: `frontend/src/release/ReleaseMismatchNotice.test.tsx`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/app/App.test.tsx`
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/nginx.conf`
- Modify: `frontend/Dockerfile`
- Modify: `frontend/tests/e2e/import-review-publish.spec.ts`
- Modify: `ops/docker-compose.yml`
- Modify: `.env.example`

**Interfaces:**
- Backend starts only with a schema-valid read-only runtime identity file whose final manifest digest, build identity, version, browser protocol, and allowed client digests agree with environment/image labels.
- To keep the existing server Compose operable until G3, server configuration has an explicit `unmanaged_legacy` deployment mode which supplies **no fabricated release version/manifest**, labels responses/UI as unmanaged, and does not claim release switching, browser cross-version protection, or catalog membership. It is accepted only by the legacy `ops/docker-compose.yml` during the migration window. Task 8's signed application template requires `managed` mode and has no value/parameter which can disable identity enforcement; Task 12/G3 refuses initialization/deploy from unmanaged mode except exact signed baseline adoption.
- `GET /api/release-identity` returns only `{version, manifest_digest, browser_protocol}` and also emits `X-CLSEN-Release-Manifest` on API responses. It never exposes GitHub run data, filesystem paths, image registry credentials, or configuration values.
- Every `POST`, `PUT`, `PATCH`, and `DELETE` must send `X-CLSEN-Client-Release`. An early guard validates it before CSRF rotation, idempotency persistence, session mutation, database checkout/write, outbox append, or business service invocation. Missing/disallowed identity returns `409 client_release_mismatch`.
- The frontend image embeds only non-circular build identity. At deployment, `/release-identity.json` is mounted from controller-verified data, served with `Cache-Control: no-store`, and loaded before React enables mutations. `index.html` revalidates; hashed chunks remain immutable-cacheable.
- On mismatch, retain the user's unsent form state in the current page, disable submission, and request one explicit refresh. Never automatically replay an unknown write. A failed lazy chunk causes at most one controlled full reload marker per navigation.
- Session/Cookie schema remains compatible across the window; a release requiring a destructive session format cannot be approved for ordinary switching.

- [ ] **Step 1: Write failing backend identity and zero-write guard tests**

Parameterize every mutating route and roles `admin`, `data_manager`, and `viewer`. Test missing, malformed, stale, unknown, and allowed identities. Spy before engine checkout, idempotency repository, session mutation, outbox, and domain repository; rejected calls must observe zero side effects. Test GET/health allowlist separately. Verify configuration fails closed in server mode but permits an explicit synthetic development identity in tests.

Also test the migration-only `unmanaged_legacy` mode: it is accepted only with the legacy Compose marker and the explicitly documented non-secret `.env.example` setting, returns an explicit unmanaged identity/status, and cannot be combined with a manifest/client allowlist or used by a rendered/approved release. Removing the marker or setting `managed` without a verified identity fails startup. This mode never makes a local build eligible for G3.

- [ ] **Step 2: Write failing frontend bootstrap, cache, and mismatch tests**

Require identity bootstrap before `writeApi`, exact header propagation, no automatic replay, form preservation, one controlled chunk reload, no reload loop, `index.html` revalidation, and long-cache hashed assets. Extend browser E2E: hold an unsaved review in source UI, switch fixture identity, attempt save, assert zero API mutation and a refresh prompt; after refresh require a new human click.

- [ ] **Step 3: Run the focused tests and observe missing identity enforcement**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/deployment/test_release_identity.py backend/tests/unit/test_main.py backend/tests/integration/test_release_browser_session_compatibility.py --require-mysql -v`

Run: `pnpm --dir frontend test --run src/api/client.test.ts src/release/releaseIdentity.test.ts src/release/ReleaseMismatchNotice.test.tsx src/app/App.test.tsx`

Expected: FAIL because runtime identity loading, early mutation rejection, frontend bootstrap, and mismatch UI do not exist.

- [ ] **Step 4: Implement the backend guard before all mutable dependencies**

Parse and validate identity once at startup, but re-read the controller-owned admission/identity generation safely when it can change during activation. Put the mutation guard at the earliest request boundary and prove middleware ordering. Do not use route-maintained opt-in lists which can forget a newly added mutation. Preserve request IDs and return the stable closed error code.

- [ ] **Step 5: Implement non-circular frontend identity and safe recovery UX**

Make application bootstrap fail closed for writes if runtime identity is absent or inconsistent with the image build identity. Keep read-only display available with an explicit stale-client banner where safe. On refresh, fetch noncached index/runtime identity; do not serialize unknown form data into URL, logs, local analytics, or automatic retry queues.

- [ ] **Step 6: Regenerate and verify API/frontend contracts**

Run: `pwsh .\scripts\generate-api-client.ps1`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/deployment/test_release_identity.py backend/tests/unit/test_main.py backend/tests/integration/test_release_browser_session_compatibility.py backend/tests/integration/test_authentication_api.py --require-mysql -v`

Run: `pnpm --dir frontend lint`

Run: `pnpm --dir frontend typecheck`

Run: `pnpm --dir frontend test --run`

Run: `pnpm --dir frontend test:e2e -- import-review-publish.spec.ts`

Expected: PASS; mismatch requests cause zero backend write, the browser never replays an unknown form, and a session remains valid after a compatible identity switch. The E2E result is fixture-driven unless explicitly run against the disposable full stack.

- [ ] **Step 7: Commit client/server release identity**

```powershell
git add backend/app/deployment/release_identity.py backend/app/api/release_identity.py backend/app/config.py backend/app/main.py backend/tests frontend/src frontend/nginx.conf frontend/Dockerfile frontend/tests/e2e/import-review-publish.spec.ts ops/docker-compose.yml .env.example
git commit -m "feat: enforce client release compatibility"
```

### Task 5: Add Release Admission, Drain, and Role-Specific Health Controls

**Depends on:** P0 and Task 4.

**Files:**
- Create: `backend/app/deployment/release_admission.py`
- Create: `backend/app/deployment/release_probe.py`
- Create: `backend/tests/unit/deployment/test_release_admission.py`
- Create: `backend/tests/integration/test_release_drain.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/worker/cli.py`
- Modify: `backend/app/worker/outbox.py`
- Modify: `backend/tests/unit/test_health.py`
- Modify: `backend/tests/integration/test_outbox_worker.py`
- Modify: `backend/app/agent/service.py`
- Modify: `backend/app/agent/repository.py`
- Modify: `backend/app/agent_control/service.py`
- Modify: `backend/tests/integration/test_agent_runtime_leases.py`
- Modify: `backend/app/deployment/entrypoint.py`
- Modify: `backend/tests/unit/deployment/test_entrypoint.py`

**Interfaces:**
- A controller-owned, read-only admission document contains `format`, monotonic `generation`, operation UUID, release manifest digest, mode (`active`, `draining`, `fenced`), and activation policy for API, worker, and Agent. It is atomically replaced and schema/digest validated by each role.
- During the explicit `unmanaged_legacy` migration window only, absence of a controller admission document preserves the current role behavior and reports `admission_management=unmanaged`; it does not synthesize a generation or accept controller commands. In `managed` mode absence/corruption always fails closed. Task 8's approved template hard-codes managed mode, and contract tests reject any managed manifest/Compose containing the legacy escape.
- Backend middleware rejects new mutating work immediately in `draining`/`fenced`, counts in-flight requests without unbounded labels, and exposes a host-only machine JSON drain probe. Existing requests may finish only within a configured upper bound.
- Worker writes a heartbeat with image/build/manifest identity, admission generation, lease state, and last content-free result code. In `draining`, it claims no new outbox item and finishes or safely returns existing leases; in `fenced`, it performs no business work.
- Agent creation/claim is stopped through the 11A persistent kill/admission boundary. Existing runs finish or enter the 11A possible-charge/fencing terminal path within the specified bound; a run never resumes across application release identities.
- Host-only commands are exposed through the deployment entrypoint or protected filesystem protocol, not the public edge. They return stable JSON: `set-admission`, `probe-drain`, `probe-release`, and role-specific `probe-health`.
- Public `/api/health/ready` remains about the existing public application and database. A DeepSeek/Runtime fault does not make it falsely unavailable; release verification checks Agent safety separately.

- [ ] **Step 1: Write failing admission and drain unit tests**

Use a fake clock and atomic admission fixtures. Cover generation rollback, operation mismatch, torn/invalid files, `active → draining → fenced`, forbidden direct `fenced → active` for the wrong operation, concurrent request accounting, drain timeout, process restart, and content-free heartbeat fields. Assert a draining role claims no new work.

Cover the migration boundary separately: legacy Compose plus `unmanaged_legacy` starts with existing behavior and explicit unmanaged status; managed app Compose with missing document or any legacy flag refuses. No test treats unmanaged status as a healthy managed admission proof.

- [ ] **Step 2: Write failing worker and Agent integration tests**

Start long synthetic outbox and Agent work, enter draining, and prove no new item/run is claimed. Exercise successful completion, safe fencing, lease expiry, possible-charge, stale heartbeat, runtime-pointer mismatch, and CAS conflict when restoring source. Assert no old run crosses to a new manifest identity and no business pointer/data changes.

- [ ] **Step 3: Run the focused tests and observe missing controls**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/deployment/test_release_admission.py backend/tests/unit/test_health.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_drain.py backend/tests/integration/test_outbox_worker.py backend/tests/integration/test_agent_runtime_leases.py --require-mysql -v`

Expected: FAIL because controller-owned admission, request/worker drain, role heartbeat, and release-aware Agent fencing do not exist.

- [ ] **Step 4: Implement atomic admission and drain accounting**

Keep the document reader fail closed in server mode. Backend increments/decrements an in-memory in-flight counter around admitted requests, but mode truth remains controller-owned. Do not implement Docker control or release-state mutation in FastAPI. Worker/Agent heartbeats are content-free and bounded; do not persist task inputs, questions, answers, raw provider errors, or daily-data values.

- [ ] **Step 5: Integrate the 11A Agent and runtime-pointer boundaries**

Use existing append-only runtime versions, CAS current pointer, kill switch, leases, and possible-charge semantics. Add only application-release identity/fence fields and controller probes. A release drain must never issue a subsequent provider call after an unknown/possible charge and must not enable the Agent merely because the public app is active.

- [ ] **Step 6: Verify drain, timeout, restart, and readiness isolation**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/deployment/test_release_admission.py backend/tests/unit/deployment/test_entrypoint.py backend/tests/unit/test_health.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_drain.py backend/tests/integration/test_outbox_worker.py backend/tests/integration/test_agent_runtime_leases.py --require-mysql -v`

Expected: PASS; no new writer or Agent run appears after draining begins, bounded work reaches a provable terminal/fenced state, and simulated Agent provider failure leaves public readiness healthy while the Agent-specific probe reports its closed state.

- [ ] **Step 7: Commit release admission and drain controls**

```powershell
git add backend/app/deployment backend/app/main.py backend/app/worker backend/app/agent backend/app/agent_control backend/tests
git commit -m "feat: add release admission and drain controls"
```

### Task 6: Prove Database Graph Compatibility and Exact Schema Fingerprints

**Depends on:** P0; Task 2 for signed manifest vocabulary; Task 5 for role probes.

**Files:**
- Create: `release/compatibility/database-revisions.json`
- Create: `backend/app/deployment/database_compatibility.py`
- Create: `backend/app/deployment/schema_fingerprint.py`
- Create: `backend/tests/unit/deployment/test_database_compatibility.py`
- Create: `backend/tests/unit/deployment/test_schema_fingerprint.py`
- Create: `backend/tests/contracts/test_release_migration_compatibility.py`
- Create: `backend/tests/integration/test_release_database_compatibility.py`
- Modify: `backend/app/deployment/release_probe.py`
- Modify: `backend/app/deployment/entrypoint.py`
- Modify: `backend/tests/contracts/test_migration_contract.py`
- Modify: `backend/tests/integration/test_migrations.py`
- Modify: `scripts/test-mysql-matrix.ps1`
- Modify: `.github/workflows/compatibility.yml`

**Interfaces:**
- The signed compatibility document records an explicit Alembic DAG digest, per-release supported read/write revisions or closed compatible relations, planned target fingerprint, and protocol/session support. Code resolves the actual Alembic graph; it never orders opaque revision strings.
- `plan_database_transition(source_manifest, target_manifest, actual_revision, graph) -> CompatibilityPlan` returns exactly one of `no_migration`, `forward_expand`, or a closed refusal. The planned final revision must be supported by both target T and the operation-frozen source S.
- Expand/contract lint compares migration operations and declared compatibility. A normal window rejects deletion/rename, type narrowing, semantic enum removal, old view/trigger/permission removal, destructive data rewrite, and unclassified raw SQL unless a reviewed closed annotation and tests prove compatibility.
- `collect_schema_fingerprint(connection) -> SchemaFingerprint` canonically covers Alembic revision, tables/columns/types/nullability/defaults/indexes/constraints, views and definitions, view definers/security, triggers, routines used by the application, and exact grants for application/worker/reader/definer/migrator roles. Volatile metadata such as object creation timestamps is excluded by explicit policy.
- `release-probe` has two distinct modes: production `--read-only` verifies connection/revision/fingerprint/permissions/protocol without DML; isolated `--synthetic-canary` exercises create/review/validate/publish/dashboard/worker/Agent-safe contracts only on a disposable restored database and synthetic storage.

- [ ] **Step 1: Write failing graph and expand/contract tests**

Use a branched synthetic Alembic graph so string sorting gives the wrong answer. Cover direct support, approved forward path, missing/ambiguous head, merge revision, target-only support, source-only support, required downgrade, contract deletion/rename/narrowing, unclassified `op.execute`, and a valid two-release expand sequence. Verify the actual repository graph has one intended head and a signed digest.

- [ ] **Step 2: Write failing fingerprint tests with an independent oracle**

Create schema pairs differing only in a column default, index, constraint, view SQL, definer, trigger, or grant and require distinct fingerprints. Create equivalent schemas with different metadata ordering and require the same fingerprint. Reject partial/unknown inspection instead of omitting it. Ensure output contains identifiers/digests only and no row values.

- [ ] **Step 3: Write failing source/target canary and production no-write tests**

On a disposable MySQL database, run both synthetic S and T canaries against a planned post-migration schema. On a guarded production-shaped fixture, spy on SQL and reject any DML, publication pointer change, daily-data edit, note edit, or Agent provider call. Verify a read-only probe alone cannot create source recovery eligibility.

- [ ] **Step 4: Run focused tests and observe absent compatibility proof**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/deployment/test_database_compatibility.py backend/tests/unit/deployment/test_schema_fingerprint.py backend/tests/contracts/test_release_migration_compatibility.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_database_compatibility.py backend/tests/integration/test_migrations.py --require-mysql -v`

Expected: FAIL because graph planning, complete fingerprinting, compatibility documents, and separate read-only/canary probes do not exist.

- [ ] **Step 5: Implement deterministic graph planning and fingerprinting**

Build the graph through Alembic's revision map and compare nodes/paths, not strings. Validate that the manifest's graph digest equals the repository artifact used by the migrate image. Make fingerprint inspection transactional where supported but explicitly account for MySQL metadata and nontransactional DDL; unknown object/permission categories are refusal, not ignored drift.

- [ ] **Step 6: Implement probes and explicit MySQL matrix jobs**

Make both `.github/workflows/compatibility.yml` and `scripts/test-mysql-matrix.ps1` invoke the release compatibility/fingerprint files explicitly in MySQL 8.0 and 8.4 rather than relying on marker discovery. Add a contract assertion over the exact file list and fail on an unexpected skip. The synthetic canary creates its own clearly disposable records and asserts cleanup. It never accepts a production database name or storage path. Preserve the 11A one-shot migration privilege flow; do not add a second privileged migration route.

- [ ] **Step 7: Verify graph, fingerprint, and both MySQL versions**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/deployment/test_database_compatibility.py backend/tests/unit/deployment/test_schema_fingerprint.py backend/tests/contracts/test_release_migration_compatibility.py backend/tests/contracts/test_migration_contract.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_database_compatibility.py backend/tests/integration/test_migrations.py backend/tests/integration/test_database_constraints.py --require-mysql -v`

Run: `pwsh .\scripts\test-mysql-matrix.ps1`

Expected: local focused tests PASS on the configured disposable database. The matrix command must produce separate 8.0/8.4 evidence before this task is accepted; do not claim either version if that command was not actually run successfully.

- [ ] **Step 8: Commit database compatibility proof**

```powershell
git add release/compatibility/database-revisions.json backend/app/deployment backend/tests/unit/deployment backend/tests/contracts/test_release_migration_compatibility.py backend/tests/contracts/test_migration_contract.py backend/tests/integration/test_release_database_compatibility.py backend/tests/integration/test_migrations.py scripts/test-mysql-matrix.ps1 .github/workflows/compatibility.yml
git commit -m "feat: prove release database compatibility"
```

### Task 7: Split the Stable Base and Make Maintenance Edge Independent

**Depends on:** Tasks 5–6. This task must preserve the existing named volumes before any server transition.

**Files:**
- Create: `ops/docker-compose.base.yml`
- Create: `ops/nginx/edge.conf`
- Create: `ops/nginx/maintenance.html`
- Create: `ops/nginx/modes/app-upstream.conf`
- Create: `ops/nginx/modes/maintenance.conf`
- Create: `ops/release/Edge.psm1`
- Create: `ops/release/BaseMigration.psm1`
- Create: `backend/tests/contracts/test_release_compose.py`
- Create: `backend/tests/contracts/test_release_edge.py`
- Create: `backend/tests/integration/test_release_edge_modes.py`
- Modify: `ops/docker-compose.yml`
- Modify: `ops/nginx/default.conf`
- Modify: `backend/tests/contracts/test_server_deployment.py`
- Modify: `ops/verify-deployment.ps1`

**Interfaces:**
- Base project contains MySQL, exact existing persistent volumes/TLS/storage initialization, a stable edge, maintenance page, and external networks with fixed names. It contains no backend/frontend/worker/migrate/Agent dependency and can serve maintenance when every application container is absent.
- Infrastructure images are pinned by digest. Their update is a separate base-maintenance procedure, never selected from an application manifest.
- Existing volume names are discovered with `docker compose config`, `docker volume inspect`, and container mount facts; migration refuses if the planned external volume mapping is not exact. It never runs `down -v`, deletes, recreates, copies, or renames a data volume automatically.
- `Set-EdgeMode -Mode maintenance|app -OperationId <uuid> -ExpectedManifestDigest <digest>` performs: intent journal callback → write candidate to same protected filesystem → flush and atomic replace → `nginx -t` → reload → verify edge mode/response/upstream identity → completion callback. Failure retains or restores the last proven mode and never records completion.
- Maintenance page returns a fixed Chinese message and `Retry-After`, leaks no version/database/error detail, keeps `/edge-healthz` available, and makes public application readiness distinctly unavailable. A maintenance `200` cannot satisfy app readiness.

- [ ] **Step 1: Write failing structural Compose and volume-preservation tests**

Use the audited absolute Docker/Compose executable to produce `docker compose ... config --format json`, then validate that JSON with the locked schema/canonical tooling; do not add an undeclared YAML parser or download one at runtime. Assert base contains only approved stable roles; no app `depends_on`; external edge/data network names are fixed; volume names exactly match the current deployment mapping; no unpinned infrastructure image; and no destructive volume command in scripts/docs. Include an upgrade fixture of the current single project and make `-WhatIf` print the resolved mapping without mutating Docker.

- [ ] **Step 2: Write failing edge transaction tests**

Test candidate write failure, torn replace, bad Nginx config, `nginx -t` failure, reload failure, wrong actual response, wrong target identity, process interruption after each substep, and repeated invocation. Require last-proven mode or `manual_intervention`; never infer success from a config file alone.

- [ ] **Step 3: Run contracts and observe the current coupled deployment**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_release_compose.py backend/tests/contracts/test_release_edge.py backend/tests/contracts/test_server_deployment.py -m "not mysql and not deepseek_live" -v`

Expected: FAIL because the current single Compose uses movable/tag images, local application builds, non-external networks, and edge depends on application health.

- [ ] **Step 4: Build the stable base and non-secret maintenance page**

Move only stable services/contracts. Preserve current `mysql_data`, `mysql_tls`, `raw_data`, `backup_data`, `restore_data`, `backup_keyring`, and `edge_tls` identities through explicit external names. Do not mechanically run the migration against a real server in this task. Keep the legacy Compose operable until the signed baseline takeover rehearsal proves the new base.

- [ ] **Step 5: Implement atomic edge modes and disposable integration fixture**

Mount only the resolved protected mode file into stable Nginx. Test with a disposable Compose project and temporary TLS material. Stop/remove all disposable app containers and prove maintenance/edge health continues. Then start a synthetic app identity, switch to app, and prove external response binds the expected manifest.

- [ ] **Step 6: Verify config, edge failure behavior, and non-destructive migration preview**

Run: `docker compose -f ops/docker-compose.base.yml config --quiet`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_release_compose.py backend/tests/contracts/test_release_edge.py backend/tests/contracts/test_server_deployment.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_edge_modes.py -v`

Run: `pwsh -NoProfile -Command "Import-Module .\ops\release\BaseMigration.psm1 -Force; Test-BaseMigration -LegacyCompose .\ops\docker-compose.yml -BaseCompose .\ops\docker-compose.base.yml -WhatIf"`

Expected: PASS against disposable facts; preview reports exact planned external names and zero Docker/state mutation. Real-server base migration remains G2/G3 rehearsal work.

- [ ] **Step 7: Commit the stable base**

```powershell
git add ops/docker-compose.base.yml ops/docker-compose.yml ops/nginx ops/release/Edge.psm1 ops/release/BaseMigration.psm1 ops/verify-deployment.ps1 backend/tests/contracts backend/tests/integration/test_release_edge_modes.py
git commit -m "ops: split stable deployment base"
```

### Task 8: Render One Immutable Application Stack from One Verified Manifest

**Depends on:** Tasks 2, 4–5, and 7.

**Files:**
- Create: `ops/docker-compose.app.template.yml`
- Create: `ops/release/Contracts.psm1`
- Create: `ops/release/Docker.psm1`
- Create: `release/fixtures/application-compose-input.json`
- Create: `backend/tests/contracts/test_release_scripts.py`
- Create: `backend/tests/integration/test_release_compose_render.py`
- Modify: `backend/tests/contracts/test_release_compose.py`
- Modify: `.dockerignore`
- Modify: `backend/Dockerfile`
- Modify: `frontend/Dockerfile`
- Modify: `agent_runtime/Dockerfile`

**Interfaces:**
- `New-ReleaseApplicationCompose -VerifiedManifest <record> -OperationId <uuid> -Destination <protected-file>` first verifies the manifest's version-neutral template/renderer/schema digests, then renders a closed template to the protected operation directory; it accepts typed verified objects, not arbitrary environment-variable image strings. The rendered Compose digest is operation evidence only and is never a manifest field.
- The application project contains frontend, backend, worker, one-shot migrate, Agent control, Agent runtime, and any 11A mTLS/egress sidecars required by the manifest. Every declared role maps to an `image@sha256` from the same manifest, including worker/migrate roles that share a backend digest.
- `migrate` is in a non-default one-shot profile. No backend, worker, frontend, Agent, sidecar, or health service has `depends_on: migrate`, and normal target start uses an explicit long-lived-service allowlist with `--no-deps`. Only the controller's operation-bound step 12 may invoke the exact migrate service/image after `migration_started` intent and writer-fence proof.
- Labels include release version, manifest digest, source SHA, operation UUID, service role, and build identity. Runtime identity/admission mounts are read-only; rendered config contains Secret **names/mount targets only**, never values.
- Reject `build`, `latest`, tag-only references, digest/tag disagreement, cross-manifest role mixing, unknown service, omitted required role/platform, host PID/network escape, privileged mode, Docker socket, registry credentials, host release state, and unexpected writable/root capabilities.
- The signed application template fixes deployment mode to `managed`; it cannot render the `unmanaged_legacy` identity/admission compatibility mode. Its required identity/admission mounts and manifest labels cannot be omitted or overridden by environment interpolation.
- Dockerfiles pin every base image digest, use locked dependencies, non-root final roles, minimal build contexts, and contain no `.env`, release credentials, GitHub token, business file, backup/keyring, or controller module.

- [ ] **Step 1: Write failing renderer and Compose policy tests**

Create mutation fixtures for every forbidden key/reference and for one role digest from another manifest. Render a synthetic verified fixture to a temporary protected file, obtain `docker compose -f <rendered> config --format json` through the audited executable, and validate that JSON structurally with locked JSON/schema code; do not parse YAML with an undeclared module. Prove the source template cannot be deployed directly, is version/manifest/operation independent, and can render two different final manifests. Prove a shared backend digest still has explicit `backend`, `worker`, and `migrate` role bindings, while migrate is outside the default profile and no long-lived service depends on it. Verify secret canaries never occur in renderer arguments, output, labels, Compose JSON, or exception text.

- [ ] **Step 2: Write failing Docker image-content contracts**

Require pinned base digests and lockfiles, non-root runtime, read-only-compatible filesystem, declared build identity, exact role entrypoints, `.dockerignore` exclusion, and absence of repository docs/tests/raw/business files in final layers. Extend `.dockerignore` (or an equivalently tested exact BuildKit named-context whitelist) so `docs`, private/table data, backend/frontend tests/results, host scripts not required at runtime, `.env*`, Git metadata, controller state, and credentials cannot enter application build contexts; keep only files explicitly required by each multi-stage build. Test the actual context inventory and final layers. Test that no application container mounts Docker socket, controller state, registry helper, receipt credential, or migration administrator credential except the one-shot 11A-controlled migrate role's narrowly scoped Secret set.

- [ ] **Step 3: Run the contracts and observe mutable current deployment inputs**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_release_compose.py backend/tests/contracts/test_release_scripts.py backend/tests/contracts/test_server_deployment.py -m "not mysql and not deepseek_live" -v`

Expected: FAIL because immutable app template/renderer do not exist and current Dockerfiles/base references are not all digest pinned.

- [ ] **Step 4: Implement typed rendering and hardened images**

PowerShell schema validation must use the same canonical golden vectors as Python; do not silently reinterpret numbers or duplicate keys. Render with explicit YAML scalar escaping, then validate the audited Compose JSON projection and exact service/profile/dependency graph. Verify every image's resolved RepoDigest after pull/start. Put the generated frontend/runtime identity JSON in a read-only operation file, not an image layer or command-line argument.

- [ ] **Step 5: Verify rendering and disposable role startup**

Run: `pwsh -NoProfile -Command "Import-Module .\ops\release\Docker.psm1 -Force; New-ReleaseApplicationCompose -Fixture .\release\fixtures\application-compose-input.json -Destination \"$env:TEMP\clsen-app-render.yml\"; docker compose -f \"$env:TEMP\clsen-app-render.yml\" config --format json | Out-Null"`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_release_compose.py backend/tests/contracts/test_release_scripts.py backend/tests/contracts/test_server_deployment.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_compose_render.py -v`

Expected: PASS with synthetic local-registry digests; the raw template is non-deployable, the rendered JSON graph contains no implicit migrate dependency, each explicitly started long-lived role reports the same final manifest identity, and canary scans of arguments/config/logs/layers are empty. This is not yet signed GHCR supply-chain evidence.

- [ ] **Step 6: Commit immutable application rendering**

```powershell
git add ops/docker-compose.app.template.yml ops/release/Contracts.psm1 ops/release/Docker.psm1 release/fixtures/application-compose-input.json .dockerignore backend/Dockerfile frontend/Dockerfile agent_runtime/Dockerfile backend/tests/contracts backend/tests/integration/test_release_compose_render.py
git commit -m "ops: render immutable release application stacks"
```

### Task 9: Build Verifiable OCI Artifacts and Supply-Chain Evidence

**Depends on:** Tasks 1–2, 6, and 8. Only isolated artifact validation is enabled here; real GHCR/application publication additionally requires G1 and Task 18.

**Files:**
- Create: `.github/workflows/release.yml`
- Create: `.github/workflows/controller-base-release.yml`
- Create: `release/toolchain.lock.json`
- Create: `release/schemas/release-build-descriptor.schema.json`
- Create: `release/schemas/controller-base-inventory.schema.json`
- Create: `release/policies/release-publication-policy.json`
- Create: `release/policies/controller-base-inventory.json`
- Create: `tools/releases/supply_chain.py`
- Create: `tools/releases/build_release_descriptor.py`
- Create: `tools/releases/build_controller_base_bundle.py`
- Create: `tools/tests/test_release_supply_chain.py`
- Create: `backend/tests/security/test_release_image_contents.py`
- Modify: `backend/tests/contracts/test_release_workflows.py`
- Modify: `backend/tests/contracts/test_release_compose.py`
- Modify: `release/policies/trusted-release-identities.json`
- Modify: `release/policies/release-security-policy.json`
- Modify: `.github/workflows/compatibility.yml`

**Interfaces:**
- `release.yml` is eligible only after the stable `release-required` check for an in-repository `push` to protected `master` succeeds. It checks event kind, repository ID, head repository, exact `master` ref, source SHA, workflow path/identity, conclusion, and fresh G1 audit. A PR, fork, non-master branch, manual SHA override, or stale/missing audit receives no tag, package, OIDC, attestation, or Release write.
- A closed signed publication policy starts with `real_application_publication_enabled=false` and `controller_base_publication_enabled=false`. Before Task 18, application jobs may build/test only in a credential-isolated disposable namespace and must make zero writes to real GHCR, application/catalog refs, or GitHub Releases even when G1 passes. Task 18 is the only planned commit that may enable real application publication, in the same change that makes every-boundary recovery jobs required. Task 11 may enable the independent controller/base workflow only after its full inventory and installer contracts exist.
- Release jobs check out and rebuild the exact protected source SHA in a clean workspace; they never promote a PR image or consume an untrusted executable artifact. The source tree/locked dependencies and generated build context digest are included in provenance.
- `release/toolchain.lock.json` pins every supply-chain executable/action/container by reviewed version, full commit/digest, source repository, checksum, and approved update process. Installation verifies checksums before execution and never searches current directory or writable PATH.
- Initial production platform is explicit in policy (for example `linux/amd64` when that is the audited server platform); do not silently publish or claim another architecture. Each role/platform output is referenced by OCI digest.
- For each component, produce a locked build, SPDX or CycloneDX SBOM, SLSA-compatible provenance/attestation, vulnerability result, image-content/Secret scan, and Sigstore-compatible signature bundle. Every evidence subject digest, build identity, source SHA, workflow identity, and final OCI digest must cross-match.
- Define a separate create-only `controller-base-v1.N` version axis and protected `controller-base-release.yml` workflow. Once Task 11 enables it, the workflow allocates its own ordinal and packages only the explicit paths in the schema-validated `controller-base-inventory.json`; filename globs are discovery aids and never the authority. The initial inventory covers the reviewed controller entrypoints/modules, stable base Compose/Nginx/configuration, and required policy/schema files, and later tasks must update it for every new runtime entrypoint or transitive dependency. The workflow emits and signs/attests an exact canonical file-digest and entrypoint/dependency-closure inventory from protected `master` with a dedicated workflow identity. It binds source SHA, host platform, configuration version, and minimum/maximum controller-state schema; it contains no runtime state or credential. A controller/base upgrade never rides inside an application manifest or consumes a `v11A.1.N` ordinal.
- Critical findings and policy-blocking High findings refuse publication. A security exception is accepted only when its signed structured owner/reason/expiry/affected-digest record validates; expiry is rechecked by the catalog and server.
- Images and OCI referrers are initially addressable by source/build identity and immutable digest. This task emits a closed `clsen.release-build-descriptor.v1` containing only version-independent component/template/renderer/evidence inputs. It has no ordinal/version/final-manifest digest, cannot enter the catalog, and is never deployable. No application release version or final manifest is approved in this task; Task 10 allocates the ordinal only after all evidence is complete.

- [ ] **Step 1: Write failing workflow trust and permission tests**

Parse every workflow job and event branch. Assert no release-capable job runs for PR/fork/non-master/manual source input; `workflow_run` or equivalent completion data is fully matched; `cancel-in-progress` cannot interrupt final publication; each job has the minimum explicit permissions; and a package/signing job never receives production database, backup, session, DeepSeek, or server credentials.

- [ ] **Step 2: Write failing subject-binding and image-content tests**

Use synthetic OCI descriptors and bundles. Mutate a layer, platform manifest, role mapping, source SHA, Compose template/renderer/schema digest, SBOM subject, provenance builder identity, signature certificate identity, scan subject, exception expiry, one controller/base file digest, state-schema compatibility, or bundle file inventory and require rejection. Assert a pre-ordinal descriptor cannot validate as a release manifest or catalog entry. Scan extracted final layers and the controller/base bundle for `.env`, Git metadata, raw/business fixtures, tokens, private keys, runtime state, and package credentials.

- [ ] **Step 3: Run contracts and observe the missing supply chain**

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests/test_release_supply_chain.py backend/tests/contracts/test_release_workflows.py backend/tests/contracts/test_release_compose.py backend/tests/security/test_release_image_contents.py -m "not mysql and not deepseek_live" -v`

Expected: FAIL because release workflow, toolchain lock, OCI evidence binding, and image-content gates do not exist.

- [ ] **Step 4: Implement the protected build and evidence graph**

Use audited full-SHA Actions or checksum-verified pinned binaries only. Re-run build-specific locked dependency, image, Compose, and no-network tests from the exact source. Generate SBOM/provenance before signing, attach them as digest-addressed OCI referrers where supported, and persist only the closed build descriptor for Task 10. Implement controller/base canonical packing, inventory verification, independent ordinal/signature/provenance logic, and protected workflow, but keep its real publication flag false until Task 11 supplies the complete controller inventory. This task must not generate or sign an application release manifest.

Do not place registry/signing tokens in arguments, build args, layers, environment dumps, artifacts, or logs. Use GitHub's short-lived job credential/OIDC only in the job that requires it. Prove the signing certificate identity matches the exact audited repository/workflow/ref/SHA policy, not a broad regular expression.

- [ ] **Step 5: Make the complete protected test set a publication prerequisite**

Require the offline backend/Runtime suite, MySQL 8.0/8.4, N/N-1 migration/compatibility, frontend lint/type/unit/browser build, container hardening, backup v2/restore contracts, Agent isolation, and release subject-binding gates. Do not treat skipped MySQL/container/browser jobs as success. Later Task 18 adds the full release recovery gate to this same prerequisite graph before production support is declared.

- [ ] **Step 6: Verify locally with synthetic descriptors and no real publication**

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests/test_release_supply_chain.py backend/tests/contracts/test_release_workflows.py backend/tests/contracts/test_release_compose.py backend/tests/security/test_release_image_contents.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m tools.releases.supply_chain verify-fixture --manifest release/fixtures/application-compose-input.json --policy release/policies/release-security-policy.json`

Expected: PASS for repository-local synthetic fixtures and every tamper vector. The application and controller publication flags remain false, production-capable fake adapters record zero write calls, and a build descriptor is not deployable. Do not claim GHCR push, production signing identity, vulnerability status, MySQL matrix, or G1 unless their real protected workflow evidence exists.

- [ ] **Step 7: Commit verifiable artifact production**

```powershell
git add .github/workflows release/toolchain.lock.json release/policies release/schemas/release-build-descriptor.schema.json release/schemas/controller-base-inventory.schema.json release/schemas/controller-base-bundle.schema.json tools/releases tools/tests/test_release_supply_chain.py backend/tests/contracts backend/tests/security/test_release_image_contents.py
git commit -m "ci: build verifiable release artifacts"
```

### Task 10: Allocate Immutable Ordinals and Define Atomic Approved Publication

**Depends on:** Tasks 3 and 9; only isolated protocol validation is enabled here. Real application publication requires G1 and Task 18; real ledger records require G1 and a caller implemented in Task 15.

**Files:**
- Create: `.github/workflows/release-catalog.yml`
- Create: `tools/releases/publish.py`
- Create: `tools/releases/build_release_manifest.py`
- Create: `tools/releases/deployment_ledger.py`
- Create: `.github/workflows/deployment-ledger.yml`
- Create: `tools/tests/test_deployment_ledger.py`
- Create: `tools/releases/github_client.py`
- Create: `tools/tests/test_release_publish.py`
- Create: `tools/tests/test_release_publish_concurrency.py`
- Modify: `.github/workflows/release.yml`
- Modify: `release/policies/release-publication-policy.json`
- Modify: `release/policies/github-repository-policy.json`
- Modify: `tools/releases/versioning.py`
- Modify: `tools/releases/catalog.py`
- Modify: `backend/tests/contracts/test_release_workflows.py`
- Modify: `release/policies/trusted-release-identities.json`

**Interfaces:**
- Final publication runs in a repository-wide concurrency group with `cancel-in-progress: false`. It uses GitHub's create-ref conflict semantics as the atomic ordinal claim; it never implements “read maximum then force-write.”
- All historical `refs/tags/v11A.1.N`, including refs with no approved Release, occupy their integer forever. A failed publication leaves a permanent gap. Re-running a SHA with an existing approved release verifies exact immutable manifest/evidence equality and exits idempotently; a SHA whose earlier claimed ordinal failed receives a new ordinal after a full rebuild/recheck.
- Before ordinal allocation, validate the Task-9 build descriptor and prove every required component/evidence is complete and digest-addressed. After claiming `v11A.1.N` at the exact source SHA, this task is the **only** final-manifest generation point: insert the claimed ordinal/version, bind the version-neutral template/renderer/schema and exact OCI/evidence subjects, canonicalize/sign once, publish immutable subjects, and prepare a GitHub Release. A descriptor or pre-ordinal record is never accepted as a final manifest.
- Until Task 18 changes `real_application_publication_enabled` in its single reviewed commit alongside the required recovery-workflow dependency graph, all production GitHub/GHCR/ref/Release adapters remain structurally unreachable and contract tests require zero writes; Task-10 external validation uses only an isolated namespace/identity. G1 alone does not override this implementation-completeness gate.
- A draft Release is CI-private and never considered approved. Upload/verify immutable assets or digest links while draft, then make it non-draft and non-prerelease as the last release-visibility step. If finalization fails, the tag remains occupied and no approved record exists.
- Catalog generations use their own protected immutable namespace, such as `release-catalog-v1.N`, and the same create-only/no-delete rule. The workflow builds the next canonical catalog from the last valid chain, adds the new application release as `approved`, signs it with the catalog workflow identity, and publishes it. A GitHub Release without a current valid catalog entry is auditable but not deployable.
- Catalog publication is idempotent by intended transition digest. Conflict, concurrent invocation, missing previous generation, incomplete Release, or signature failure never rewrites a tag/catalog/Release.
- Define the shared create-only ledger primitive used later by Task 15: protected `deployment-ledger.yml` accepts only a bounded signed closed record from the dedicated dispatcher identity, independently verifies environment/operation/sequence/prior digests, re-reads all protected ledger refs, and atomically claims exactly `refs/tags/deployment-ledger/<environment>/<fixed-width-next-sequence>` through create-ref conflict semantics. Record digest stays only in the signed tag message, so two different records for one sequence contend on the identical ref; one wins and the other receives conflict then re-reads. The fixed-width encoding preserves lexical/integer order, while validators still strictly parse and bound the integer. Prefer the narrowest available `workflow_dispatch`; do not assume GitHub can scope `Actions: write` to one workflow. G1 must inventory every workflow the host actor can trigger and prove none offers arbitrary ref/package/Release/code execution. The ledger job's `contents: write` token is untrusted outside its intended call: a complete branch/tag ruleset matrix plus disposable positive/negative API tests must prove it can create only this exact fixed-width tag grammar and cannot update/delete those refs or create/write `master`, another branch/tag namespace, Release, package, environment rule, or workflow. Oversized records fail before a ref write; no external asset is used. If GitHub's actual permission/ruleset model cannot enforce and evidence this split—including no bypass actor—stop for a design amendment or purpose-built append-only service; real hold/receipt use is blocked and no fallback Deployments API is allowed.

- [ ] **Step 1: Write failing allocator and idempotency tests**

Cover empty history, gaps, integer 9/10 ordering, malformed historical refs, two concurrent publishers, create-ref conflict, same-SHA approved replay, same-SHA failed claim, finalization failure, attempted tag update/delete, pre-ordinal descriptor misuse, and publication flag false. For the ledger primitive, cover fixed-width 9/10 lexical and integer ordering, wrong width/leading sign/overflow, two different digests contending on the identical environment+sequence ref, dispatcher scope overreach, non-ledger actor, sequence/prior-head mismatch, workflow attempt outside its namespace, ref update/delete, and exact replay. Use a deterministic fake GitHub server which records methods, permissions, refs, drafts, releases, and assets. With the flag false, application production endpoints must receive zero calls.

- [ ] **Step 2: Write failing atomic Release/catalog tests**

Terminate after each operation: tag claim, manifest signing, OCI upload, draft creation, asset upload, draft verification, Release publication, catalog tag claim, and catalog publication. At every point assert the server's deployable list contains either the old catalog or the complete new release—never a partially approved version. Require a gap after failed claim and no deletion/number reuse.

- [ ] **Step 3: Run tests and observe missing publisher semantics**

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests/test_release_publish.py tools/tests/test_release_publish_concurrency.py tools/tests/test_deployment_ledger.py backend/tests/contracts/test_release_workflows.py -v`

Expected: FAIL because atomic ref allocation, idempotent publisher, draft-to-approved boundary, and catalog workflow are absent.

- [ ] **Step 4: Implement create-only publication through a narrow GitHub client**

Expose only required read/list/create operations. Do not implement force-update or delete methods in the release client. Validate repository numeric ID and response subjects on every call. Treat rate limits, ambiguous network outcomes, and duplicate responses as recoverable unknowns: re-read facts and compare canonical digests before any retry.

- [ ] **Step 5: Implement chained catalog publication and external protection check**

Before any ref/package write, re-run G1 policy audit and signature identity checks. Add the catalog tag namespace to ruleset documentation/audit. The catalog workflow can approve/revoke/archive/retain only closed transitions generated from typed inputs; arbitrary JSON/free-text status payload is rejected. Publish the signed next generation only after every referenced manifest/Release/referrer is independently readable by digest.

- [ ] **Step 6: Verify concurrency and crash points without touching GitHub**

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests/test_release_publish.py tools/tests/test_release_publish_concurrency.py tools/tests/test_deployment_ledger.py tools/tests/test_release_catalog.py backend/tests/contracts/test_release_workflows.py -v`

Expected: PASS against the fake server, including one winning ordinal under concurrency, permanent gaps, immutable approved replay, and old-catalog safety at every crash point. This does not prove real repository rulesets or publication.

- [ ] **Step 7: Commit atomic approved publication**

```powershell
git add .github/workflows/release.yml .github/workflows/release-catalog.yml .github/workflows/deployment-ledger.yml tools/releases tools/tests/test_release_publish.py tools/tests/test_release_publish_concurrency.py tools/tests/test_deployment_ledger.py backend/tests/contracts/test_release_workflows.py release/policies
git commit -m "ci: publish immutable approved releases"
```

**External isolated validation after this commit and G1:** Run the committed workflow only with the repository owner's approved isolated package/ref/Release namespace and test signing identity while real application publication remains disabled. Save source SHA, claimed test ordinal(s), manifest/catalog digests, workflow identity, and closed results. Require a non-destructive update attempt on an occupied test ref to fail; never delete an existing application/catalog ref for testing. Any code/config fix creates a new commit and invalidates the earlier evidence. This validation proves only the isolated atomic protocol, not real application publication or production support.

### Task 11: Secure the Host Controller and Verify Catalog/Artifact Trust

**Depends on:** Tasks 3 and 10. Tests use fixed local signed fixtures; installation/real catalog access requires G2.

**Files:**
- Create: `ops/release.ps1`
- Create: `ops/install-release-controller.ps1`
- Create: `ops/release/HostSecurity.psm1`
- Create: `ops/release/Credentials.psm1`
- Create: `ops/release/Catalog.psm1`
- Modify: `ops/release/Contracts.psm1`
- Create: `ops/release/Logging.psm1`
- Create: `backend/tests/contracts/test_release_host_security.py`
- Create: `backend/tests/contracts/test_release_catalog_client.py`
- Create: `backend/tests/security/test_release_secret_leakage.py`
- Create: `release/fixtures/host-trust-policy.json`
- Modify: `backend/tests/contracts/test_release_scripts.py`
- Modify: `docs/operations/github-release-trust-prerequisites.md`
- Modify: `.github/workflows/controller-base-release.yml`
- Modify: `tools/releases/build_controller_base_bundle.py`
- Modify: `release/policies/release-publication-policy.json`
- Modify: `release/policies/controller-base-inventory.json`
- Modify: `backend/tests/contracts/test_release_workflows.py`

**Interfaces:**
- Installation accepts a signed controller/base bundle, verifies it out of place, resolves a dedicated non-service local OS identity, creates `C:\ProgramData\CLSEN\ReleaseController` with explicit protected owner/ACL/no unsafe inheritance, and writes an approved hash policy. The controller cannot self-approve changed script/base hashes.
- The secure-boundary bundle inventory becomes usable only after this task's controller, installer, stable-base, Nginx, schemas, and policy files exist. `controller-base-inventory.json` declares exact entrypoints plus closed recursively enumerated module/config roots and required individual schemas/policies; the builder resolves this into a canonical sorted path/digest inventory and rejects an entrypoint whose static imports, dot-sourced scripts, declared subprocess scripts, schema reads, or locked auxiliary tool dependency is outside that closure. Later tasks may extend the inventory only in the same reviewed commit that introduces a new runtime entrypoint/dependency; any extension creates a new controller/base version and invalidates older G2 evidence. `controller-base-release.yml` then changes only `controller_base_publication_enabled` to true, builds from a clean protected-master checkout, allocates a separate create-only `controller-base-v1.N`, signs/attests the canonical inventory with its dedicated workflow identity, and publishes it independently of application releases. Contract tests reject missing/extra/unresolved controller files and prove application `v11A.1.N` manifests cannot select or update this bundle.
- Installer verifies the bundle's canonical manifest/signature/attestation against the dedicated protected workflow identity, exact source SHA, immutable bundle digest, host platform, and state-schema compatibility before trusting its file hashes. It rejects old-generation replay below the last accepted installer generation, mixed-version/extra/missing files, archive traversal/reparse entries, partial extraction, and interrupted installation. Installation stages to a sibling protected directory, flushes/verifies it, atomically activates the new controller/base pointer, and retains the last verified configuration bundle for controller/base rollback; rollback never touches MySQL or persistent data volumes.
- Runtime preflight checks caller identity, owner, ACL, reparse-point/path containment, file hashes, PowerShell version, absolute tool paths and tool hashes, Docker context/endpoint, protected state/credential paths, and server environment marker before loading a mutating module.
- Auxiliary executables (`docker`, Compose plugin, signature verifier, GitHub client if used, Nginx control path) are invoked by approved absolute path. A same-name binary in CWD, repository, user-writable PATH, alias, function, or PowerShell profile is ignored; commands run `-NoProfile -NonInteractive` where applicable.
- `Credentials.psm1` retrieves a dedicated repository/package reader, receipt writer, and optional receipt-signing material from Windows Credential Manager/DPAPI-backed store or an equivalently audited OS facility. Secrets are passed through stdin/in-memory headers/protected handles, never argv, Compose, environment dump, transcript, journal, manifest, SBOM, or application container.
- All registry/catalog/hold/receipt clients pin an allowlisted HTTPS host, repository numeric ID, and audited trust policy; set bounded connect/read timeouts and response-size limits; reject plaintext, host/certificate mismatch, unexpected content type, and every HTTPS-to-HTTP or cross-host redirect. Authorization is never forwarded to a redirected host. Tests use malicious redirect, DNS/Host mismatch, oversized-response, timeout, and ambiguous-response fixtures and scan process/network captures for credential canaries.
- `Catalog.psm1` discovers immutable catalog generation Releases, downloads canonical bytes/signature bundles to an operation temp directory, verifies exact trusted repository/workflow/ref/SHA identity and chain, then resolves the application Release/manifest and OCI subjects. It does not trust a mutable “latest” tag or display tag.
- A fresh read path never updates `last accepted`, cache, or journal. Mutating deploy/initialize code persists accepted generation/digest later through Task 12. `list` may use an already persisted stale snapshot only with `stale=true`; no other command can plan/deploy from stale data.
- Structured logs accept a fixed field enum and stable reason codes. Unknown object/string payloads are rejected or reduced to a closed code; exceptions are not serialized wholesale.

- [ ] **Step 1: Write failing ACL, caller, hash, and path-hijack tests**

Create temporary safe/unsafe directory trees with wrong owner, inherited write access, symlink/junction/reparse escape, changed controller hash, unapproved PowerShell profile, fake `docker`/signature/GitHub tools in CWD and PATH, wrong Docker context, and non-release caller. Add valid and invalid signed controller/base bundles covering workflow/source mismatch, rollback replay, mixed/missing/extra file, archive traversal, incompatible state schema, independent-version-axis violation, and interruption before/after activation. Assert refusal happens before credential retrieval, Docker, state mutation, or base activation, and rollback changes configuration only.

- [ ] **Step 2: Write failing catalog/signature/credential tests**

Use a local TLS fixture and test signing key/bundle. Cover valid chain; catalog rollback/gap/expiry; wrong issuer/repository/workflow/ref/SHA/subject; moved application tag; manifest/SBOM/provenance/layer tamper; cross-host/downgrade redirect; host/certificate mismatch; oversized/ambiguous response; stale list; and inspect/WhatIf failure. Spy network requests, process argv/stdin/logs, and application container config for registry/receipt/DB canaries.

- [ ] **Step 3: Run host contracts and observe missing security boundary**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_release_host_security.py backend/tests/contracts/test_release_catalog_client.py backend/tests/contracts/test_release_scripts.py backend/tests/security/test_release_secret_leakage.py -m "not mysql and not deepseek_live" -v`

Expected: FAIL because the dedicated installer, host validation, credential provider, signature-verifying catalog client, and allowlisted logging do not exist.

- [ ] **Step 4: Implement a non-self-updating controller installation boundary**

Keep installation separate from `release.ps1`. Refuse repository/workspace roots as state/credential/render destinations. On Windows, query canonical SIDs and explicit access rules, not localized display names. Require only the dedicated identity and explicit break-glass administrators to write; application service identities and ordinary users have no read access to credential/controller state. Never change ACL recursively outside the exact resolved controller root. Validate the signed bundle and its entire extracted inventory out of place, then atomically switch a protected current-bundle pointer; do not let a locally edited hash-policy file bless itself.

- [ ] **Step 5: Implement strict catalog, signature, OCI, and log validation**

Share the canonical golden vectors from Task 2 through PowerShell contract tests. Verify bytes before deserialization into trusted records, then verify every transitive digest and signature subject. Do not pull an image merely to inspect an unverified target. Use `docker manifest`/registry read APIs for descriptors first; actual pulls happen in deploy after disk planning. Scrub process output through a field allowlist and fail the Secret-canary acceptance test on any match.

- [ ] **Step 6: Verify host security with fake tools and signed fixtures**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_release_host_security.py backend/tests/contracts/test_release_catalog_client.py backend/tests/contracts/test_release_scripts.py backend/tests/security/test_release_secret_leakage.py -m "not mysql and not deepseek_live" -v`

Expected: PASS with approved fixture tools; every hijack/tamper is rejected before a side effect and captured output contains zero canaries. This is not G2 proof for the real server.

- [ ] **Step 7: Commit the secure host controller boundary**

```powershell
git add ops/release.ps1 ops/install-release-controller.ps1 ops/release .github/workflows/controller-base-release.yml tools/releases/build_controller_base_bundle.py release/policies/release-publication-policy.json release/policies/controller-base-inventory.json backend/tests/contracts/test_release_host_security.py backend/tests/contracts/test_release_catalog_client.py backend/tests/contracts/test_release_scripts.py backend/tests/contracts/test_release_workflows.py backend/tests/security/test_release_secret_leakage.py release/fixtures/host-trust-policy.json docs/operations/github-release-trust-prerequisites.md
git commit -m "ops: secure the host release controller"
```

**Provisional G2 action after this commit:** Let protected `master` generate a signed controller/base bundle from this exact committed SHA. On the target-equivalent host, run the committed installer's `-WhatIf`, review exact paths/SIDs/hashes/Docker context, then install that exact bundle under the dedicated identity. Prove the registry identity can read only approved digests and cannot push/delete/ref-update/Release-write; prove hold/receipt identity cannot write packages/refs/releases. Save only bundle source SHA/digest/inventory digest plus ACL/owner/hash/caller/result codes. This evidence authorizes only this exact bundle for interim implementation/rehearsal preparation. Any later bundle-inventory or dependency-graph change in Tasks 12–19 invalidates it; the final Task-19 bundle must repeat the complete G2 procedure before G3/G4. Any fix requires a new committed/signed bundle and a full rerun.

### Task 12: Add Durable Journal, Derived State, Lock Order, and Strictly Read-Only Commands

**Depends on:** Tasks 6, 8, and 11; P0 supplies the final 11A backup/migration scripts.

**Files:**
- Create: `ops/release/Journal.psm1`
- Create: `ops/release/State.psm1`
- Create: `ops/release/Locks.psm1`
- Create: `ops/release/Status.psm1`
- Create: `backend/tests/contracts/test_release_journal.py`
- Create: `backend/tests/contracts/test_release_read_only_commands.py`
- Create: `backend/tests/integration/test_release_state_reconciliation.py`
- Modify: `ops/release.ps1`
- Modify: `ops/release/Catalog.psm1`
- Modify: `ops/release/Docker.psm1`
- Modify: `scripts/backup.ps1`
- Modify: `scripts/restore-verify.ps1`
- Modify: `ops/migrate-with-definer-privilege.ps1`
- Modify: `scripts/test-mysql-matrix.ps1`
- Modify: `ops/verify-deployment.ps1`
- Modify: `backend/tests/contracts/test_maintenance_scripts.py`
- Modify: `backend/tests/contracts/test_release_scripts.py`

**Interfaces:**
- The append-only journal is one operation directory containing create-once, ordered canonical entry files. Each entry has format, sequence, previous-entry digest, operation UUID, event, durable state/result, actor SID, UTC time, and an allowlisted evidence object/digest. Creation uses a same-filesystem temporary file, full file flush, atomic create/rename without overwrite, and directory durability where the platform supports it. A missing/gap/duplicate/reordered/torn/hash-invalid entry fails closed.
- Every side effect later writes `<effect>_intent` before execution and `<effect>_completed` only after independently verifying the actual effect. Intent without completion means “possibly occurred,” never “did not occur.” Terminal `committed`, `aborted`, and `rolled_back` entries are immutable. `manual_intervention` remains a blocking state for the same operation rather than permission for a new deploy.
- Derived `current.json`, `previous.json`, last-accepted catalog, and operation index are rebuildable caches. Each uses write/flush/atomic replace and embeds the journal tip digest. On drift/corruption, read-only status reports `recovery_required` or `manual_intervention`; it never repairs state implicitly.
- Deployment lock order is `host deployment lock → database maintenance barrier → operation-specific backup/migration/restore lock`. Lock evidence includes purpose, actor SID, process start identity, operation UUID, heartbeat, and journal tip. A dead process/stale heartbeat cannot be deleted by `deploy`; only `recover` may reconcile and take over the same operation after fact verification.
- A top-level mutating command creates a protected, random, single-operation **lease capability** bound to host-lock generation, operation UUID, owner SID/process-start identity, journal tip, command purpose, expiry/heartbeat, and an HMAC or OS-protected digest stored only under the controller ACL. Child backup/restore/migration processes never reacquire or release the host lease. They receive a protected capability handle/path, verify exact parent ownership and current journal tip, acquire only their permitted database/sublock, and return without changing the parent lease. Wrong/forged/replayed capability, different operation/tip/owner, duplicate top-level acquire, expired heartbeat, or dead parent fails closed.
- Standalone backup, restore verification, one-shot migration, and base maintenance use the same lock-order module but acquire their own top-level host lease only when no parent capability is supplied. Supplying both a parent capability and standalone-acquire mode is invalid. They wait or safely refuse a release conflict; no path takes locks in reverse order or allows a child to outlive/release a dead parent's logical ownership.
- `list`, `inspect`, `status`, `history`, and `deploy -WhatIf` run a read-only dispatcher which cannot import mutating functions. Side-effect spies must observe zero lock creation/takeover, credential/cache/journal/state write, image pull, backup, container change, admission update, edge reload, migration, or receipt.
- `initialize -Version ... -WhatIf` performs a read-only G3 comparison. The mutating form is allowed exactly once, only with no prior journal/state and exact equality among approved signed manifest, actual component RepoDigests/labels, runtime pointer, database fingerprint/revision, configuration schema, and app edge identity. It records a genesis current without stopping or rebuilding anything. A local build/tag or partial match is never adoptable.
- Target equals current is an idempotent read-only result. If any nonterminal operation exists, all informational commands return it as `recovery_required`; a new deploy/initialize is refused.

- [ ] **Step 1: Write failing journal and atomic-state tests**

Cover ordered append, concurrent append, duplicate sequence, gap, reordered entry, previous-digest mismatch, torn final file, half-written derived state, terminal rewrite, unknown field/event, oversized/log-content value, clock anomaly, and rebuild of a deliberately deleted derived snapshot. Assert corrupted evidence is reported without modifying the fixture.

- [ ] **Step 2: Write failing lock-order and maintenance-script tests**

Model deploy/deploy, deploy/backup, deploy/restore, backup/migration, stale process ID reuse, old heartbeat, wrong operation takeover, and reversed database/sublock acquisition. Add nested deploy→backup→restore-proof and deploy→migration cases which inherit the exact protected capability without a second top-level acquire or deadlock; cover forged/replayed/wrong-operation/wrong-tip capabilities, child attempt to release the parent lease, and parent death while a child is running. Instrument existing scripts so a test records acquisitions and proves the fixed partial order. No test deletes or mutates a real host lock.

- [ ] **Step 3: Write failing read-only and baseline-takeover tests**

Invoke all commands against fake Docker/GitHub/filesystem/DB adapters whose mutating methods throw. Test fresh/stale/no catalog, damaged state, running operation, target=current, and every single baseline mismatch. Capture filesystem snapshots, process calls, network methods, Docker calls, and lock paths before/after; they must be identical for read-only commands and `-WhatIf`.

- [ ] **Step 4: Run contracts and observe missing durable state**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_release_journal.py backend/tests/contracts/test_release_read_only_commands.py backend/tests/contracts/test_release_scripts.py backend/tests/contracts/test_maintenance_scripts.py -m "not mysql and not deepseek_live" -v`

Expected: FAIL because journal/state/lock modules, read-only dispatcher, unified maintenance lease, and signed-baseline adoption are absent.

- [ ] **Step 5: Implement durable journal/state and fixed lock ordering**

Use canonical entry bytes and create-once filesystem semantics. Do not “repair” a partial journal by truncating or skipping entries; report the exact closed corruption code. Validate process start time as well as PID to avoid PID reuse. Make heartbeat writes atomic and distinguish OS mutex release from durable logical ownership. Issue lease capabilities through `Locks.psm1` only after the parent lease/journal is durable; child scripts validate but cannot mint or release them. Standalone backups can queue for the deployment lease or return a closed busy result; a deploy child inherits the exact parent and never bypasses or reacquires it.

- [ ] **Step 6: Implement pure read commands and exact baseline adoption**

Keep read adapters/interfaces separate so PowerShell's `SupportsShouldProcess` is defense in depth, not the only `-WhatIf` guarantee. `status` compares journal/state against actual RepoDigests/labels, edge response/mode, admission generation, Agent pointer, fence facts, and database revision/fingerprint. On G3 initialization, validate a fresh catalog and full local/offline artifact proof before writing one genesis intent/completion/state set.

- [ ] **Step 7: Verify journal, locks, read-only commands, and reconciliation**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_release_journal.py backend/tests/contracts/test_release_read_only_commands.py backend/tests/contracts/test_release_scripts.py backend/tests/contracts/test_maintenance_scripts.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_state_reconciliation.py -v`

Expected: PASS; state rebuild matches the journal tip, conflict/unknown facts fail closed, read-only spies show zero mutation, every maintenance path follows the same lock order, and nested deploy backup/restore/migration completes without self-deadlock while the parent lease remains continuously owned.

- [ ] **Step 8: Commit durable host state and commands**

```powershell
git add ops/release.ps1 ops/release scripts/backup.ps1 scripts/restore-verify.ps1 ops/migrate-with-definer-privilege.ps1 scripts/test-mysql-matrix.ps1 ops/verify-deployment.ps1 backend/tests/contracts backend/tests/integration/test_release_state_reconciliation.py
git commit -m "ops: add durable release state and commands"
```

### Task 13: Gate Every Release on Backup v2, Isolated Migration, and Dual-Version Proof

**Depends on:** P0 backup format v2; Tasks 6 and 12.

**Files:**
- Create: `ops/release/BackupRestore.psm1`
- Create: `ops/release/Database.psm1`
- Create: `backend/tests/contracts/test_release_backup_gate.py`
- Create: `backend/tests/integration/test_release_isolated_migration.py`
- Create: `backend/tests/integration/test_release_disk_preflight.py`
- Modify: `backend/app/maintenance/backup.py`
- Modify: `backend/app/maintenance/restore.py`
- Modify: `backend/app/maintenance/cli.py`
- Modify: `backend/app/deployment/release_probe.py`
- Modify: `backend/app/deployment/database_compatibility.py`
- Modify: `scripts/backup.ps1`
- Modify: `scripts/restore-verify.ps1`
- Modify: `ops/migrate-with-definer-privilege.ps1`
- Modify: `backend/tests/unit/maintenance/test_backup.py`
- Modify: `backend/tests/unit/maintenance/test_restore.py`
- Modify: `backend/tests/contracts/test_maintenance_scripts.py`
- Modify: `backend/tests/integration/test_backup_write_barrier.py`
- Modify: `backend/tests/integration/test_backup_key_rotation.py`

**Interfaces:**
- `Get-ReleaseDiskPlan` computes a conservative peak before any image pull or maintenance: currently running/base layers not safely reclaimable, complete frozen source cache and referrers, complete target layers/referrers, temporary pull/unpack overhead, new encrypted backup, decrypt verification workspace, isolated MySQL data/storage restore, migration/canary workspace, journal reserve, and configured safety reserve. Unknown image/backup size or insufficient free space refuses before a side effect.
- Each deploy creates a **new** 11A-format-v2 encrypted backup under its operation UUID. The controller invokes the existing machine JSON CLI, checks allowed fields only, and binds backup UUID, manifest/artifact digest, key ID (never key), source database revision/fingerprint, operation UUID, time, and verification result into journal evidence.
- A successful backup gate includes authenticated decryption of every artifact and a fresh restore to a cryptographically random database name and isolated storage directory under configured test-only roots. Production database/storage paths and broad workspace roots are refused. Cleanup never follows an unresolved link/reparse point and never targets a path outside the exact operation root.
- The target manifest's exact migrate image digest upgrades only that isolated restored copy along the Task-6 forward plan. Then verify planned Alembic revision, complete schema/grant/view-definer/trigger fingerprint, backup-v2 restoration canaries, and absence of unclassified/partial migration state.
- Execute target T and frozen source S synthetic read/write canaries against the **post-migration isolated copy** with their exact image/build/runtime identities. Canaries use generated synthetic records only and prove create/import/review/validate/publish/read/dashboard/worker plus Agent safe-disabled/declared state without contacting DeepSeek. Record result/digest, never row content.
- Source automatic-recovery eligibility is a four-part evidence object bound to the operation: signed compatibility relation; isolated post-migration S read/write canary; actual production post-migration fingerprint; and S image's production no-write probe. This task forms the isolated part; Tasks 15–16 add fresh production facts. None of the four can substitute for another.
- Migration authority remains the 11A `grant → positive verify → exact migrate digest → finally revoke → reverse verify` flow. A reverse-verification failure is a release failure even when Alembic returned success. The controller never owns or receives the administrator credential.
- Production database downgrade and automatic backup overwrite/restore functions are absent from ordinary controller adapters and counted as zero calls in tests.

- [ ] **Step 1: Write failing disk, backup, and path-safety tests**

Cover exact-fit/under-reserve space, unknown compressed/unpacked size, shared layers, partial local source cache, multi-arch/referrer size, backup growth, restore workspace, registry interruption, encrypted artifact mutation, wrong key ID, authentication/decrypt failure, backup schema mismatch, predictable database name, production-name/path collision, traversal/reparse escape, and cleanup interruption. Assert every pre-maintenance refusal leaves source serving and journal/current/business data unchanged.

- [ ] **Step 2: Write failing isolated migration and S/T canary tests**

Use a freshly encrypted synthetic backup. Cover no-migration, valid expand, target-only compatibility, source-only compatibility, required downgrade, planned fingerprint mismatch, grant/definer/trigger drift, restore canary failure, T canary failure, S canary failure, wrong image digest, wrong Agent bundle pointer, and provider-network attempt. Assert no connection to the production database and no production storage write.

- [ ] **Step 3: Run focused tests and observe the missing release gate**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_release_backup_gate.py backend/tests/contracts/test_maintenance_scripts.py backend/tests/unit/maintenance/test_backup.py backend/tests/unit/maintenance/test_restore.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_disk_preflight.py backend/tests/integration/test_release_isolated_migration.py backend/tests/integration/test_backup_write_barrier.py backend/tests/integration/test_backup_key_rotation.py --require-mysql -v`

Expected: FAIL because release-specific disk planning, operation-bound backup/restore proof, target-image isolated migration, and dual-image canaries are absent.

- [ ] **Step 4: Implement conservative disk planning and backup-v2 orchestration**

Query registry descriptors and local Docker content facts without pulling target layers. Treat deduplication only when digest/platform/storage-driver evidence proves it; otherwise count the full object. Call the existing backup/restore CLI through absolute approved paths and parse strict JSON, not human log text. Never extend backup v2 by weakening exact table classification, encryption authentication, keyring isolation, or restored-data canaries.

- [ ] **Step 5: Implement isolated target migration and both image canaries**

Create a per-operation disposable Compose/network/database/storage namespace with no public edge and no production credentials. Pull/verify both complete target and frozen source sets before maintenance. Run target migrate by digest against the isolated DB, then start T canary roles; tear them down and start S canary roles against the same migrated DB. Block external sockets/provider calls. Hash the closed canary result and cleanup inventory, not the synthetic values.

- [ ] **Step 6: Prove temporary migration privileges always converge**

Inject failure before grant, after grant, after positive verification, during Alembic, after Alembic, during revoke, and during reverse verification. The `finally` path always attempts revoke; only a successful closed reverse check satisfies the gate. An unknown/revocation failure remains a blocking result for later operator remediation and never proceeds to production maintenance.

- [ ] **Step 7: Verify backup, restore, compatibility, and MySQL versions**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_release_backup_gate.py backend/tests/contracts/test_maintenance_scripts.py backend/tests/unit/maintenance/test_backup.py backend/tests/unit/maintenance/test_restore.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_disk_preflight.py backend/tests/integration/test_release_isolated_migration.py backend/tests/integration/test_backup_write_barrier.py backend/tests/integration/test_backup_key_rotation.py --require-mysql -v`

Run: `pwsh .\scripts\test-mysql-matrix.ps1`

Expected: focused and matrix evidence PASS on disposable MySQL 8.0/8.4. `scripts/test-mysql-matrix.ps1` explicitly names `test_release_disk_preflight.py` and `test_release_isolated_migration.py`, rejects unexpected skips, and the gate proves source continues serving for all pre-maintenance failures. Backup/restore/migration/canary artifacts are operation-bound and downgrade/production-restore call counts are zero. Do not report the matrix if it did not actually run.

- [ ] **Step 8: Commit the backup and isolated compatibility gate**

```powershell
git add ops/release/BackupRestore.psm1 ops/release/Database.psm1 backend/app/maintenance backend/app/deployment scripts/backup.ps1 scripts/restore-verify.ps1 scripts/test-mysql-matrix.ps1 ops/migrate-with-definer-privilege.ps1 backend/tests
git commit -m "ops: gate releases on isolated migration proof"
```

### Task 14: Hold and Recover a Verifiable MySQL Writer Fence

**Depends on:** P0; Tasks 5, 8, and 12–13. This task does not yet execute production DDL.

**Files:**
- Create: `backend/app/maintenance/fence_holder.py`
- Create: `backend/app/maintenance/fence_protocol.py`
- Create: `backend/tests/unit/maintenance/test_fence_protocol.py`
- Create: `backend/tests/integration/test_release_fence_holder.py`
- Create: `backend/tests/integration/test_release_lock_order.py`
- Modify: `backend/app/maintenance/barrier.py`
- Modify: `backend/app/maintenance/health.py`
- Modify: `backend/app/maintenance/cli.py`
- Modify: `backend/app/deployment/entrypoint.py`
- Modify: `backend/tests/unit/maintenance/test_barrier.py`
- Modify: `backend/tests/integration/test_backup_write_barrier.py`
- Modify: `backend/tests/integration/test_file_ingest.py`
- Modify: `backend/tests/integration/test_admin_management_api.py`
- Modify: `ops/release/Database.psm1`
- Modify: `ops/release/Locks.psm1`
- Modify: `ops/docker-compose.app.template.yml`
- Modify: `backend/tests/contracts/test_release_compose.py`
- Modify: `scripts/database-privileges.json`
- Modify: `scripts/init-database.ps1`
- Modify: `scripts/sync-test-runtime-grants.ps1`
- Modify: `scripts/test-mysql-matrix.ps1`
- Modify: `ops/mysql/init-users.sh`
- Modify: `ops/docker-compose.base.yml`
- Modify: `.env.example`
- Modify: `backend/tests/contracts/test_database_bootstrap_script.py`
- Modify: `backend/tests/contracts/test_test_grant_sync_script.py`
- Modify: `backend/tests/contracts/test_server_deployment.py`

**Interfaces:**
- Bootstrap provisions two TLS-only, noninteractive identities with independent generated Secrets: `clsen_release_fence` for the holder and `clsen_release_observer` for independent content-free fact collection. `.env.example`, local bootstrap, container init, base Compose Secrets, test grant synchronization, deployment verification, and privilege manifest all declare the same closed contract. Neither Secret is mounted into backend, worker, frontend, Agent, migrate, backup, restore, or application test roles; only the operation-bound fence-holder receives the fence Secret, and only the host-side approved verifier receives the observer credential through its protected handle.
- `clsen_release_fence` receives only `SELECT` on the singleton `maintenance_write_barrier` table plus the exact named-lock capability verified necessary on both MySQL 8.0 and 8.4; it receives no INSERT/UPDATE/DELETE, schema-wide grant, DDL, migration, backup, user/grant administration, or global nonessential privilege. `clsen_release_observer` is distinct so the holder cannot broaden itself: grant the minimum performance-schema/sys/process metadata reads actually demonstrated necessary to map connection ID, account/program attributes, server UUID, named-lock ownership, and unknown sessions. If MySQL 8.0/8.4 requires a narrowly scoped global privilege such as `PROCESS`, document the exact reason/result fields and prove no SQL text, bind value, business row, credential, or unrelated session content is returned. Unsupported least-privilege parity is a blocking design amendment, not a reason to reuse root/migrator/app.
- The controller starts one dedicated `fence-holder` role from an approved backend/migration image with `clsen_release_fence` and no public network. It receives operation UUID and protected protocol/status file handles, not arbitrary SQL or credentials on argv.
- On **one physical MySQL connection**, the holder verifies server/database identity, obtains the existing named maintenance lock, starts a transaction, locks singleton `maintenance_write_barrier` `FOR UPDATE`, and freezes MySQL `CONNECTION_ID()`, server UUID, operation UUID, process start identity, holder build/image identity, lock names, acquired timestamp, and heartbeat sequence.
- Acquisition completion is valid only after the controller independently confirms: all source backend/worker/Agent/migrate/restart policies are stopped/disabled; no app/worker/Agent DB sessions remain; holder PID/build/image/operation matches; named lock owner equals the frozen connection ID; barrier row lock blocks a test-only application writer; and no unknown writer identity is connected. This verification happens before DDL.
- Heartbeats contain no Secret or business data and prove the same process/connection identity. A live PID with a changed connection, missing heartbeat, server UUID change, or lock-owner mismatch is loss of fence, not reacquisition.
- Release is an authenticated local controller request bound to operation UUID/journal intent and accepted exactly once. On the **same connection**, holder commits or rolls back the barrier transaction as protocol dictates, invokes `RELEASE_LOCK`, verifies its return value, queries ownership evidence, writes a final response, flushes, and exits. The controller independently verifies `IS_USED_LOCK` no longer names this connection/operation and no residual barrier owner before recording completion.
- Holder/controller disappearance, MySQL restart, socket loss, release-intent without completion, or ambiguous response never counts as release completion. Recovery reads actual lock/session/schema facts and chooses a Task-16 closed path.
- The migration role uses a distinct narrow identity/connection which deliberately bypasses the normal application shared-row acquisition but cannot operate without controller-held host lease and fence evidence. No other role may bypass the barrier.

- [ ] **Step 1: Write failing protocol and same-connection unit tests**

Use fake connection/process transports to cover acquire order, connection ID freeze, heartbeat sequence, duplicate/reordered command, wrong operation/authentication, release before acquire, reconnect, commit/release return failure, write/flush failure, and exact terminal response. Assert the implementation cannot transparently reconnect or reacquire under the same operation.

- [ ] **Step 2: Write failing MySQL ownership and writer-blocking tests**

Against disposable MySQL, start normal application writers, drain/stop them, acquire the holder, and prove named-lock plus row-lock identity. Attempt writes through backend, worker, ingest, publication, admin, Agent/control, `clsen_release_fence`, `clsen_release_observer`, and a deliberately unknown test account. Known application writers must be absent/blocked; both release identities must have zero business DML/DDL; an unknown connected writer causes controller refusal. Verify migrate identity can execute only the planned fixture operation while holder remains unchanged. Compare exact grants and content-free observer fields on MySQL 8.0 and 8.4 and fail on any extra/global privilege or Secret mount.

- [ ] **Step 3: Write failing crash-boundary tests**

Kill the holder after named-lock acquisition, after row acquisition, after acquisition response, after release intent, after transaction release, after `RELEASE_LOCK`, and before final response. Separately kill controller and restart MySQL. Assert no missing holder/connection is treated as completed, target activation stays fenced, edge stays maintenance, and recovery evidence distinguishes definitely held/released/unknown.

- [ ] **Step 4: Run tests and observe that the current context manager is insufficient**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/maintenance/test_fence_protocol.py backend/tests/unit/maintenance/test_barrier.py backend/tests/contracts/test_release_compose.py backend/tests/contracts/test_database_bootstrap_script.py backend/tests/contracts/test_test_grant_sync_script.py backend/tests/contracts/test_server_deployment.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_fence_holder.py backend/tests/integration/test_release_lock_order.py backend/tests/integration/test_backup_write_barrier.py backend/tests/integration/test_file_ingest.py backend/tests/integration/test_admin_management_api.py --require-mysql -v`

Expected: FAIL because the current backup context manager has no durable process/connection identity, heartbeat, authenticated release protocol, or crash reconciliation.

- [ ] **Step 5: Implement the dedicated holder without weakening backup barriers**

Factor low-level acquire/verify/release primitives from `barrier.py` only where safe; keep the normal application's shared barrier behavior and backup context semantics. The holder owns a raw dedicated connection and disables pooling/reconnect. Status/protocol files use protected handles, canonical closed records, sequence/digest checks, and create/atomic semantics. Never log DSNs, SQL parameter values, or connection credentials.

Provision/rotate both identities through the existing idempotent bootstrap and explicit privilege-manifest flow. Positive and reverse tests compare `SHOW GRANTS`/metadata to the closed expected set and confirm revoked/deleted extras; no script queries a nonexistent `information_schema.ROUTINE_PRIVILEGES` table. Container entrypoint and local/test synchronizers must produce equivalent identities without printing passwords.

- [ ] **Step 6: Implement controller-side independent ownership verification**

`Database.psm1` queries MySQL through the approved `clsen_release_observer` no-content verifier and compares only allowlisted server UUID, connection ID, named lock owner, session account/program/operation attributes, and heartbeat. It does not accept the holder's self-report alone and never exposes SQL text or business content. Lock-order tests prove host deployment lease precedes holder acquisition and remains held until the operation reaches a terminal result.

- [ ] **Step 7: Verify on MySQL 8.0 and 8.4 with crash injection**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/maintenance/test_fence_protocol.py backend/tests/unit/maintenance/test_barrier.py backend/tests/contracts/test_release_compose.py backend/tests/contracts/test_database_bootstrap_script.py backend/tests/contracts/test_test_grant_sync_script.py backend/tests/contracts/test_server_deployment.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_fence_holder.py backend/tests/integration/test_release_lock_order.py backend/tests/integration/test_backup_write_barrier.py backend/tests/integration/test_file_ingest.py backend/tests/integration/test_admin_management_api.py --require-mysql -v`

Run: `pwsh .\scripts\test-mysql-matrix.ps1`

Expected: PASS on both supported MySQL versions, including killed-holder/controller/server cases. `scripts/test-mysql-matrix.ps1` explicitly names `test_release_fence_holder.py` and `test_release_lock_order.py`, checks the exact file set, and rejects every unexpected skip. Exact grants show zero business DML/DDL and no unnecessary global privilege for either release identity. At every unknown ownership point, application writes/activation and migration continuation are forbidden; no test assumes transactional DDL rollback.

- [ ] **Step 8: Commit the verifiable writer fence**

```powershell
git add backend/app/maintenance backend/app/deployment/entrypoint.py ops/release/Database.psm1 ops/release/Locks.psm1 ops/docker-compose.app.template.yml ops/docker-compose.base.yml ops/mysql/init-users.sh scripts/database-privileges.json scripts/init-database.ps1 scripts/sync-test-runtime-grants.ps1 scripts/test-mysql-matrix.ps1 .env.example backend/tests
git commit -m "ops: hold a verifiable deployment writer fence"
```

### Task 15: Execute the Complete 20-Step Single-Slot Deploy Transaction

**Depends on:** Tasks 7–8, 10, and 12–14. G1/G2/G3 are required before a real server deploy.

**Files:**
- Create: `ops/release/Transaction.psm1`
- Create: `ops/release/Preflight.psm1`
- Create: `ops/release/Receipt.psm1`
- Create: `ops/release/CentralOperation.psm1`
- Modify: `.github/workflows/deployment-ledger.yml`
- Modify: `tools/releases/deployment_ledger.py`
- Modify: `tools/tests/test_deployment_ledger.py`
- Modify: `release/policies/github-repository-policy.json`
- Modify: `release/policies/trusted-release-identities.json`
- Modify: `backend/tests/contracts/test_release_workflows.py`
- Create: `backend/tests/contracts/test_release_transaction.py`
- Create: `backend/tests/contracts/test_release_central_operation.py`
- Create: `backend/tests/integration/test_release_controller.py`
- Create: `backend/tests/integration/test_release_normal_deploy.py`
- Modify: `ops/release.ps1`
- Modify: `ops/release/Journal.psm1`
- Modify: `ops/release/State.psm1`
- Modify: `ops/release/Docker.psm1`
- Modify: `ops/release/Edge.psm1`
- Modify: `ops/release/Database.psm1`
- Modify: `ops/release/BackupRestore.psm1`
- Create: `ops/verify-release-deployment.ps1`
- Modify: `backend/tests/contracts/test_release_scripts.py`
- Modify: `backend/tests/integration/test_published_analytics.py`

**Interfaces:**
- `deploy -Version <strict-version>` implements exactly these durable completion states in order: `requested`, `catalog_verified`, `compatibility_planned`, `artifacts_prepared`, `target_preflight_passed`, `backup_verified`, `isolated_compatibility_verified`, `maintenance_entered`, `work_drained`, `source_stopped_and_writer_fenced`, `migration_started`, `migration_verified`, `source_recovery_verified`, `target_started_fenced`, `target_verified_fenced`, `writer_fence_released`, `target_activated`, `traffic_restored`, `commit_recorded`, then `committed` or `committed_pending_receipt`.
- Every state with a side effect has a specific intent event and an independently verified completion event. The transition table is data/closed code, not scattered string comparisons. A missing prerequisite or unexpected event is refusal.
- The central deployment authority is a protected, create-only **Git annotated-tag ledger**, not GitHub Deployments or an assumed custom service. The host sends the signed canonical `register`, `renew`, or terminal `close-with-receipt` record only to protected `deployment-ledger.yml`. That workflow validates the complete chain, claims the next global per-environment sequence with Git create-ref conflict semantics, and publishes `deployment-ledger/<environment>/<fixed-width-sequence>` with the bounded signed record/digest directly in the annotated-tag message. The sequence-only ref name ensures competing transitions collide rather than creating digest-suffixed sibling refs. Each record binds the prior environment head and operation record, so every environment transition—across operations—is a single auditable chain. The host identity can dispatch/read only; it cannot write any ref or Release. The workflow identity can create only this namespace. G1 rulesets prohibit update/delete of every ledger ref for all ordinary/admin actors without silent bypass. If the exact create-only/write-once split cannot be proven from fresh GitHub settings and a non-destructive refusal test, real deploy/retention stays disabled; do not substitute the deletable Deployments API or an external asset.
- Idempotency key is `(environment_id, operation_uuid, transition_kind, sequence, record_digest)`. `register` requires no currently open operation; `renew` and `close` require the exact open operation, unchanged S/T roots, and next operation sequence. Every transition also requires the next environment sequence and prior environment-head digest. Create-ref conflict causes a full re-read: identical record is idempotent; a competing valid record, sequence fork/gap, missing protected ref or annotated tag object/message, duplicate sequence with different digest, or ambiguous dispatch/read-back blocks deploy and **all central GC** until reviewed. Expiry never deletes or unprotects an open hold: an expired unclosed record remains a protected root and global-GC pause until an acknowledged signed terminal close exists.
- After `compatibility_planned` freezes S/T and **before any image/referrer pull or other artifact preparation**, deploy journals hold-registration intent, dispatches the signed record, exhaustively re-lists the protected tag refs and annotated tag objects/messages, and continues only when the exact digest is the unique valid environment tip. It renews with strictly increasing operation/environment sequences and prior digests before expiry throughout long backup, migration, and recovery work and performs the same full read-back. Before maintenance, failure, timeout, stale list, fork, or ambiguous dispatch safely aborts with source still serving. After maintenance starts, an unknown renewal/close result never restores traffic or permits cleanup by assumption: the operation remains locally blocking/safe, retries only the identical dispatch after read-back, and central GC globally pauses on stale/ambiguous/forked hold/receipt facts.
- Steps 1–7 happen while the healthy source remains admitted and on edge. Artifacts include complete verified target and frozen source images/referrers/config/runtime bundle in local protected cache. Target preflight has no production writer credential or public edge.
- `maintenance_entered` is a durable composite, not a cross-resource atomic action. Fixed order is: edge-maintenance intent → Task-7 atomic mode transaction including `nginx -t`, reload, and external maintenance response proof → admission-draining intent → controller document update → backend/worker/Agent generation acknowledgements → state completion. Every subeffect has its own intent/completion. If edge succeeds and admission fails, public traffic remains on maintenance; if edge fails, admission is not changed. Recovery reconciles an incomplete subeffect from facts and never claims the two resources changed atomically. `work_drained` then requires bounded proofs for HTTP/DB writes, worker leases, and Agent runs. Timeout restores source admission then app edge in explicit verified subtransactions only while source is running and the database fingerprint is unchanged; otherwise it remains maintenance.
- Step 10 disables source restart policies, stops every source writer/Agent role then frontend, verifies no source/unknown DB sessions, and acquires/verifies Task-14 fence. MySQL/base/edge/controller remain running.
- Step 11 journals migration intent, current/plan fingerprints, target migrate digest, and privilege-flow evidence **before** invoking migration. Step 12 runs the exact target digest and verifies actual revision/fingerprint/grants/definers/triggers plus reverse privilege convergence while the independent holder remains unchanged.
- Step 13 creates fresh source-recovery eligibility from all four evidence parts. Step 14 starts the only app slot as target with application admission still `fenced`, using an explicit long-lived-role allowlist and `--no-deps`; neither this nor any later `up` can select the migrate profile. Step 15 checks exact RepoDigests/labels/runtime pointer, database and authorization no-write probes, worker/Agent paused state, HTTPS/internal protocols, and public-readiness/Agent isolation. The sole migrate invocation occurred in step 12 after its intent; call-sequence evidence proves migrate/DDL count was zero before then and remains one operation-bound invocation.
- Step 16 journals release intent then commands the same fence-holder to release, independently verifies release, and records completion. Unknown release remains maintenance. Step 17 atomically activates target roles internally while edge remains maintenance; step 18 restores edge and verifies public release/browser handshake.
- Step 19 records `current=target`, `previous_stable=source_release` only after target traffic is independently healthy. Operation-start previous stays in immutable history. Step 20 sends one canonical terminal `close-with-receipt` record whose single signed meaning both records terminal/current/previous/database evidence and closes the exact open hold; create-ref is the one visibility boundary, not a claimed GitHub transaction across resources. The transition is idempotent by operation UUID/receipt digest. `committed`, `aborted`, and `rolled_back` all require that exact close record to be the acknowledged environment-chain tip. A network-unknown close after local target commit becomes `committed_pending_receipt`; it does **not** roll a healthy target back and keeps root protection logically active until read-back proves closure. `manual_intervention` remains an open protected hold and is never terminally closed.
- Target equals current returns an idempotent read-only result. Deploying an older version uses the same transaction; if it requires database downgrade or lacks post-migration source/target compatibility, it refuses before maintenance.
- Ordinary deploy never changes daily-data publication pointers, site-configuration versions, raw-file digests, notes, or business rows. Production probes are read-only. Synthetic writes occur only in the isolated copy.

- [ ] **Step 1: Write failing pure state-transition and command-surface tests**

Enumerate all 20 states, allowed predecessor, required intent, evidence fields, and terminal outcomes. Test skipped/repeated/out-of-order transition, intent without completion, terminal rewrite, target=current, old compatible target, downgrade target, revoked/archived/expired target, stale catalog, nonterminal prior operation, forbidden parameters, and wrong operation/source. Against a deterministic fake ledger-dispatch/ref/Release API, add hold register/renew/close schemas, canonical asset round trip, repository/environment mismatch, missing pagination page, identical replay, operation/environment sequence or prior-digest gap/rollback, chain fork, changed roots, expired-unclosed hold, concurrent environment operation, forbidden ref update/delete or non-ledger namespace write, malicious redirect, dispatch/read-back ambiguity, and terminal close linearization with GC. Assert no public `FailAfter`/`Skip*`/`Force*` test switch.

- [ ] **Step 2: Write failing normal no-migration and expand integration tests**

With a temporary registry/test signature, disposable central hold/receipt authority, MySQL/storage/state directory, and synthetic base/app stacks, exercise baseline S→T without migration and S→T with one expand migration. Assert hold acknowledgement before the first artifact pull, monotonically renewed protection, exact state/effect order, source traffic through step 7, stable maintenance through steps 8–17, exact fence identity through steps 10–16, target identity at step 18, current/previous only at step 19, and one acknowledged unique terminal `close-with-receipt` record. Kill at every maintenance composite substep; also prove no migrate container/DDL before step 12 and no second invocation during target start.

- [ ] **Step 3: Write failing compatible historical-version and receipt tests**

Deploy T, then select signed older S which supports current D without downgrade. Prove DB revision never decreases, old application passes isolated/read-only compatibility, and the same full gates execute. Inject only ledger-dispatch/read-back failure after commit; assert target remains healthy, state is `committed_pending_receipt`, new deploy is blocked, and no migration/container/edge replay occurs on identical close-record retry.

- [ ] **Step 4: Run focused tests and observe the missing transaction**

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests/test_deployment_ledger.py backend/tests/contracts/test_release_workflows.py backend/tests/contracts/test_release_transaction.py backend/tests/contracts/test_release_central_operation.py backend/tests/contracts/test_release_scripts.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_controller.py backend/tests/integration/test_release_normal_deploy.py backend/tests/integration/test_published_analytics.py --require-mysql -v`

Expected: FAIL because the normal 20-step transaction, exact effect journaling, central hold lifecycle, activation ordering, and unique terminal receipt/hold-close boundary are absent.

- [ ] **Step 5: Implement pre-maintenance steps and bounded maintenance entry**

Freeze source from journal plus actual facts before accepting target. Obtain fresh catalog and plan graph compatibility, then register/read back the signed central hold before preparing complete source/target. Run target preflight and consume Task-13 backup/isolation proof while renewing the same hold. Only then enter maintenance through the ordered edge/admission composite. Any pre-maintenance failure closes an `aborted` receipt/hold only after proving no maintenance effect; if central registration/renewal/close is unknown, stop safely with source serving and block cleanup/new deploy until the same operation is reconciled. Drain failure may restore admission then edge only after rechecking source health and unchanged DB fingerprint.

- [ ] **Step 6: Implement fenced migration, target validation, traffic, and commit**

Follow the specified order without `finally` blocks that blindly restore traffic or release locks. Start migrate only by the explicit operation-bound service invocation after migration intent; start long-lived target roles from a closed allowlist with `--no-deps`. At every exception, append only known facts/result code and invoke no ad hoc rollback. Task 16 will route classifiable synchronous failures through the same closed recovery engine; process/host interruption leaves the operation for explicit same-operation `recover`. Do not infer health from container `running`, maintenance `200`, Compose project name, or state cache; compare exact digests/labels/probes and actual edge response.

- [ ] **Step 7: Implement content-free receipt and pending behavior**

Build a canonical terminal receipt from journal evidence, sign/authorize it with the separate ledger-dispatch identity, and submit it as the single signed close record for the exact hold, idempotently by operation UUID/receipt digest. Store only ledger sequence/tip, hold digest, and receipt digest/status/attempt metadata. Bound retries/read-back with backoff; do not move healthy target traffic for a post-commit audit-network failure. Refuse new deploy/prune while pending, and let central GC pause while the hold or receipt is nonfresh/ambiguous.

- [ ] **Step 8: Verify normal upgrade, compatible older release, and invariants**

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests/test_deployment_ledger.py backend/tests/contracts/test_release_workflows.py backend/tests/contracts/test_release_transaction.py backend/tests/contracts/test_release_central_operation.py backend/tests/contracts/test_release_scripts.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_controller.py backend/tests/integration/test_release_normal_deploy.py backend/tests/integration/test_published_analytics.py --require-mysql -v`

Expected: PASS on the disposable fixture for no-migration, expand, and compatible older-version deploy. Every test asserts DB downgrade calls are zero and pre/post business publication pointer, site-config version, raw digest, daily-data digest, and notes are unchanged. This is not production-support evidence until Tasks 16, 18, and 19 pass.

- [ ] **Step 9: Commit the normal release transaction**

```powershell
git add ops/release.ps1 ops/release ops/verify-release-deployment.ps1 .github/workflows/deployment-ledger.yml tools/releases/deployment_ledger.py tools/tests/test_deployment_ledger.py release/policies/github-repository-policy.json release/policies/trusted-release-identities.json backend/tests/contracts/test_release_workflows.py backend/tests/contracts/test_release_transaction.py backend/tests/contracts/test_release_central_operation.py backend/tests/contracts/test_release_scripts.py backend/tests/integration/test_release_controller.py backend/tests/integration/test_release_normal_deploy.py backend/tests/integration/test_published_analytics.py
git commit -m "ops: execute transactional single-slot releases"
```

### Task 16: Recover Interrupted Operations with a Closed Decision Table

**Depends on:** Task 15.

**Files:**
- Create: `ops/release/Recovery.psm1`
- Create: `ops/release/RecoveryTable.psd1`
- Create: `backend/tests/contracts/test_release_recovery_table.py`
- Create: `backend/tests/integration/test_release_failure_recovery.py`
- Create: `backend/tests/integration/test_release_partial_ddl_recovery.py`
- Create: `backend/tests/integration/test_release_receipt_recovery.py`
- Modify: `ops/release.ps1`
- Modify: `ops/release/Transaction.psm1`
- Modify: `ops/release/Journal.psm1`
- Modify: `ops/release/State.psm1`
- Modify: `ops/release/Database.psm1`
- Modify: `ops/release/Edge.psm1`
- Modify: `ops/release/Receipt.psm1`
- Modify: `ops/release/CentralOperation.psm1`
- Modify: `backend/tests/contracts/test_release_transaction.py`
- Modify: `backend/tests/contracts/test_release_central_operation.py`
- Modify: `backend/tests/integration/test_release_controller.py`
- Modify: `.github/workflows/compatibility.yml`
- Modify: `scripts/test-mysql-matrix.ps1`

**Interfaces:**
- `recover -OperationId <uuid>` accepts only an existing nonterminal/pending operation and the original frozen source/target. It cannot choose another target, create a new operation UUID, substitute operation-start `previous_stable`, or change a terminal entry.
- Before choosing an action, recovery verifies the full journal chain/intent-completion pairs, derived state tip, lock/caller facts, the exact central hold digest/latest monotonic sequence/expiry/read-back status, actual edge mode/response, application RepoDigests/labels/restart policies/admission, Agent runtime pointer/runs, holder PID/heartbeat/connection/lock ownership, database server UUID/revision/complete fingerprint/privileges/sessions, backup/restore/isolated canary proof, source-recovery evidence, and receipt facts.
- Recovery never registers a replacement hold, changes environment/operation/S/T, or resets a sequence. Before **any** recovery side effect it reads back the same central record and renews it with exactly `next_sequence`, then reads back that digest. An expired-but-still-present hold may be renewed only through this monotonic transition; definitively missing, conflicting, or ambiguous evidence after maintenance keeps stable maintenance and becomes `manual_intervention`. Before maintenance, a definitively absent hold permits only safe local abort while source serves and globally pauses cleanup until reconciled. Long-lived `manual_intervention` and `committed_pending_receipt` continue monotonic renewals and keep source/target roots protected. Recovery terminally closes only this same hold with the decision-table receipt; an ambiguous close retries/read-backs the identical receipt digest and never sends a different terminal result.
- `RecoveryTable.psd1` is a closed machine-readable encoding of design section 14.2. Each rule declares required last proven state/intents/facts, allowed effects, successful result, and otherwise `manual_intervention`. Unknown/conflicting evidence has no default recovery action.
- `requested` through `isolated_compatibility_verified`: cleanup only operation-scoped temporary artifacts; source/current/previous/DB/edge stay unchanged; result `aborted` only after the exact acknowledged unique terminal `close-with-receipt` record. Unknown close keeps a locally blocking pending state and central deletion paused.
- `maintenance_entered`/`work_drained` while source is running and fingerprint unchanged: restore source admission, verify source, atomically restore edge; result `aborted`. Otherwise maintenance/manual intervention.
- `source_stopped_and_writer_fenced` with no migration intent and exact pre-fingerprint: write fence-release intent, release/verify through the same Task-14 connection rules, restart only frozen source digests/runtime pointer, verify and restore edge; result `rolled_back`. Unknown fence release is manual intervention.
- Migration intent without verified completion: enumerate actual schema. Only exact pre-migration fingerprint, or exact planned fingerprint **plus fresh complete source-recovery proof**, allows verified fence release and frozen-source restart. Every partial/neither/ambiguous schema stays maintenance/manual intervention. Alembic downgrade calls remain zero.
- `migration_verified` through before fence release: stop target; only fresh source recovery proof permits verified fence release and frozen-source restart. After fence release but before traffic, recovery first proves no operation/unknown barrier owner; it may reacquire a verification barrier under the same operation, then explicitly release it before source start.
- Traffic completion without commit: if actual edge, exact target digests/identity, DB, admission, and health all agree, record current/previous and continue receipt; otherwise restore source only through the complete source rule. Commit without terminal result only retries the identical receipt when actual healthy target/current agree; drift stops external traffic and becomes manual intervention.
- `committed_pending_receipt` touches no container, database, admission, edge, current, or previous. It retries/read-backs the same canonical `close-with-receipt` digest; success appends `committed`, closes the hold, and failure remains pending/protected and alerts. `committed`, `aborted`, and `rolled_back` are read-only terminal checks with an acknowledged closed hold; drift creates a separate incident record and never rewrites the result.
- `manual_intervention` continues to own/block the logical deployment lease. Only recover of the same operation may append additional verified facts and reach an allowed terminal result. Break-glass is a separately documented incident process and never a hidden recovery-table default.
- The synchronous `deploy` command and explicit `recover` command call the same `Invoke-ClosedRecoveryDecision` engine. A classifiable target start/readiness/identity, source-proof, fence-release, or edge-restore failure while the controller still owns the same lease immediately runs that engine before `deploy` returns, ending as `rolled_back`, `committed_pending_receipt`, or `manual_intervention` as facts allow. It never leaves a routine target failure pending merely to require a second command. Only controller/host loss, unknown external facts, or an operator-aborted process requires later explicit `recover`.

- [ ] **Step 1: Write failing one-to-one decision-table contract tests**

Parse the approved specification's state/rule fixture and require every section-14.2 row, 20 durable states, side-effect intent, and result to map to exactly one closed table rule. Test missing/extra/wildcard rule, wrong source (`previous_stable`), changed target, unknown fact treated as false, terminal rewrite, unbounded cleanup, and automatic downgrade/production restore adapter presence.

- [ ] **Step 2: Write failing recovery integration tests at major boundaries**

Externally terminate the controller after hold registration/renewal, every maintenance edge/admission substep, source stop/fence acquire, migration intent, migration verification, target fenced start/verify, fence-release intent/completion, target activation, traffic completion, commit, and receipt/hold-close submission. Restart with the same operation. Assert the same hold/next sequence, exact allowed result/effect count, current/previous rule, edge/application identity, fence facts, and zero forbidden business/DB effects. Repeat recover to prove idempotency.

Separately return synchronous target-start/readiness and edge-restore failures without killing the controller. Assert `deploy` invokes the identical table engine before returning and reaches the same allowed automatic recovery/manual result and effect counts as a later explicit `recover`; no second recovery implementation or speculative rollback path is called.

- [ ] **Step 3: Write failing MySQL nontransactional partial-DDL matrix**

Use test-only migration revisions/scripts where DDL #1 implicitly commits and DDL #2 fails or the process is killed. Create cases where `alembic_version` is old/new/missing while actual schema is exact pre, exact planned, or partial. Also inject migration privilege reverse-verification failure. On MySQL 8.0 and 8.4, assert recovery inspects complete fingerprint; partial/unknown state never releases fence, starts source/target, restores traffic, calls downgrade, or changes business data.

- [ ] **Step 4: Write failing receipt and terminal-drift tests**

Drop the central endpoint before/after hold register, renewal, and terminal close; replay an acknowledgement, return a lower sequence, expire the hold, corrupt/ambiguate the response, and race central GC. Assert only the same transition or exact next sequence is used, ambiguous/expired facts pause all cleanup, and no new deploy starts. For terminal-state container/edge/DB drift, assert a new content-free incident/manual-intervention record is created without mutating original terminal journal/current/previous/closed hold.

- [ ] **Step 5: Run focused tests and observe missing recovery implementation**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_release_recovery_table.py backend/tests/contracts/test_release_transaction.py backend/tests/contracts/test_release_central_operation.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_controller.py backend/tests/integration/test_release_failure_recovery.py backend/tests/integration/test_release_partial_ddl_recovery.py backend/tests/integration/test_release_receipt_recovery.py --require-mysql -v`

Expected: FAIL because `recover`, the closed decision table, partial-DDL classification, and receipt-only recovery do not exist.

- [ ] **Step 6: Implement fact collection before recovery decisions**

Collect actual facts through read-only approved adapters and bind each fact to observation time/source/digest. Do not mutate derived state before decision. If facts conflict or cannot be collected, enter/retain maintenance and append a closed `manual_intervention` reason if safe journal ownership is proven. Never release a logical lease or fence merely because a process disappeared.

- [ ] **Step 7: Implement each decision-table action as an idempotent effect group**

Each effect checks its intent/completion and actual fact before doing anything. For possibly executed effects, reconcile rather than blindly retry. Source recovery always renders/starts exact frozen manifest digests and uses the operation-frozen runtime pointer through 11A CAS; a CAS conflict is manual intervention. Traffic restore requires exact public identity, not only health status.

- [ ] **Step 8: Verify full recovery and both MySQL versions**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_release_recovery_table.py backend/tests/contracts/test_release_transaction.py backend/tests/contracts/test_release_central_operation.py -m "not mysql and not deepseek_live" -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_controller.py backend/tests/integration/test_release_failure_recovery.py backend/tests/integration/test_release_partial_ddl_recovery.py backend/tests/integration/test_release_receipt_recovery.py --require-mysql -v`

Run: `pwsh .\scripts\test-mysql-matrix.ps1`

Expected: PASS on disposable MySQL 8.0/8.4. `scripts/test-mysql-matrix.ps1` explicitly invokes the partial-DDL recovery file and rejects unexpected skips. Every vector ends only as `aborted`, `rolled_back`, `committed`, `committed_pending_receipt`, or blocking `manual_intervention`; every terminal outcome has one acknowledged hold close, while pending/manual states remain protected. Downgrade/production-overwrite/business-mutation call counts are zero. This is still not final support evidence until Task 18 fault injection and G4 rehearsal pass.

- [ ] **Step 9: Commit closed crash recovery**

```powershell
git add ops/release.ps1 ops/release backend/tests/contracts/test_release_recovery_table.py backend/tests/contracts/test_release_transaction.py backend/tests/contracts/test_release_central_operation.py backend/tests/integration/test_release_controller.py backend/tests/integration/test_release_failure_recovery.py backend/tests/integration/test_release_partial_ddl_recovery.py backend/tests/integration/test_release_receipt_recovery.py .github/workflows/compatibility.yml scripts/test-mysql-matrix.ps1
git commit -m "ops: recover interrupted release operations"
```

### Task 17: Manage Retention, Long-Term Holds, Revocation, Archival, and Safe Pruning

**Depends on:** Tasks 3, 10, and 16.

**Files:**
- Create: `.github/workflows/release-retention.yml`
- Create: `tools/releases/retention.py`
- Create: `tools/tests/test_release_retention.py`
- Create: `tools/tests/test_release_revocation.py`
- Create: `ops/release/Retention.psm1`
- Create: `backend/tests/contracts/test_release_retention_workflow.py`
- Create: `backend/tests/integration/test_release_local_prune.py`
- Modify: `.github/workflows/release-catalog.yml`
- Modify: `tools/releases/catalog.py`
- Modify: `ops/release.ps1`
- Modify: `ops/release/Catalog.psm1`
- Modify: `ops/release/Transaction.psm1`
- Modify: `ops/release/Receipt.psm1`
- Modify: `release/policies/github-repository-policy.json`
- Modify: `release/policies/release-security-policy.json`
- Modify: `backend/tests/contracts/test_release_workflows.py`

**Interfaces:**
- The central mark set always protects: the latest 20 `approved` non-revoked releases by integer ordinal; every `long_term_retained` release; current/previous in every fresh production receipt; source/target of every live, expired-unclosed, `manual_intervention`, or `committed_pending_receipt` operation hold; versions referenced by an unexpired rehearsal hold; and every OCI platform manifest, child manifest/config/layer, version-neutral Compose template/renderer, signature, SBOM, provenance, scan result, and required referrer reachable from those roots.
- The cleanup workflow exhaustively paginates and signature-validates the protected `deployment-ledger/<environment>/*` refs and annotated tag objects/messages into one environment chain, records its unique tip and sorted ref/digest set in the sweep plan, and repeats the full read immediately before every delete group. Any missing protected ref or tag object/message, added/changed record set, fork, pagination ambiguity, operation/environment sequence rollback/gap, expired-but-unclosed hold, ambiguous dispatch/close, expired/missing/ambiguous production receipt, stale catalog, unknown rehearsal hold, incomplete referrer traversal, or ambiguous registry deletion result pauses **all central deletion**. Unknown never means unreferenced. Expiry is an alert/global pause, never permission to collect an open hold's roots.
- Retain/unretain is a protected catalog transition with actor, timestamp, closed reason, and prior/next catalog digest. Unretain does not delete; normal mark policy decides later. A version cannot be retained to bypass `revoked`.
- Revocation is terminal and signed with closed security/data/supply-chain reason. Ordinary deploy never targets revoked. A revoked current is not blindly stopped; `deploy-away-from-revoked-current` is allowed only to an approved/compatible/non-revoked target, requires a closed incident code, and executes the complete Task-15 gates without any bypass.
- Archival publishes a signed `archived` catalog generation **before** deletion, waits for all fresh receipts/holds to prove no current/previous/nonterminal/rehearsal reference, and only then deletes deployability artifacts. It retains version, Git SHA, manifest digest, signature/gate summary, status/reason/times, and deployment history. Archived versions cannot be rebuilt under the old number or ordinarily deployed.
- Registry deletion is by verified immutable digest/object ID through a narrow create/read/delete client whose token can delete only the approved package namespace and cannot change source/tag/Release/catalog. Enumerate multi-arch descendants and referrers before mark/sweep; after deletion, verify every protected root remains pullable and verifiable offline.
- Local `prune -WhatIf` is read-only. Actual prune requires no nonterminal/pending operation, fresh catalog and receipts, deployment lock, complete verified source/current/previous/target roots, and a content-addressed plan digest. It never removes base images/volumes/data/backup/keyring/controller state and never uses broad Docker prune.

- [ ] **Step 1: Write failing mark-set and graph traversal tests**

Generate graphs with shared layers, multi-arch child manifests, nested/referrer artifacts, recent ordinal gaps, current/previous outside recent 20, long-term holds, live/expired-unclosed/manual/pending annotated-tag-ledger holds, rehearsal holds, archived/revoked nodes, stale receipts, operation/environment sequence/prior-digest rollback/gap/fork, ambiguous close, missing protected ref/tag object/message or ledger/registry pagination page, missing child, and cycles/malformed descriptors. Race register/renew/close ref creation against GC's first and pre-delete full pagination. Assert all protected reachable objects are marked and every stale/unknown/forked/concurrent change pauses all deletion.

- [ ] **Step 2: Write failing catalog transition and workflow-permission tests**

Cover retain/unretain audit, revoked terminality, archived ordering, attempted resurrection, ordinary deploy to revoked, current revoked alert, deploy-away with missing/free-text incident code, and cleanup credential overreach. Assert PR/non-master/server-reader/receipt identities cannot invoke catalog status or package deletion.

- [ ] **Step 3: Write failing local prune tests**

Use a fake Docker content store. Cover current/previous/nonterminal/pending protection, incomplete local source cache, stale catalog/receipt, plan drift between WhatIf and execute, shared layer, base image, and unexpected Docker object. Snapshot all named volumes/networks/state/backup directories and require no deletion outside the exact marked application objects.

- [ ] **Step 4: Run focused tests and observe absent safe retention**

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests/test_release_retention.py tools/tests/test_release_revocation.py backend/tests/contracts/test_release_retention_workflow.py backend/tests/contracts/test_release_workflows.py -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_local_prune.py -v`

Expected: FAIL because central retention/revocation workflow, transitive OCI mark/sweep, and protected local prune do not exist.

- [ ] **Step 5: Implement closed catalog operations and transitive mark/sweep**

Accept only typed version/reason/expiry inputs from a protected reviewed workflow. Revalidate current catalog, central hold/receipt snapshot generation, and all referenced objects immediately before publishing the next generation and before each delete group. Sweep only after the catalog's archived/hold transition is accepted, every terminal hold has one acknowledged unique `close-with-receipt` record, and holds/receipts remain fresh. Use immutable identifiers and re-read after ambiguous API responses; never delete a tag/ref merely to make an object collectible.

- [ ] **Step 6: Implement local prune and revoked-current handling**

Make local plan output content-free and hashable. Revalidate the identical plan under lock before each deletion group. Add the specialized deploy-away command mode as a thin incident-reason wrapper around the normal transaction, not a second transaction path. A revoked-current catalog update triggers alert/status but does not itself invoke Docker or edge.

- [ ] **Step 7: Verify mark/sweep, permissions, and offline protected roots**

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests/test_release_retention.py tools/tests/test_release_revocation.py backend/tests/contracts/test_release_retention_workflow.py backend/tests/contracts/test_release_workflows.py -v`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_release_local_prune.py -v`

Expected: PASS against fake/local stores. After a simulated sweep, every protected manifest/referrer remains signature-verifiable and startable from local content; stale receipts or an incomplete graph produce zero delete calls.

- [ ] **Step 8: Commit retention and revocation management**

```powershell
git add .github/workflows/release-retention.yml .github/workflows/release-catalog.yml tools/releases tools/tests/test_release_retention.py tools/tests/test_release_revocation.py ops/release.ps1 ops/release backend/tests/contracts backend/tests/integration/test_release_local_prune.py release/policies
git commit -m "ci: manage release retention and revocation"
```

**External isolated validation after this commit and G1:** From this exact committed SHA, create disposable signed test releases/receipts in an approved isolated package/ref/Release namespace, exercise retain/unretain/archive/revoke and dry-run cleanup, then actual cleanup of only explicitly disposable unreferenced objects. Prove reader and receipt identities cannot delete; cleanup identity cannot write source refs/Releases outside its closed workflow. Never test by deleting a real application version/current/previous artifact. Save the final source SHA, workflow identity, plan/receipt/catalog digests, closed results, and content-free proof of catalog-before-delete ordering and protected-root survival. Any code/config fix creates a new commit and requires this validation to be rerun. Keep production cleanup disabled until this succeeds and receipts are monitored.

### Task 18: Run End-to-End Tamper, Concurrency, and Every-Boundary Failure Gates

**Depends on:** Tasks 16–17. This task makes recovery tests a required protected-master publication gate; it does not replace G4.

**Files:**
- Create: `backend/tests/release_harness/__init__.py`
- Create: `backend/tests/release_harness/environment.py`
- Create: `backend/tests/release_harness/faults.py`
- Create: `backend/tests/release_harness/oracles.py`
- Create: `backend/tests/integration/test_release_supply_chain_integration.py`
- Create: `backend/tests/integration/test_release_every_boundary_recovery.py`
- Create: `backend/tests/integration/test_release_concurrency.py`
- Create: `backend/tests/integration/test_release_security_canaries.py`
- Create: `backend/tests/fixtures/release/fault-boundaries.json`
- Create: `scripts/test-release-matrix.ps1`
- Modify: `backend/pyproject.toml`
- Modify: `.github/workflows/compatibility.yml`
- Modify: `.github/workflows/release.yml`
- Modify: `release/policies/release-publication-policy.json`
- Modify: `ops/verify-release-deployment.ps1`
- Modify: `backend/tests/contracts/test_release_workflows.py`
- Modify: `backend/tests/contracts/test_release_transaction.py`

**Interfaces:**
- The harness creates a unique temporary root, local OCI registry pinned by digest, test-only signing/trusted identity, disposable stable/app Compose projects, synthetic backup keyring/storage, temporary release controller state, synthetic browser client, fake protected-workflow/annotated-tag hold/receipt ledger, and disposable MySQL 8.0 or 8.4 database whose name passes the repository's test-only guard.
- It refuses production database names/hosts, repository `.env`, real GHCR/receipt credentials, non-test signing identity, workspace/global Docker objects, or non-temporary state paths. Teardown targets only objects carrying the unique test label/name after resolving exact paths; named persistent production volumes are never mounted or deleted.
- Faults are injected **outside** production command parameters: kill controller/holder/container/Docker fixture process, block fixture registry/ledger-dispatch network, fork/reorder/paginate protected ledger refs and annotated tag objects/messages, mutate fixture bytes, exhaust fixture disk adapter, or replace fixture files at harness-controlled boundaries. Production `release.ps1` exposes no fault switch.
- `fault-boundaries.json` enumerates every side-effect intent/completion gap and all 20 durable boundaries. Tests kill before effect, after effect/before completion, and after completion where distinct, restart the controller, invoke the same-operation recovery, and use independent oracles for journal/current/previous, actual edge, exact digests, admission, fence ownership, DB fingerprint/revision, receipt, and business-data invariants.
- Required tamper cases include moved tag; replayed/expired/rollback catalog; manifest/component/layer/Compose/SBOM/provenance/signature/scan mutation; wrong OIDC identity; partial pull; fake PATH tool; ACL/hash drift; Secret canaries; concurrent deploy/deploy and deploy/backup; disk/backup/decrypt/restore/canary failures; drain timeout; unknown DB writer; holder loss/reconnect; partial DDL; privilege reverse-check failure; source proof failure; target startup/readiness/identity/runtime-pointer failure; edge substep failure; torn journal/state; GitHub hold register/renew/close outage or ambiguity, sequence rollback/fork, GC concurrency; registry outage; and local/central cleanup uncertainty.
- The test oracle always asserts forbidden side effects: zero downgrade/production restore; no real/existing publication/config/raw/daily-data/note mutation; no traffic under unknown state; no new work after drain/fence; no wrong source (`previous_stable`) start; no unverified digest; no Secret/business content; no deletion of protected object.
- Protected `master` runs the release harness explicitly in both MySQL 8.0 and 8.4 jobs with bounded timeouts and publishes only content-free test summaries. `release-required` depends on them. Until these gates pass, automatic **real application** approved publication remains disabled; Task-10 isolated workflow validation does not count.

- [ ] **Step 1: Write failing harness self-safety and oracle tests**

Try production-like DB names/URLs, real workspace/state/credential paths, missing unique labels, reparse/path traversal, broad Docker cleanup, repository `.env`, real package host, and production signing identity; require refusal before setup/destruction. Test each independent oracle against deliberately inconsistent fixtures so no oracle merely trusts controller output.

- [ ] **Step 2: Write failing supply-chain and concurrency end-to-end tests**

Build/push synthetic signed S/T releases, then mutate/replay/move one element at a time and assert refusal before maintenance/current change. Run two controller processes plus a backup process and prove one fixed lock order/owner; kill the winner and require only same-operation recover, never a second deploy takeover. Fork the fake annotated-tag ledger and race register/renew/close ref creation with GC; require unique-chain/read-back or a global deletion pause, never root deletion.

- [ ] **Step 3: Generate every intent/boundary recovery test**

Parameterize from the checked-in boundary inventory rather than hand-selecting only happy points. For each vector, record expected allowed terminal/maintenance set and forbidden effects. Include at least exact-pre, exact-planned-plus-source-proof, and partial/ambiguous DDL outcomes. Repeat recover twice to prove idempotency and terminal read-only behavior.

- [ ] **Step 4: Add browser/session, worker, and Agent cross-release tests**

Keep an unsaved old-browser form across S→T, attempt mutation, and prove mismatch before DB/idempotency/outbox writes. Verify refresh and explicit reconfirmation. Run long worker and Agent jobs across drain; prove finish/fence/possible-charge semantics, no cross-version continuation, correct runtime-pointer CAS, and public readiness isolation from provider failure.

- [ ] **Step 5: Run the harness and observe missing full-gate wiring**

Run: `pwsh .\scripts\test-release-matrix.ps1 -MySqlVersion 8.4`

Expected: initial FAIL until harness environment, boundary inventory, adapters, and workflow wiring exist. The script must refuse if Docker/PowerShell/test database safety prerequisites are not satisfied; refusal is not a passing test.

- [ ] **Step 6: Implement safe environment lifecycle, external fault injector, and oracles**

Keep harness helpers in tests only. Resolve and inventory every created container/network/volume/path before teardown. Do not use `docker system prune`, broad `docker compose down -v`, workspace deletion, or an unresolved glob. Ensure registry/signing/receipt fixtures are isolated from network/credentials used by production.

- [ ] **Step 7: Wire protected MySQL 8.0/8.4 release jobs and enable real publication gate**

Pin every new workflow Action/container by full SHA/digest. Invoke the exact release tests in both matrix entries; assert no unexpected skip. Add their stable conclusions to `release-required`. In the same commit, and only after the workflow graph makes these conclusions mandatory, change the signed `real_application_publication_enabled` policy to true; contracts prove no job can observe true without all recovery dependencies and fresh G1. Keep PR jobs credential-free and use smaller deterministic unit/contracts where full Docker harness is unsuitable.

- [ ] **Step 8: Verify complete matrices without claiming G4**

Run: `pwsh .\scripts\test-release-matrix.ps1 -MySqlVersion 8.0`

Run: `pwsh .\scripts\test-release-matrix.ps1 -MySqlVersion 8.4`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_release_workflows.py backend/tests/contracts/test_release_transaction.py -m "not mysql and not deepseek_live" -v`

Expected: both disposable matrices PASS every registered vector with zero unexpected skip and content-free artifacts. Save counts by boundary/reason and evidence digests, but do not invent timing/performance or claim target-server rehearsal.

- [ ] **Step 9: Commit full release recovery gates**

```powershell
git add backend/tests/release_harness backend/tests/integration/test_release_supply_chain_integration.py backend/tests/integration/test_release_every_boundary_recovery.py backend/tests/integration/test_release_concurrency.py backend/tests/integration/test_release_security_canaries.py backend/tests/fixtures/release backend/pyproject.toml scripts/test-release-matrix.ps1 .github/workflows release/policies/release-publication-policy.json ops/verify-release-deployment.ps1 backend/tests/contracts
git commit -m "test: verify switchable release recovery gates"
```

### Task 19: Add Monitoring, Runbooks, Base Upgrades, and the Target-Equivalent Rehearsal

**Depends on:** Task 18. Production support additionally requires G1–G4.

**Files:**
- Create: `ops/release-monitor.ps1`
- Create: `ops/run-release-rehearsal.ps1`
- Create: `ops/release/Monitoring.psm1`
- Create: `ops/release/Rehearsal.psm1`
- Create: `release/schemas/release-rehearsal-evidence.schema.json`
- Create: `docs/operations/application-releases.md`
- Create: `docs/operations/application-release-recovery.md`
- Create: `docs/operations/application-release-retention.md`
- Create: `docs/operations/stable-base-upgrades.md`
- Create: `docs/operations/application-release-break-glass.md`
- Create: `backend/tests/contracts/test_release_monitoring.py`
- Create: `backend/tests/contracts/test_release_operations_docs.py`
- Create: `backend/tests/contracts/test_release_rehearsal.py`
- Modify: `.github/workflows/controller-base-release.yml`
- Modify: `tools/releases/build_controller_base_bundle.py`
- Modify: `release/policies/controller-base-inventory.json`
- Modify: `tools/tests/test_release_supply_chain.py`
- Modify: `backend/tests/contracts/test_release_host_security.py`
- Modify: `backend/tests/contracts/test_release_workflows.py`
- Modify: `ops/DEPLOYMENT.md`
- Modify: `ops/verify-deployment.ps1`
- Modify: `ops/verify-release-deployment.ps1`
- Modify: `docs/operations/local-maintenance.md`
- Modify: `docs/operations/agent-runtime.md`

**Interfaces:**
- `release-monitor.ps1` is strictly read-only and emits bounded content-free machine JSON/exit codes for: current/previous vs actual digest drift; nonterminal/manual operation; prolonged maintenance; open/manual hold nearing expiry, expired-unclosed, operation/environment gap or fork, missing protected tag object/message, dispatcher/ruleset G1 drift, or central GC-paused state; pending/expired receipt; missing current/previous local/central artifact; catalog/signature/provenance failure; backup/isolated restore failure; database revision/fingerprint incompatibility; migration privilege drift; runtime pointer mismatch; browser mismatch rate; and insufficient release peak-space reserve.
- Alert dimensions are a closed enum and values contain only environment ID, release version, digest, operation UUID, state/reason, timestamp/age bucket, and evidence digest. No database rows, usernames, imported filenames, notes, Agent content, raw exception/provider error, credential path/content, or unbounded label appears.
- `run-release-rehearsal.ps1` only accepts an explicitly marked target-equivalent **isolated** environment, synthetic data, approved test signing/registry/receipt identities, and an empty rehearsal state namespace. It invokes public release commands and external fault controls; it does not add production bypass/fault flags.
- This task explicitly extends `controller-base-inventory.json` with both new runtime entrypoints, `ops/release-monitor.ps1` and `ops/run-release-rehearsal.ps1`, their `ops/release/Monitoring.psm1` and `ops/release/Rehearsal.psm1` module dependencies, and `release/schemas/release-rehearsal-evidence.schema.json`. `build_controller_base_bundle.py` and `controller-base-release.yml` require these exact paths and reject a missing, extra, unresolved, or digest-mismatched entrypoint/dependency before signing or publication. Tests prove the old `ops/release*.ps1` glob would miss `run-release-rehearsal.ps1` and that the explicit canonical inventory does not. Both entrypoints run Task-11 host preflight from the installed protected bundle and verify their own digest plus dependency-closure/inventory digest before any observation or rehearsal setup; an arbitrary repository checkout is not a supported G2/G4 runner.
- Rehearsal evidence schema binds environment class, final controller/base source SHA, bundle/inventory/runner/schema digests, application version/manifest/image digests, source/target/current/previous, database revisions/fingerprints, operation UUIDs, named step/result codes, timestamps, test/harness version, and reviewer sign-off. The validator accepts success only when those controller subjects equal the installed final G2 bundle used for every step. It excludes Secret and business values and never contains synthetic row content.
- Daily release guide covers exact `list`, `inspect`, `status`, `history`, `deploy -WhatIf`, `deploy`, and `recover` commands, freshness/compatibility interpretation, content-free evidence, pending receipt, compatible historical selection, and the fact that “arbitrary version” means approved + present + unrevoked + compatible.
- Recovery guide mirrors every decision-table case, explicitly prohibits DB downgrade/speculative source/previous startup, and gives safe collection/escalation for partial DDL/manual intervention. Break-glass is a separately authorized incident procedure with two-person approval/evidence; it is not implemented as a normal controller flag and cannot retrospectively mark an unknown operation successful.
- Retention guide covers recent 20, long-term retain/unretain, revoke, archive, receipt holds, central/local dry run, and proof before deletion. Base guide covers controller/edge/MySQL/infrastructure digest update under separate maintenance with backup/rehearsal/rollback of config only; it never deletes/recreates persistent volumes or lets an application version self-update the base.
- `ops/DEPLOYMENT.md` changes the supported application-upgrade path only after the completion checklist/G4 evidence is recorded. Legacy on-server build is then marked break-glass/migration-only, not a silent alternate normal path.

- [ ] **Step 1: Write failing monitoring and documentation contracts**

Require every alert/runbook topic and exact safe command, no forbidden production switch, no `down -v`/blind prune/downgrade/overwrite guidance, explicit source-vs-previous rule, all five recovery results, content-free evidence fields, G1–G4 sign-off, and the ten rehearsal steps. Require the workflow/builder/inventory contracts to include both new entrypoints and every runtime dependency. Delete, replace, or omit the runner, module, schema, inventory entry, or expected workflow path one at a time and require bundle construction or host preflight to fail. Inject content/Secret canaries into fake errors and assert monitor output rejects/redacts them to closed codes.

- [ ] **Step 2: Write failing rehearsal safety and evidence tests**

Refuse a production DB/registry/credential/state marker, existing non-test volume, non-synthetic fixture, non-empty global namespace, or unsupported platform. Test evidence duplicate/unknown fields, missing step, wrong digest/operation link, fabricated success without actual oracle, and Secret/business canary. Require each step's actual fact oracle before a success result. Exercise a fake public-command adapter and require exact ten-step sequencing, external-only fault injection, content-free evidence, cleanup containment, and read-only `-WhatIf`.

- [ ] **Step 3: Run contracts and observe missing operations layer**

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests/test_release_supply_chain.py backend/tests/contracts/test_release_host_security.py backend/tests/contracts/test_release_workflows.py backend/tests/contracts/test_release_monitoring.py backend/tests/contracts/test_release_operations_docs.py backend/tests/contracts/test_release_rehearsal.py -m "not mysql and not deepseek_live" -v`

Expected: FAIL because read-only monitoring, the safety-gated rehearsal runner/evidence validator, and operator runbooks do not exist.

- [ ] **Step 4: Implement content-free monitoring and wire alerts**

Reuse Task-12 status read adapters without importing mutators. Produce stable exit codes suitable for Task Scheduler/monitoring ingestion. Document but do not assume the site's alert transport; whatever transport is selected must receive only the allowlisted event. Test stale/unreachable facts as explicit alerts, not healthy defaults.

- [ ] **Step 5: Implement the rehearsal runner and strict evidence validator**

Make `run-release-rehearsal.ps1` validate the isolated target-equivalent marker, empty unique state/ledger namespace, synthetic inputs, exact signed controller/base/application subjects, disposable databases/volumes, and external fault-controller identity before invoking only public release commands. `-WhatIf` performs no setup or mutation. The runner executes the declared ten-step graph, gates each success on independent Task-18 oracles, writes schema-closed content-free evidence atomically, scans it for canaries, and never cleans an unresolved/out-of-root object. It has no production bypass or embedded fault hook.

- [ ] **Step 6: Write daily, recovery, retention, break-glass, and base guides**

Use exact commands and closed expected states. Clearly distinguish repository CI evidence, per-deploy fresh evidence, target rehearsal, and performance/availability observations. Do not promise zero downtime or an unmeasured duration. Explain that MySQL backup is for disaster recovery/verification, not routine application rollback. Include how to leave stable maintenance in place and escalate partial DDL without guessing.

- [ ] **Step 7: Verify deterministic docs/monitoring and the rehearsal's safety checks**

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests/test_release_supply_chain.py backend/tests/contracts/test_release_host_security.py backend/tests/contracts/test_release_workflows.py backend/tests/contracts/test_release_monitoring.py backend/tests/contracts/test_release_operations_docs.py backend/tests/contracts/test_release_rehearsal.py -m "not mysql and not deepseek_live" -v`

Run: `pwsh .\ops\release-monitor.ps1 -WhatIf`

Run: `pwsh .\ops\run-release-rehearsal.ps1 -WhatIf`

Expected: contracts PASS; both PowerShell previews are read-only and either produce a complete closed plan against configured safe fixture facts or refuse with a closed prerequisite code. A refusal is not G4 completion.

- [ ] **Step 8: Run final repository gates before commit**

Run: `.\.venv\Scripts\python.exe -m ruff check backend tools`

Run: `.\.venv\Scripts\python.exe -m ruff format --check backend tools`

Run: `.\.venv\Scripts\python.exe -m mypy --config-file backend/pyproject.toml backend/app backend/tests tools/releases tools/tests`

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests -m "not mysql and not deepseek_live"`

Run: `.\.venv\Scripts\python.exe -m pytest tools/tests`

Run: `pnpm --dir frontend lint`

Run: `pnpm --dir frontend typecheck`

Run: `pnpm --dir frontend test --run`

Run: `pnpm --dir frontend build`

Run: `pwsh .\scripts\test-mysql-matrix.ps1`

Run: `pwsh .\scripts\test-release-matrix.ps1 -MySqlVersion 8.0`

Run: `pwsh .\scripts\test-release-matrix.ps1 -MySqlVersion 8.4`

Expected: deterministic, frontend, MySQL, and release matrices PASS with zero unexpected skips. Report only commands actually run. These repository checks are not G4.

- [ ] **Step 9: Commit operations and final gate mapping**

```powershell
git add ops/release-monitor.ps1 ops/run-release-rehearsal.ps1 ops/release/Monitoring.psm1 ops/release/Rehearsal.psm1 release/schemas/release-rehearsal-evidence.schema.json .github/workflows/controller-base-release.yml tools/releases/build_controller_base_bundle.py release/policies/controller-base-inventory.json tools/tests/test_release_supply_chain.py docs/operations ops/DEPLOYMENT.md ops/verify-deployment.ps1 ops/verify-release-deployment.ps1 backend/tests/contracts/test_release_host_security.py backend/tests/contracts/test_release_workflows.py backend/tests/contracts/test_release_monitoring.py backend/tests/contracts/test_release_operations_docs.py backend/tests/contracts/test_release_rehearsal.py
git commit -m "ops: add signed switchable release operations"
```

**External final G2 → G3 → G4 actions after this commit:** First let protected `master` build and sign a new immutable controller/base bundle from this exact final Task-19 source SHA and complete inventory/dependency graph. Repeat the **entire** G2 procedure with that exact bundle: signature/inventory verification, installer `-WhatIf`, exact paths/SIDs/hashes/Docker context, ACL/owner/caller checks, registry and ledger identity negative-permission tests, backup/key fault-domain checks, installation, and post-install digest verification. Earlier Task-11 G2 evidence is insufficient if any bundled or dependency file changed. Next, with this same G2-approved installed controller, perform G3: establish genesis only if none exists, otherwise strictly and read-only revalidate the immutable genesis/current journal chain, actual application digests/runtime pointer/database fingerprint/edge identity, and approved manifest; never write a second genesis or bless drift. Only then, on the target-equivalent isolated host and after fresh G1, run G4 with application manifests built from their exact final committed SHAs: signed baseline; synthetic import→processing→human correction/note→validation→daily publish→dashboard/Agent-safe state; expand deployment; session/browser/data/worker/Agent/backup/privilege proof; compatible prior-version deployment without downgrade; target-start failure automatic source recovery; real partial DDL on MySQL 8.0 and 8.4 with maintenance/manual intervention; current/previous/long-term/open-ledger/referrer retention plus ledger/receipt outage; and signed/reviewed canary-free evidence. Include at least one real host reboot/power-loss boundary after maintenance or migration intent and prove stable maintenance, restart policy, journal durability, same-operation hold renewal, and recovery. Every expected step closes successfully except deliberate partial DDL, whose successful safety outcome is maintenance plus `manual_intervention`. Any later change to the controller/base inventory or dependency graph invalidates G2 and controller-dependent G3 as well as G4; any other code/config change after rehearsal invalidates G4. Create new committed/signed artifacts and rerun the affected gates—evidence from an earlier SHA or bundle is invalid.

## Dependency and Gate Graph

```text
P0 + T2 → T4 → T5 ───────────────→ T7 → T8 ──────────────────────────────┐
P0 + T2 + T5 → T6 ───────────────────────────────┐                       │
T1 → G1                                          │                       │
T2 → T3                                          │                       │
T1 + T2 + T6 + T8 → T9 → T10 → T11 → T12 ──────┼───────────────────────┤
P0 backup-v2 + T6 + T12 → T13                    │                       │
P0 + T5 + T8 + T12 + T13 → T14                  │                       │
T7 + T8 + T10 + T12 + T13 + T14 → T15 → T16 → T17 → T18 → T19          │
T11 commit + G1 → provisional signed controller/base bundle → provisional G2
T12–T19 controller/base inventory or dependency changes → invalidate prior G2 and controller-dependent G3
Final T19 commit + G1 → final signed controller/base bundle → full final G2
Final G2 bundle + exact approved baseline/genesis-chain proof → final G3
Final committed/signed application artifacts + G1 + final G2 + final G3 → G4
```

Tasks are executed in numeric order even where the graph permits local parallel preparation. G1 blocks real ledger/package publication; G2 blocks real controller/base installation and host mutation; G3 blocks the first real deploy/recover; G4 blocks the production-supported claim. They do not block repository-local implementation against fixed fixtures. G1, G2, G3, and G4 are evidence gates, not repository commits. Each Task 1–19 ends with exactly one commit; do not squash across a recovery/security boundary during implementation review.

## Implementation Completion Checklist

- [ ] All 18 stage-11A tasks and their external/target gates are complete; actual Alembic head and Agent/backup interfaces match this plan.
- [ ] Tasks 1–19 were implemented in order as 19 reviewable commits, with every expected-failure test observed before its minimal implementation and no applied migration edited.
- [ ] G1 proves protected `master`, stable required checks, protected application/catalog/controller/ledger refs with create-only actors and no update/delete bypass, Action allowlist/default permissions, trusted signing/attestation/ledger identities, and least-privilege GHCR/dispatcher actors.
- [ ] Every approved manifest/catalog/ledger hold/receipt passes strict duplicate-key/schema/canonical/digest/signature/identity validation; the immutable environment chain has no gap/fork, and all OCI components/evidence bind one source SHA/build identity.
- [ ] Stable base preserves exact production volumes/networks and serves maintenance independently; application Compose contains no `build`, `latest`, tag-only, cross-manifest image, Docker socket, controller credential, or unapproved writable privilege.
- [ ] Fresh final G2 evidence binds the exact Task-19 controller/base source SHA, immutable bundle and inventory/dependency digests, dedicated host identity, caller/ACL/owner/hash/path/Docker-context policy, read-only registry identity, dispatch/read-only ledger identity, backup/key fault domains, and zero Secret canaries; no earlier bundle's evidence is reused after an inventory change.
- [ ] Using that same final G2-approved controller, G3 either establishes the sole genesis current or strictly read-only revalidates the existing immutable genesis/current chain from exact actual-digest/runtime/database/edge equality with one approved signed manifest; no second genesis, local build/tag, or observed drift was guessed or blessed.
- [ ] Informational commands and `-WhatIf` show zero state/lock/cache/Docker/backup/edge/database/receipt side effects, including under damaged/stale facts.
- [ ] Every deploy creates and verifies a fresh encrypted backup v2, random isolated restore, target migration, exact fingerprint, and target/source synthetic read/write canaries before maintenance.
- [ ] Writer fence ownership is proven on one connection across steps 10–16 on MySQL 8.0/8.4; dedicated fence/observer identities have exact least privilege and zero business DML/DDL; holder/controller/MySQL loss and release ambiguity remain fenced/maintenance until safely reconciled.
- [ ] Normal and historical-version deploys follow all 20 states; the database never downgrades and source recovery uses only the operation-frozen source with all four compatibility proofs.
- [ ] Every recovery-table row, every side-effect intent/completion gap, partial DDL, concurrent operation, tamper, edge failure, target failure, ledger register/renew/close outage/fork/expiry, registry outage, journal tear, and cleanup uncertainty has passing closed-result and forbidden-side-effect evidence.
- [ ] Old browsers cannot write through a release mismatch, never automatically replay an unknown form, and compatible sessions survive after explicit refresh/reconfirmation.
- [ ] Worker and Agent admission/drain/fencing prevent cross-version work; Runtime pointer CAS and possible-charge behavior remain correct; Agent dependency failure does not falsify public readiness.
- [ ] Central/local retention protects recent 20, current, previous, long-term, every open/expired/manual/pending ledger hold, and rehearsal roots plus every OCI descendant/referrer; fork/gap/ambiguity pauses all deletion, revoked is terminal, and archival precedes deletion.
- [ ] G4 target-equivalent rehearsal is reviewed and signed against final committed artifacts, including both MySQL versions for partial DDL and a real host reboot/power-loss boundary; evidence contains zero Secret/business canaries and makes no unsupported downtime/performance claim.
- [ ] `ops/DEPLOYMENT.md` marks release switching supported only after all above evidence exists; until then the legacy documented procedure remains authoritative.

Only after every checkbox and G1–G4 is satisfied may the project state that administrators can safely select and publish compatible historical application versions.
