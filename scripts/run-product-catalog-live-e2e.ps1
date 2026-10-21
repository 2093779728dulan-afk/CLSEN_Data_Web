#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter()]
    [ValidateSet("Catalog", "Products", "Cutover", "Release", "All")]
    [string]$Milestone = "Catalog",

    [Parameter()]
    [switch]$ValidateOnly,

    [Parameter()]
    [switch]$Experience,

    [Parameter()]
    [switch]$ExperienceOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

if ($ExperienceOnly -and -not $Experience) {
    throw "-ExperienceOnly requires -Experience."
}

$playwrightProject = switch ($Milestone) {
    "Catalog" { "catalog-milestone-a" }
    "Products" { "product-milestone-b" }
    default { "product-cutover" }
}
$releaseSource = if ($Milestone -eq "Catalog") { "legacy_parser" } else { "p0_catalog" }

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$backendDirectory = Join-Path $repositoryRoot "backend"
$frontendDirectory = Join-Path $repositoryRoot "frontend"
$pythonExecutable = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$viteEntry = Join-Path $frontendDirectory "node_modules\vite\bin\vite.js"
$privilegeManifestPath = Join-Path $PSScriptRoot "database-privileges.json"
$runIdentifier = [guid]::NewGuid().ToString("N")
$databaseName = "clsen_data_test_$($runIdentifier.Substring(0, 16))"
$containerName = "clsen-catalog-live-$($runIdentifier.Substring(0, 12))"
$containerLabel = "clsen.catalog-live.run=$runIdentifier"
$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$runtimeRoot = [IO.Path]::GetFullPath(
    (Join-Path $temporaryRoot "clsen-catalog-live-$runIdentifier")
)
$storageRoot = Join-Path $runtimeRoot "storage"
$manifestPath = Join-Path $runtimeRoot "run-manifest.json"
$resultPath = Join-Path $runtimeRoot "playwright-result.json"
$teardownMarker = Join-Path $runtimeRoot "playwright-teardown.json"
$experienceStopMarker = Join-Path $runtimeRoot "experience-stop.json"
$experienceCredentialsPath = Join-Path $runtimeRoot "experience-credentials.json"
$usersPath = Join-Path $runtimeRoot "live-users.json"
$evidencePath = Join-Path $temporaryRoot "clsen-catalog-live-evidence-$runIdentifier.json"
$caCertificatePath = Join-Path $runtimeRoot "mysql-ca.pem"
$containerStarted = $false
$jobCreated = $false
$success = $false
$runFailure = $null
$cleanupFailure = $null
$migrationPassword = $null
$runtimePassword = $null
$grantAdminPassword = $null
$adminPassword = $null
$managerPassword = $null
$viewerPassword = $null
$containerId = $null
$processRecords = [Collections.Generic.List[object]]::new()
$managedEnvironment = @(
    "APP_DATABASE_URL",
    "APP_MIGRATION_DATABASE_URL",
    "APP_TEST_DATABASE_URL",
    "APP_TEST_RUNTIME_DATABASE_URL",
    "APP_TEST_RUN_ID",
    "APP_STORAGE_ROOT",
    "APP_STORAGE_MAX_UPLOAD_BYTES",
    "APP_STORAGE_LEASE_TTL_SECONDS",
    "APP_STORAGE_LEASE_RENEW_INTERVAL_SECONDS",
    "APP_STORAGE_ORPHAN_AGE_SECONDS",
    "APP_ENVIRONMENT",
    "APP_LOG_LEVEL",
    "APP_PRODUCT_ANALYTICS_SOURCE",
    "APP_SESSION_SECRET",
    "APP_SESSION_COOKIE_SECURE",
    "APP_CORS_ALLOWED_ORIGINS",
    "CATALOG_LIVE_API_URL",
    "CATALOG_LIVE_FRONTEND_URL",
    "CATALOG_LIVE_RUN_ID",
    "CATALOG_LIVE_RUNTIME_ROOT",
    "CATALOG_LIVE_MANIFEST",
    "CATALOG_LIVE_RESULT_PATH",
    "CATALOG_LIVE_USERS_PATH",
    "CATALOG_LIVE_TEARDOWN_MARKER",
    "CATALOG_LIVE_EVIDENCE_PATH",
    "CATALOG_LIVE_ADMIN_USERNAME",
    "CATALOG_LIVE_ADMIN_PASSWORD",
    "CATALOG_LIVE_MANAGER_PASSWORD",
    "CATALOG_LIVE_VIEWER_PASSWORD",
    "CATALOG_LIVE_ADMIN_STATE",
    "CATALOG_LIVE_MANAGER_STATE",
    "CATALOG_LIVE_VIEWER_STATE",
    "CATALOG_LIVE_PLAYWRIGHT_OUTPUT",
    "CATALOG_LIVE_PYTHON",
    "CATALOG_LIVE_BACKEND_DIR",
    "CATALOG_LIVE_CUTOVER_PHASE",
    "CATALOG_LIVE_KEEP_STATES",
    "CATALOG_LIVE_REUSE_STATES",
    "VITE_PRODUCT_ANALYTICS_SOURCE"
)
$previousEnvironment = @{}
foreach ($name in $managedEnvironment) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name)
}

function Assert-SafeRuntimeRoot {
    $resolved = [IO.Path]::GetFullPath($runtimeRoot)
    if (
        -not $resolved.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Leaf $resolved) -cne "clsen-catalog-live-$runIdentifier" -or
        $resolved -ceq $temporaryRoot
    ) {
        throw "The live runtime root is outside the operating-system temporary directory."
    }
    return $resolved
}

function ConvertTo-MySqlIdentifier {
    param([Parameter(Mandatory)][string]$Value)
    if ($Value -cnotmatch '\A[A-Za-z0-9_]+\z') {
        throw "Unsafe MySQL identifier was rejected."
    }
    return "{0}{1}{0}" -f [char]96, $Value
}

function ConvertTo-MySqlStringLiteral {
    param([Parameter(Mandatory)][string]$Value)
    return $Value.Replace("\", "\\").Replace("'", "''")
}

function New-DatabaseUrl {
    param(
        [Parameter(Mandatory)][string]$User,
        [Parameter(Mandatory)][string]$Password,
        [Parameter(Mandatory)][int]$Port
    )
    $encodedUser = [Uri]::EscapeDataString($User)
    $encodedPassword = [Uri]::EscapeDataString($Password)
    $encodedCa = [Uri]::EscapeDataString($caCertificatePath)
    return (
        "mysql+pymysql://${encodedUser}:${encodedPassword}@127.0.0.1:" +
        "$Port/${databaseName}?charset=utf8mb4&ssl_ca=$encodedCa&ssl_check_hostname=false"
    )
}

function Invoke-ContainerSql {
    param(
        [Parameter(Mandatory)][string]$Sql,
        [Parameter(Mandatory)][string]$Operation
    )
    $output = @(
        $Sql | & $script:dockerCommand.Source exec --interactive `
            $containerName mysql --user=root --batch 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "MySQL failed while attempting to $Operation in the runner-owned container."
    }
}

function Invoke-GrantAdminSql {
    param(
        [Parameter(Mandatory)][string]$Sql,
        [Parameter(Mandatory)][string]$DatabaseUrl,
        [Parameter(Mandatory)][string]$Operation
    )
    $environmentName = "APP_CATALOG_LIVE_GRANT_ADMIN_URL"
    $previousValue = [Environment]::GetEnvironmentVariable($environmentName)
    try {
        [Environment]::SetEnvironmentVariable($environmentName, $DatabaseUrl)
        $program = @'
import os
import sys

from sqlalchemy import create_engine

url = os.environ.pop("APP_CATALOG_LIVE_GRANT_ADMIN_URL")
statements = [value.strip() for value in sys.stdin.read().split(";") if value.strip()]
engine = create_engine(url, future=True)
raw_connection = engine.raw_connection()
try:
    cursor = raw_connection.cursor()
    try:
        cursor.execute("SELECT CURRENT_USER(), DATABASE()")
        current_user, database_name = cursor.fetchone()
        if not str(current_user).startswith("clsen_live_grants@"):
            raise RuntimeError("unexpected grant administrator identity")
        if not str(database_name).startswith("clsen_data_test_"):
            raise RuntimeError("unexpected grant administrator schema")
        for statement in statements:
            cursor.execute(statement)
        raw_connection.commit()
    finally:
        cursor.close()
finally:
    raw_connection.close()
    engine.dispose()
'@
        $output = @($Sql | & $pythonExecutable -c $program 2>&1)
        if ($LASTEXITCODE -ne 0) {
            [IO.File]::WriteAllLines(
                (Join-Path $runtimeRoot "logs\grant-admin.log"),
                [string[]]$output,
                [Text.UTF8Encoding]::new($false)
            )
            throw "The grant administrator failed while attempting to $Operation."
        }
    }
    finally {
        [Environment]::SetEnvironmentVariable($environmentName, $previousValue)
    }
}

function Get-FreeLoopbackPort {
    for ($attempt = 1; $attempt -le 100; $attempt++) {
        $port = Get-Random -Minimum 12000 -Maximum 60000
        $listener = [Net.Sockets.TcpListener]::new(
            [Net.IPAddress]::Loopback,
            $port
        )
        try {
            $listener.Start()
            return $port
        }
        catch [Net.Sockets.SocketException] {
            # Another process owns this candidate; choose another safe port.
        }
        finally {
            $listener.Stop()
        }
    }
    throw "Could not reserve a browser-safe loopback port."
}

function Get-TextSha256 {
    param([Parameter(Mandatory)][string]$Value)
    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    try {
        return [Convert]::ToHexString(
            [Security.Cryptography.SHA256]::HashData($bytes)
        ).ToLowerInvariant()
    }
    finally {
        [Array]::Clear($bytes, 0, $bytes.Length)
    }
}

function Get-ProcessCommandLine {
    param([Parameter(Mandatory)][int]$ProcessId)
    $record = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId"
    if ($null -eq $record -or [string]::IsNullOrWhiteSpace($record.CommandLine)) {
        throw "Could not read the runner-owned process command line."
    }
    return [string]$record.CommandLine
}

function Add-OwnedProcess {
    param(
        [Parameter(Mandatory)][Diagnostics.Process]$Process,
        [Parameter(Mandatory)][string]$Role,
        [Parameter(Mandatory)][string]$RequiredCommandFragment
    )
    if ($Process.HasExited) {
        throw "$Role exited before it could be assigned to the live job."
    }
    [CatalogLiveJob]::Assign($Process.Id)
    Register-ProcessIdentity `
        -ProcessId $Process.Id `
        -Role $Role `
        -RequiredCommandFragment $RequiredCommandFragment
    Start-Sleep -Milliseconds 100
    Sync-OwnedProcessTree -RootProcessId $Process.Id -Role $Role
}

function Register-ProcessIdentity {
    param(
        [Parameter(Mandatory)][int]$ProcessId,
        [Parameter(Mandatory)][string]$Role,
        [string]$RequiredCommandFragment = ""
    )
    if ($null -ne ($processRecords | Where-Object { $_.pid -eq $ProcessId } | Select-Object -First 1)) {
        return
    }
    $process = Get-Process -Id $ProcessId -ErrorAction Stop
    $commandLine = Get-ProcessCommandLine -ProcessId $ProcessId
    if (-not $commandLine.Contains($RequiredCommandFragment, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Role command fingerprint did not contain its required runner argument."
    }
    $startedAt = $process.StartTime.ToUniversalTime()
    $processRecords.Add([pscustomobject]@{
        role = $Role
        pid = $ProcessId
        started_at = $startedAt.ToString("O")
        start_ticks = $startedAt.Ticks
        command_sha256 = Get-TextSha256 -Value $commandLine
    })
}

function Get-DescendantProcessIds {
    param([Parameter(Mandatory)][int]$RootProcessId)
    $all = @(Get-CimInstance Win32_Process)
    $known = [Collections.Generic.HashSet[int]]::new()
    $known.Add($RootProcessId) | Out-Null
    $changed = $true
    while ($changed) {
        $changed = $false
        foreach ($process in $all) {
            if (
                -not $known.Contains([int]$process.ProcessId) -and
                $known.Contains([int]$process.ParentProcessId)
            ) {
                $known.Add([int]$process.ProcessId) | Out-Null
                $changed = $true
            }
        }
    }
    return @($known | Where-Object { $_ -ne $RootProcessId })
}

function Sync-OwnedProcessTree {
    param(
        [Parameter(Mandatory)][int]$RootProcessId,
        [Parameter(Mandatory)][string]$Role
    )
    foreach ($processId in Get-DescendantProcessIds -RootProcessId $RootProcessId) {
        if ($null -eq ($processRecords | Where-Object { $_.pid -eq $processId } | Select-Object -First 1)) {
            try {
                [CatalogLiveJob]::Assign($processId)
                Register-ProcessIdentity -ProcessId $processId -Role "$Role-child"
            }
            catch {
                if ($null -ne (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
                    throw
                }
                # A short-lived launcher exited after the immutable CIM snapshot.
            }
        }
    }
}

function Assert-OwnedProcessIdentity {
    param([Parameter(Mandatory)][object]$Record)
    $process = Get-Process -Id $Record.pid -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return
    }
    $startedAt = $process.StartTime.ToUniversalTime()
    try {
        $commandLine = Get-ProcessCommandLine -ProcessId $Record.pid
    }
    catch {
        if ($null -eq (Get-Process -Id $Record.pid -ErrorAction SilentlyContinue)) {
            return
        }
        throw
    }
    if (
        $startedAt.Ticks -ne [long]$Record.start_ticks -or
        (Get-TextSha256 -Value $commandLine) -cne [string]$Record.command_sha256
    ) {
        throw "Refusing ambiguous cleanup because a runner PID identity changed."
    }
}

function Wait-OwnedListener {
    param(
        [Parameter(Mandatory)][int]$Port,
        [Parameter(Mandatory)][int]$RootProcessId,
        [Parameter(Mandatory)][string]$Role,
        [Parameter(Mandatory)][string]$Url
    )
    for ($attempt = 1; $attempt -le 120; $attempt++) {
        Sync-OwnedProcessTree -RootProcessId $RootProcessId -Role $Role
        $listeners = @(Get-NetTCPConnection `
            -LocalPort $Port `
            -State Listen `
            -ErrorAction SilentlyContinue)
        $listener = $listeners | Where-Object {
            $owner = $_.OwningProcess
            $null -ne ($processRecords | Where-Object {
                $_.pid -eq $owner -and $_.role.StartsWith($Role, [StringComparison]::Ordinal)
            } | Select-Object -First 1)
        } | Select-Object -First 1
        if ($null -ne $listener) {
            try {
                $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
                if ($response.StatusCode -eq 200) {
                    return
                }
            }
            catch {
                # The process owns the port but has not completed startup yet.
            }
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Runner-owned service on loopback port $Port did not become ready."
}

function Get-DirectorySha256 {
    param([Parameter(Mandatory)][string]$LiteralPath)
    $resolved = [IO.Path]::GetFullPath($LiteralPath)
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "Release build output is unavailable."
    }
    $builder = [Text.StringBuilder]::new()
    foreach ($file in Get-ChildItem -LiteralPath $resolved -File -Recurse | Sort-Object FullName) {
        $relative = [IO.Path]::GetRelativePath($resolved, $file.FullName).Replace("\", "/")
        $digest = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        [void]$builder.Append($relative).Append(":").Append($digest).Append("`n")
    }
    if ($builder.Length -eq 0) {
        throw "Release build output is empty."
    }
    return Get-TextSha256 -Value $builder.ToString()
}

function Get-CatalogBusinessChecksum {
    param([Parameter(Mandatory)][string]$DatabaseUrl)
    $environmentName = "APP_CATALOG_LIVE_CHECKSUM_URL"
    $previousValue = [Environment]::GetEnvironmentVariable($environmentName)
    $program = @'
import datetime as dt
import hashlib
import json
import os

import sqlalchemy as sa

tables = (
    "product_styles", "product_style_revisions", "product_skus",
    "product_sku_revisions", "product_identity_key_reservations",
    "product_catalog_versions", "product_catalog_style_members",
    "product_categories", "product_category_aliases",
    "catalog_style_change_drafts",
    "product_catalog_sku_members", "product_catalog_mappings",
    "product_catalog_exclusions", "product_catalog_publications",
    "product_catalog_publication_events", "return_dedup_snapshots",
    "return_dedup_publications", "return_dedup_group_revisions",
    "return_dedup_group_members", "return_dedup_snapshot_groups",
    "publication_snapshots", "publication_snapshot_members",
    "fact_snapshot_tuples", "business_report_rows", "return_report_rows",
    "catalog_audit_events", "audit_events",
)

def clean(value):
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)

engine = sa.create_engine(os.environ.pop("APP_CATALOG_LIVE_CHECKSUM_URL"), future=True)
digest = hashlib.sha256()
with engine.connect() as connection:
    for table in tables:
        columns = sa.inspect(connection).get_columns(table)
        names = [column["name"] for column in columns]
        primary = sa.inspect(connection).get_pk_constraint(table).get("constrained_columns") or names
        order = ", ".join(f"`{name}`" for name in primary)
        rows = connection.execute(sa.text(f"SELECT * FROM `{table}` ORDER BY {order}"))
        digest.update(table.encode("ascii") + b"\n")
        for row in rows:
            payload = [clean(value) for value in row]
            digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
engine.dispose()
print(digest.hexdigest())
'@
    try {
        [Environment]::SetEnvironmentVariable($environmentName, $DatabaseUrl)
        $output = @(& $pythonExecutable -c $program 2>&1)
        if ($LASTEXITCODE -ne 0 -or ($output -join "").Trim() -cnotmatch '\A[0-9a-f]{64}\z') {
            throw "Could not compute the cutover business checksum."
        }
        return ($output -join "").Trim()
    }
    finally {
        [Environment]::SetEnvironmentVariable($environmentName, $previousValue)
    }
}

function Stop-LiveJob {
    if (-not $script:jobCreated) {
        return
    }
    foreach ($record in $processRecords) {
        Assert-OwnedProcessIdentity -Record $record
    }
    [CatalogLiveJob]::Close()
    $script:jobCreated = $false
}

function Invoke-SchemaPreflight {
    param(
        [Parameter(Mandatory)][string]$DatabaseEnvironment,
        [Parameter(Mandatory)][ValidateSet("api", "worker")][string]$Component
    )
    Push-Location -LiteralPath $backendDirectory
    try {
        & $pythonExecutable -m app.schema_preflight `
            --database-environment $DatabaseEnvironment `
            --component $Component
        if ($LASTEXITCODE -ne 0) {
            throw "$Component schema preflight failed before live process launch."
        }
    }
    finally {
        Pop-Location
    }
}

function Invoke-CutoverPhase {
    param(
        [Parameter(Mandatory)][ValidateSet("legacy-before", "p0", "legacy-rollback")][string]$Phase,
        [Parameter(Mandatory)][ValidateSet("legacy_parser", "p0_catalog")][string]$Source,
        [Parameter(Mandatory)][string]$Project,
        [Parameter(Mandatory)][bool]$ReuseStates,
        [Parameter(Mandatory)][bool]$KeepStates
    )
    $phaseRoot = Join-Path $runtimeRoot "cutover\$Phase"
    $distRoot = Join-Path $phaseRoot "dist"
    New-Item -ItemType Directory -Path $phaseRoot -Force | Out-Null
    $apiPort = Get-FreeLoopbackPort
    do { $frontendPort = Get-FreeLoopbackPort } while ($frontendPort -eq $apiPort)
    $apiUrl = "http://127.0.0.1:$apiPort"
    $frontendUrl = "http://127.0.0.1:$frontendPort"

    $env:APP_PRODUCT_ANALYTICS_SOURCE = $Source
    $env:VITE_PRODUCT_ANALYTICS_SOURCE = $Source
    $env:APP_CORS_ALLOWED_ORIGINS = $frontendUrl
    $env:CATALOG_LIVE_API_URL = $apiUrl
    $env:CATALOG_LIVE_FRONTEND_URL = $frontendUrl
    $env:CATALOG_LIVE_PLAYWRIGHT_OUTPUT = Join-Path $phaseRoot "playwright"
    $env:CATALOG_LIVE_CUTOVER_PHASE = $Phase
    if ($ReuseStates) { $env:CATALOG_LIVE_REUSE_STATES = "1" } else { Remove-Item Env:CATALOG_LIVE_REUSE_STATES -ErrorAction SilentlyContinue }
    if ($KeepStates) { $env:CATALOG_LIVE_KEEP_STATES = "1" } else { Remove-Item Env:CATALOG_LIVE_KEEP_STATES -ErrorAction SilentlyContinue }

    Push-Location -LiteralPath $frontendDirectory
    try {
        & $pnpmCommand.Source exec vite build --outDir $distRoot --emptyOutDir |
            ForEach-Object { Write-Host $_ }
        if ($LASTEXITCODE -ne 0) { throw "$Phase release build failed." }
    }
    finally { Pop-Location }
    $artifactDigest = Get-DirectorySha256 -LiteralPath $distRoot

    [CatalogLiveJob]::Create("clsen-catalog-live-$runIdentifier-$Phase")
    $script:jobCreated = $true
    try {
        Invoke-SchemaPreflight -DatabaseEnvironment "APP_DATABASE_URL" -Component "api"
        $apiArguments = [string[]]@(
            "-m", "uvicorn", "app.main:app", "--app-dir", $backendDirectory,
            "--host", "127.0.0.1", "--port", "$apiPort"
        )
        $apiProcessId = [CatalogLiveJob]::Launch(
            $pythonExecutable, $apiArguments, $repositoryRoot,
            (Join-Path $runtimeRoot "logs\$Phase-fastapi.log")
        )
        $apiProcess = Get-Process -Id $apiProcessId -ErrorAction Stop
        Add-OwnedProcess -Process $apiProcess -Role "$Phase-fastapi" -RequiredCommandFragment "$apiPort"

        if ($Source -eq "p0_catalog") {
            Invoke-SchemaPreflight -DatabaseEnvironment "APP_TEST_RUNTIME_DATABASE_URL" -Component "worker"
            $workerArguments = [string[]]@(
                "-m", "app.worker.cli", "--database-environment",
                "APP_TEST_RUNTIME_DATABASE_URL", "--poll-seconds", "0.2"
            )
            $workerProcessId = [CatalogLiveJob]::Launch(
                $pythonExecutable, $workerArguments, $backendDirectory,
                (Join-Path $runtimeRoot "logs\$Phase-worker.log")
            )
            $workerProcess = Get-Process -Id $workerProcessId -ErrorAction Stop
            Add-OwnedProcess -Process $workerProcess -Role "$Phase-worker" -RequiredCommandFragment "app.worker.cli"
        }

        $viteSecretEnvironment = @{}
        foreach ($name in @(
            "APP_DATABASE_URL", "APP_MIGRATION_DATABASE_URL", "APP_TEST_DATABASE_URL",
            "APP_TEST_RUNTIME_DATABASE_URL", "APP_SESSION_SECRET"
        )) {
            $viteSecretEnvironment[$name] = [Environment]::GetEnvironmentVariable($name)
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
        try {
            $viteArguments = [string[]]@(
                $viteEntry, "preview", "--outDir", $distRoot,
                "--host", "127.0.0.1", "--port", "$frontendPort", "--strictPort"
            )
            $viteProcessId = [CatalogLiveJob]::Launch(
                $nodeCommand.Source, $viteArguments, $frontendDirectory,
                (Join-Path $runtimeRoot "logs\$Phase-vite.log")
            )
            $viteProcess = Get-Process -Id $viteProcessId -ErrorAction Stop
            Add-OwnedProcess -Process $viteProcess -Role "$Phase-vite" -RequiredCommandFragment "$frontendPort"
        }
        finally {
            foreach ($name in $viteSecretEnvironment.Keys) {
                [Environment]::SetEnvironmentVariable($name, $viteSecretEnvironment[$name])
            }
        }

        Wait-OwnedListener -Port $apiPort -RootProcessId $apiProcess.Id -Role "$Phase-fastapi" -Url "$apiUrl/api/health/ready"
        Wait-OwnedListener -Port $frontendPort -RootProcessId $viteProcess.Id -Role "$Phase-vite" -Url "$frontendUrl/api/health/ready"

        $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json -AsHashtable
        $manifest.state = "running"
        if (-not $manifest.details.ContainsKey("cutover_phases")) { $manifest.details.cutover_phases = @() }
        $manifest.details.cutover_phases += [ordered]@{
            phase = $Phase
            source = $Source
            artifact_digest = $artifactDigest
            artifact_root = $distRoot
            api_port = $apiPort
            frontend_port = $frontendPort
        }
        $manifest.details.processes = @($processRecords)
        $manifest.details.container_id = $containerId
        [IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))

        Push-Location -LiteralPath $frontendDirectory
        try {
            & $pnpmCommand.Source exec playwright test --config=playwright.catalog-live.config.ts --project=$Project |
                ForEach-Object { Write-Host $_ }
            if ($LASTEXITCODE -ne 0) { throw "$Phase live Playwright acceptance failed." }
        }
        finally { Pop-Location }
    }
    finally {
        Stop-LiveJob
    }
    return $artifactDigest
}

if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw "The project Python runtime was not found."
}
if (-not (Test-Path -LiteralPath $viteEntry -PathType Leaf)) {
    throw "The Vite runtime was not found; install frontend dependencies first."
}
if (-not (Test-Path -LiteralPath $privilegeManifestPath -PathType Leaf)) {
    throw "The database privilege manifest was not found."
}
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$pnpmCommand = Get-Command pnpm -ErrorAction SilentlyContinue
$script:dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($null -eq $nodeCommand -or $null -eq $pnpmCommand -or $null -eq $script:dockerCommand) {
    throw "Docker, Node.js, and pnpm are required by the live runner."
}
if ($Experience -and $Milestone -cne "Catalog" -and -not ($ExperienceOnly -and $Milestone -ceq "Products")) {
    throw "Experience mode supports Catalog, or Products with -ExperienceOnly."
}
$dockerVersion = @(& $script:dockerCommand.Source version --format "{{.Server.Version}}" 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "Docker is installed but its daemon is unavailable."
}
if ($ValidateOnly) {
    Write-Host "Live E2E prerequisites validated without execution."
    return
}

$jobType = @'
using System;
using System.Text;
using System.Runtime.InteropServices;

public static class CatalogLiveJob
{
    private const uint PROCESS_SET_QUOTA = 0x0100;
    private const uint PROCESS_TERMINATE = 0x0001;
    private const uint PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;
    private const uint JobObjectExtendedLimitInformation = 9;
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
    private const uint CREATE_SUSPENDED = 0x00000004;
    private const uint CREATE_BREAKAWAY_FROM_JOB = 0x01000000;
    private const uint CREATE_NO_WINDOW = 0x08000000;
    private const uint STARTF_USESTDHANDLES = 0x00000100;
    private const uint GENERIC_WRITE = 0x40000000;
    private const uint FILE_SHARE_READ = 0x00000001;
    private const uint FILE_SHARE_WRITE = 0x00000002;
    private const uint CREATE_ALWAYS = 2;
    private const uint FILE_ATTRIBUTE_NORMAL = 0x00000080;
    private const int STD_INPUT_HANDLE = -10;
    private static readonly IntPtr INVALID_HANDLE_VALUE = new IntPtr(-1);
    private static IntPtr handle = IntPtr.Zero;

    [StructLayout(LayoutKind.Sequential)]
    private struct SECURITY_ATTRIBUTES
    {
        public uint nLength;
        public IntPtr lpSecurityDescriptor;
        [MarshalAs(UnmanagedType.Bool)] public bool bInheritHandle;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
        public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct EXTENDED_LIMIT_INFORMATION
    {
        public BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO
    {
        public uint cb;
        public string lpReserved, lpDesktop, lpTitle;
        public uint dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars;
        public uint dwFillAttribute, dwFlags;
        public ushort wShowWindow, cbReserved2;
        public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION
    {
        public IntPtr hProcess, hThread;
        public uint dwProcessId, dwThreadId;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(IntPtr job, uint infoClass, IntPtr info, uint length);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint access, bool inherit, int processId);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool IsProcessInJob(IntPtr process, IntPtr job, out bool result);
    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(IntPtr value);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool CreateProcess(
        string applicationName, StringBuilder commandLine,
        IntPtr processAttributes, IntPtr threadAttributes,
        bool inheritHandles, uint creationFlags, IntPtr environment,
        string currentDirectory, ref STARTUPINFO startupInfo,
        out PROCESS_INFORMATION processInformation);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool TerminateProcess(IntPtr process, uint exitCode);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateFile(
        string fileName, uint desiredAccess, uint shareMode,
        ref SECURITY_ATTRIBUTES securityAttributes, uint creationDisposition,
        uint flagsAndAttributes, IntPtr templateFile);
    [DllImport("kernel32.dll")]
    private static extern IntPtr GetStdHandle(int standardHandle);

    public static void Create(string name)
    {
        if (handle != IntPtr.Zero) throw new InvalidOperationException("job already exists");
        handle = CreateJobObject(IntPtr.Zero, name);
        if (handle == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
        var info = new EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        int length = Marshal.SizeOf(info);
        IntPtr pointer = Marshal.AllocHGlobal(length);
        try
        {
            Marshal.StructureToPtr(info, pointer, false);
            if (!SetInformationJobObject(handle, JobObjectExtendedLimitInformation, pointer, (uint)length))
                throw new System.ComponentModel.Win32Exception();
        }
        finally { Marshal.FreeHGlobal(pointer); }
    }

    public static void Assign(int processId)
    {
        if (handle == IntPtr.Zero) throw new InvalidOperationException("job does not exist");
        IntPtr process = OpenProcess(
            PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION,
            false,
            processId);
        if (process == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
        try
        {
            bool alreadyAssigned;
            if (!IsProcessInJob(process, handle, out alreadyAssigned))
                throw new System.ComponentModel.Win32Exception();
            if (alreadyAssigned) return;
            if (!AssignProcessToJobObject(handle, process))
                throw new System.ComponentModel.Win32Exception();
        }
        finally { CloseHandle(process); }
    }

    private static string Quote(string value)
    {
        if (value.Length > 0 && value.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
            return value;
        var result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char character in value)
        {
            if (character == '\\') { slashes++; continue; }
            if (character == '"')
            {
                result.Append('\\', slashes * 2 + 1).Append('"');
                slashes = 0;
                continue;
            }
            result.Append('\\', slashes).Append(character);
            slashes = 0;
        }
        result.Append('\\', slashes * 2).Append('"');
        return result.ToString();
    }

    public static int Launch(
        string executable, string[] arguments, string workingDirectory, string logPath)
    {
        if (handle == IntPtr.Zero) throw new InvalidOperationException("job does not exist");
        var command = new StringBuilder(Quote(executable));
        foreach (string argument in arguments) command.Append(' ').Append(Quote(argument));
        var security = new SECURITY_ATTRIBUTES();
        security.nLength = (uint)Marshal.SizeOf(security);
        security.bInheritHandle = true;
        IntPtr logHandle = CreateFile(
            logPath, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
            ref security, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, IntPtr.Zero);
        if (logHandle == INVALID_HANDLE_VALUE)
            throw new System.ComponentModel.Win32Exception();
        var startup = new STARTUPINFO();
        startup.cb = (uint)Marshal.SizeOf(startup);
        startup.dwFlags = STARTF_USESTDHANDLES;
        startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
        startup.hStdOutput = logHandle;
        startup.hStdError = logHandle;
        PROCESS_INFORMATION process = new PROCESS_INFORMATION();
        uint flags = CREATE_SUSPENDED | CREATE_BREAKAWAY_FROM_JOB | CREATE_NO_WINDOW;
        try
        {
            if (!CreateProcess(executable, command, IntPtr.Zero, IntPtr.Zero, true,
                flags, IntPtr.Zero, workingDirectory, ref startup, out process))
                throw new System.ComponentModel.Win32Exception();
            if (!AssignProcessToJobObject(handle, process.hProcess))
            {
                TerminateProcess(process.hProcess, 1);
                throw new System.ComponentModel.Win32Exception();
            }
            if (ResumeThread(process.hThread) == 0xFFFFFFFF)
            {
                TerminateProcess(process.hProcess, 1);
                throw new System.ComponentModel.Win32Exception();
            }
            return (int)process.dwProcessId;
        }
        finally
        {
            CloseHandle(logHandle);
            if (process.hThread != IntPtr.Zero) CloseHandle(process.hThread);
            if (process.hProcess != IntPtr.Zero) CloseHandle(process.hProcess);
        }
    }

    public static void Close()
    {
        if (handle == IntPtr.Zero) return;
        CloseHandle(handle);
        handle = IntPtr.Zero;
    }
}
'@

try {
    Assert-SafeRuntimeRoot | Out-Null
    New-Item -ItemType Directory -Path $runtimeRoot -ErrorAction Stop | Out-Null
    $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $aclOutput = @(& icacls.exe $runtimeRoot /inheritance:r /grant:r "*$currentSid`:(OI)(CI)F" 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not restrict the runner-owned runtime directory ACL."
    }
    New-Item -ItemType Directory -Path (Join-Path $runtimeRoot "logs") | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $runtimeRoot "states") | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $runtimeRoot "playwright") | Out-Null
    $manifest = [ordered]@{
        run_id = $runIdentifier
        database_name = $databaseName
        runtime_root = $runtimeRoot
        storage_root = $storageRoot
        state = "created"
        details = @{}
    }
    [IO.File]::WriteAllText(
        $manifestPath,
        ($manifest | ConvertTo-Json -Depth 10),
        [Text.UTF8Encoding]::new($false)
    )

    $dockerRun = @(
        & $script:dockerCommand.Source run --detach --rm `
            --name $containerName `
            --label $containerLabel `
            --publish "127.0.0.1::3306" `
            --env "MYSQL_ALLOW_EMPTY_PASSWORD=yes" `
            "mysql:8.0" `
            --character-set-server=utf8mb4 `
            --collation-server=utf8mb4_0900_ai_ci `
            --default-time-zone=+00:00 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Docker could not start the runner-owned Oracle MySQL 8.0 container."
    }
    $containerId = ($dockerRun -join "").Trim()
    if ($containerId -cnotmatch '\A[0-9a-f]{64}\z') {
        throw "Docker returned an invalid container identity."
    }
    $containerStarted = $true
    $mysqlReady = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        $ping = @(
            & $script:dockerCommand.Source exec $containerName `
                mysqladmin ping --protocol=TCP --host=127.0.0.1 `
                --port=3306 --user=root --silent 2>&1
        )
        if ($LASTEXITCODE -eq 0) {
            $mysqlReady = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $mysqlReady) {
        throw "Runner-owned MySQL did not become ready."
    }
    $copyCa = @(
        & $script:dockerCommand.Source cp `
            "${containerName}:/var/lib/mysql/ca.pem" `
            $caCertificatePath 2>&1
    )
    if (
        $LASTEXITCODE -ne 0 -or
        -not (Test-Path -LiteralPath $caCertificatePath -PathType Leaf)
    ) {
        throw "Runner-owned MySQL did not provide its TLS CA."
    }
    $portOutput = @(
        & $script:dockerCommand.Source port $containerName "3306/tcp" 2>&1
    )
    $portMatch = [regex]::Match(($portOutput -join "`n"), ':(?<port>[0-9]{1,5})\s*$')
    $mysqlPort = 0
    if (
        $LASTEXITCODE -ne 0 -or
        -not $portMatch.Success -or
        -not [int]::TryParse($portMatch.Groups["port"].Value, [ref]$mysqlPort) -or
        $mysqlPort -lt 1 -or $mysqlPort -gt 65535
    ) {
        throw "Docker returned an invalid runner-owned MySQL port."
    }

    $migrationUser = "clsen_live_migration"
    $runtimeUser = "clsen_live_runtime"
    $grantAdminUser = "clsen_live_grants"
    $migrationPassword = [guid]::NewGuid().ToString("N")
    $runtimePassword = [guid]::NewGuid().ToString("N")
    $grantAdminPassword = [guid]::NewGuid().ToString("N")
    $databaseIdentifier = ConvertTo-MySqlIdentifier -Value $databaseName
    $bootstrapSql = @"
SET GLOBAL log_bin_trust_function_creators = ON;
CREATE DATABASE $databaseIdentifier CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER '$migrationUser'@'%' IDENTIFIED WITH caching_sha2_password BY '$(ConvertTo-MySqlStringLiteral $migrationPassword)' REQUIRE SSL;
CREATE USER '$runtimeUser'@'%' IDENTIFIED WITH caching_sha2_password BY '$(ConvertTo-MySqlStringLiteral $runtimePassword)' REQUIRE SSL;
CREATE USER '$grantAdminUser'@'%' IDENTIFIED WITH caching_sha2_password BY '$(ConvertTo-MySqlStringLiteral $grantAdminPassword)' REQUIRE SSL;
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES, TRIGGER ON $databaseIdentifier.* TO '$migrationUser'@'%';
GRANT SELECT ON $databaseIdentifier.* TO '$runtimeUser'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON $databaseIdentifier.* TO '$grantAdminUser'@'%' WITH GRANT OPTION;
"@
    Invoke-ContainerSql -Sql $bootstrapSql -Operation "create isolated database identities"
    $migrationUrl = New-DatabaseUrl -User $migrationUser -Password $migrationPassword -Port $mysqlPort
    $runtimeUrl = New-DatabaseUrl -User $runtimeUser -Password $runtimePassword -Port $mysqlPort
    $grantAdminUrl = New-DatabaseUrl -User $grantAdminUser -Password $grantAdminPassword -Port $mysqlPort
    $env:APP_MIGRATION_DATABASE_URL = $migrationUrl
    $env:APP_TEST_DATABASE_URL = $migrationUrl
    $env:APP_TEST_RUNTIME_DATABASE_URL = $runtimeUrl
    $env:APP_TEST_RUN_ID = $runIdentifier

    Push-Location -LiteralPath $backendDirectory
    try {
        & $pythonExecutable -m alembic -c alembic.ini upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw "The runner-owned database migration failed."
        }
    }
    finally {
        Pop-Location
    }

    $privileges = Get-Content -Raw -LiteralPath $privilegeManifestPath |
        ConvertFrom-Json -AsHashtable
    if ($privileges.version -ne 5) {
        throw "The database privilege manifest version is not supported."
    }
    $grants = [Collections.Generic.List[string]]::new()
    foreach ($table in @($privileges.runtime.insert_only) + @($privileges.runtime.mutable_insert)) {
        $grants.Add("GRANT INSERT ON $databaseIdentifier.$(ConvertTo-MySqlIdentifier $table) TO '$runtimeUser'@'%';")
    }
    foreach ($table in @($privileges.runtime.update)) {
        $grants.Add("GRANT UPDATE ON $databaseIdentifier.$(ConvertTo-MySqlIdentifier $table) TO '$runtimeUser'@'%';")
    }
    foreach ($table in $privileges.runtime.update_columns.Keys) {
        $columns = @(
            foreach ($column in @($privileges.runtime.update_columns[$table])) {
                ConvertTo-MySqlIdentifier $column
            }
        )
        $grants.Add("GRANT UPDATE ($($columns -join ', ')) ON $databaseIdentifier.$(ConvertTo-MySqlIdentifier $table) TO '$runtimeUser'@'%';")
    }
    foreach ($table in @($privileges.runtime.delete)) {
        $grants.Add("GRANT DELETE ON $databaseIdentifier.$(ConvertTo-MySqlIdentifier $table) TO '$runtimeUser'@'%';")
    }
    Invoke-GrantAdminSql `
        -Sql ($grants -join "`n") `
        -DatabaseUrl $grantAdminUrl `
        -Operation "apply least-privilege runtime grants"

    $adminUsername = "catalog-live-admin-$runIdentifier"
    $adminPassword = [guid]::NewGuid().ToString("N") + "!Aa"
    $managerPassword = [guid]::NewGuid().ToString("N") + "!Mm"
    $viewerPassword = [guid]::NewGuid().ToString("N") + "!Vv"
    $env:CATALOG_LIVE_ADMIN_USERNAME = $adminUsername
    $env:CATALOG_LIVE_ADMIN_PASSWORD = $adminPassword
    Push-Location -LiteralPath $backendDirectory
    try {
        & $pythonExecutable -m tests.live.product_catalog_live_harness `
            --run-id $runIdentifier `
            --manifest $manifestPath `
            preflight
        if ($LASTEXITCODE -ne 0) {
            throw "The catalog live database preflight failed."
        }
        $seedArguments = @(
            "--run-id", $runIdentifier,
            "--manifest", $manifestPath,
            "seed"
        )
        if ($ExperienceOnly) { $seedArguments += "--include-catalog-experience" }
        & $pythonExecutable -m tests.live.product_catalog_live_harness @seedArguments
        if ($LASTEXITCODE -ne 0) {
            throw "The catalog live deterministic seed failed."
        }
    }
    finally {
        Pop-Location
        Remove-Item Env:CATALOG_LIVE_ADMIN_PASSWORD -ErrorAction SilentlyContinue
    }

    $env:APP_DATABASE_URL = $runtimeUrl
    $env:APP_STORAGE_ROOT = $storageRoot
    $env:APP_STORAGE_MAX_UPLOAD_BYTES = "16777216"
    $env:APP_STORAGE_LEASE_TTL_SECONDS = "300"
    $env:APP_STORAGE_LEASE_RENEW_INTERVAL_SECONDS = "60"
    $env:APP_STORAGE_ORPHAN_AGE_SECONDS = "86400"
    $env:APP_ENVIRONMENT = "test"
    $env:APP_LOG_LEVEL = "WARNING"
    $env:APP_SESSION_SECRET = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
    $env:APP_SESSION_COOKIE_SECURE = "false"
    $env:CATALOG_LIVE_RUN_ID = $runIdentifier
    $env:CATALOG_LIVE_RUNTIME_ROOT = $runtimeRoot
    $env:CATALOG_LIVE_MANIFEST = $manifestPath
    $env:CATALOG_LIVE_RESULT_PATH = $resultPath
    $env:CATALOG_LIVE_USERS_PATH = $usersPath
    $env:CATALOG_LIVE_TEARDOWN_MARKER = $teardownMarker
    $env:CATALOG_LIVE_EVIDENCE_PATH = $evidencePath
    $env:CATALOG_LIVE_ADMIN_USERNAME = $adminUsername
    $env:CATALOG_LIVE_ADMIN_PASSWORD = $adminPassword
    $env:CATALOG_LIVE_MANAGER_PASSWORD = $managerPassword
    $env:CATALOG_LIVE_VIEWER_PASSWORD = $viewerPassword
    $env:CATALOG_LIVE_ADMIN_STATE = Join-Path $runtimeRoot "states\admin.json"
    $env:CATALOG_LIVE_MANAGER_STATE = Join-Path $runtimeRoot "states\manager.json"
    $env:CATALOG_LIVE_VIEWER_STATE = Join-Path $runtimeRoot "states\viewer.json"
    $env:CATALOG_LIVE_PYTHON = $pythonExecutable
    $env:CATALOG_LIVE_BACKEND_DIR = $backendDirectory

    Add-Type -TypeDefinition $jobType -Language CSharp
    if ($Milestone -in @("Cutover", "Release", "All")) {
        $legacyBeforeDigest = Invoke-CutoverPhase `
            -Phase "legacy-before" `
            -Source "legacy_parser" `
            -Project "product-cutover-legacy-before" `
            -ReuseStates $false `
            -KeepStates $true
        $p0Project = if ($Milestone -in @("Release", "All")) {
            "product-release"
        }
        else {
            "product-cutover"
        }
        $p0Digest = Invoke-CutoverPhase `
            -Phase "p0" `
            -Source "p0_catalog" `
            -Project $p0Project `
            -ReuseStates $true `
            -KeepStates $true
        $p0BusinessChecksum = Get-CatalogBusinessChecksum -DatabaseUrl $migrationUrl
        $legacyRollbackDigest = Invoke-CutoverPhase `
            -Phase "legacy-rollback" `
            -Source "legacy_parser" `
            -Project "product-cutover-legacy-rollback" `
            -ReuseStates $true `
            -KeepStates $false
        $rollbackBusinessChecksum = Get-CatalogBusinessChecksum -DatabaseUrl $migrationUrl
        if ($rollbackBusinessChecksum -cne $p0BusinessChecksum) {
            throw "Cutover rollback changed catalog, publication, dedup, fact, or audit business state."
        }
        if (-not (Test-Path -LiteralPath $teardownMarker -PathType Leaf)) {
            throw "Cutover final Playwright teardown did not remove private browser states."
        }
        Push-Location -LiteralPath $backendDirectory
        try {
            & $pythonExecutable -m tests.live.product_catalog_live_harness `
                --run-id $runIdentifier `
                --manifest $manifestPath `
                evidence `
                --result $resultPath `
                --output $evidencePath
            if ($LASTEXITCODE -ne 0) { throw "Cutover live evidence verification failed." }
        }
        finally { Pop-Location }
        $evidence = Get-Content -Raw -LiteralPath $evidencePath | ConvertFrom-Json -AsHashtable
        $evidence.cutover = [ordered]@{
            phases = @("legacy-before", "p0", "legacy-rollback")
            sources = @("legacy_parser", "p0_catalog", "legacy_parser")
            artifact_digests = @($legacyBeforeDigest, $p0Digest, $legacyRollbackDigest)
            p0_business_checksum = $p0BusinessChecksum
            rollback_business_checksum = $rollbackBusinessChecksum
            zero_business_writes_on_rollback = $true
        }
        [IO.File]::WriteAllText($evidencePath, ($evidence | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))
    }
    else {
    $apiPort = Get-FreeLoopbackPort
    do {
        $frontendPort = Get-FreeLoopbackPort
    } while ($frontendPort -eq $apiPort)
    $apiUrl = "http://127.0.0.1:$apiPort"
    $frontendUrl = "http://127.0.0.1:$frontendPort"
    $env:APP_DATABASE_URL = $runtimeUrl
    $env:APP_STORAGE_ROOT = $storageRoot
    $env:APP_STORAGE_MAX_UPLOAD_BYTES = "16777216"
    $env:APP_STORAGE_LEASE_TTL_SECONDS = "300"
    $env:APP_STORAGE_LEASE_RENEW_INTERVAL_SECONDS = "60"
    $env:APP_STORAGE_ORPHAN_AGE_SECONDS = "86400"
    $env:APP_ENVIRONMENT = "test"
    $env:APP_LOG_LEVEL = "WARNING"
    $env:APP_PRODUCT_ANALYTICS_SOURCE = $releaseSource
    $env:VITE_PRODUCT_ANALYTICS_SOURCE = $releaseSource
    $env:APP_SESSION_SECRET = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
    $env:APP_SESSION_COOKIE_SECURE = "false"
    $env:APP_CORS_ALLOWED_ORIGINS = $frontendUrl
    $env:CATALOG_LIVE_API_URL = $apiUrl

    [CatalogLiveJob]::Create("clsen-catalog-live-$runIdentifier")
    $jobCreated = $true
    Invoke-SchemaPreflight -DatabaseEnvironment "APP_DATABASE_URL" -Component "api"
    $apiArguments = [string[]]@(
        "-m", "uvicorn", "app.main:app", "--app-dir", $backendDirectory,
        "--host", "127.0.0.1", "--port", "$apiPort"
    )
    $apiProcessId = [CatalogLiveJob]::Launch(
        $pythonExecutable,
        $apiArguments,
        $repositoryRoot,
        (Join-Path $runtimeRoot "logs\fastapi.log")
    )
    $apiProcess = Get-Process -Id $apiProcessId -ErrorAction Stop
    Add-OwnedProcess -Process $apiProcess -Role "fastapi" -RequiredCommandFragment "$apiPort"
    Invoke-SchemaPreflight -DatabaseEnvironment "APP_TEST_RUNTIME_DATABASE_URL" -Component "worker"
    $workerArguments = [string[]]@(
        "-m", "app.worker.cli", "--database-environment",
        "APP_TEST_RUNTIME_DATABASE_URL", "--poll-seconds", "0.2"
    )
    $workerProcessId = [CatalogLiveJob]::Launch(
        $pythonExecutable,
        $workerArguments,
        $backendDirectory,
        (Join-Path $runtimeRoot "logs\worker.log")
    )
    $workerProcess = Get-Process -Id $workerProcessId -ErrorAction Stop
    Add-OwnedProcess -Process $workerProcess -Role "worker" -RequiredCommandFragment "app.worker.cli"

    $viteSecretEnvironment = @{}
    foreach ($name in @(
        "APP_DATABASE_URL", "APP_MIGRATION_DATABASE_URL", "APP_TEST_DATABASE_URL",
        "APP_TEST_RUNTIME_DATABASE_URL", "APP_SESSION_SECRET"
    )) {
        $viteSecretEnvironment[$name] = [Environment]::GetEnvironmentVariable($name)
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
    try {
        $viteArguments = [string[]]@(
            $viteEntry, "--host", "127.0.0.1", "--port", "$frontendPort",
            "--strictPort"
        )
        $viteProcessId = [CatalogLiveJob]::Launch(
            $nodeCommand.Source,
            $viteArguments,
            $frontendDirectory,
            (Join-Path $runtimeRoot "logs\vite.log")
        )
        $viteProcess = Get-Process -Id $viteProcessId -ErrorAction Stop
        Add-OwnedProcess -Process $viteProcess -Role "vite" -RequiredCommandFragment "$frontendPort"
    }
    finally {
        foreach ($name in $viteSecretEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable($name, $viteSecretEnvironment[$name])
        }
    }

    Write-Host "Runner-owned services: api=$apiPort frontend=$frontendPort"
    Wait-OwnedListener `
        -Port $apiPort `
        -RootProcessId $apiProcess.Id `
        -Role "fastapi" `
        -Url "$apiUrl/api/health/ready"
    Wait-OwnedListener `
        -Port $frontendPort `
        -RootProcessId $viteProcess.Id `
        -Role "vite" `
        -Url "$frontendUrl/api/health/ready"
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json -AsHashtable
    if ($manifest.state -cne "seeded" -or $manifest.run_id -cne $runIdentifier) {
        throw "The live manifest could not prove runner ownership before browser startup."
    }
    $manifest.state = "running"
    $manifest.details.processes = @($processRecords)
    $manifest.details.api_port = $apiPort
    $manifest.details.frontend_port = $frontendPort
    $manifest.details.container_id = $containerId
    [IO.File]::WriteAllText(
        $manifestPath,
        ($manifest | ConvertTo-Json -Depth 10),
        [Text.UTF8Encoding]::new($false)
    )

    $env:CATALOG_LIVE_FRONTEND_URL = $frontendUrl
    $env:CATALOG_LIVE_RUN_ID = $runIdentifier
    $env:CATALOG_LIVE_RUNTIME_ROOT = $runtimeRoot
    $env:CATALOG_LIVE_MANIFEST = $manifestPath
    $env:CATALOG_LIVE_RESULT_PATH = $resultPath
    $env:CATALOG_LIVE_USERS_PATH = $usersPath
    $env:CATALOG_LIVE_TEARDOWN_MARKER = $teardownMarker
    $env:CATALOG_LIVE_EVIDENCE_PATH = $evidencePath
    $env:CATALOG_LIVE_ADMIN_USERNAME = $adminUsername
    $env:CATALOG_LIVE_ADMIN_PASSWORD = $adminPassword
    $env:CATALOG_LIVE_MANAGER_PASSWORD = $managerPassword
    $env:CATALOG_LIVE_VIEWER_PASSWORD = $viewerPassword
    $env:CATALOG_LIVE_ADMIN_STATE = Join-Path $runtimeRoot "states\admin.json"
    $env:CATALOG_LIVE_MANAGER_STATE = Join-Path $runtimeRoot "states\manager.json"
    $env:CATALOG_LIVE_VIEWER_STATE = Join-Path $runtimeRoot "states\viewer.json"
    $env:CATALOG_LIVE_PLAYWRIGHT_OUTPUT = Join-Path $runtimeRoot "playwright"
    $env:CATALOG_LIVE_PYTHON = $pythonExecutable
    $env:CATALOG_LIVE_BACKEND_DIR = $backendDirectory
    if ($Experience) {
        $env:CATALOG_LIVE_KEEP_STATES = "1"
    }
    else {
        Remove-Item Env:CATALOG_LIVE_KEEP_STATES -ErrorAction SilentlyContinue
    }

    if (-not $ExperienceOnly) {
        Push-Location -LiteralPath $frontendDirectory
        try {
            & $pnpmCommand.Source exec playwright test `
                --config=playwright.catalog-live.config.ts `
                --project=$playwrightProject
            if ($LASTEXITCODE -ne 0) {
                throw "$Milestone live Playwright acceptance failed."
            }
        }
        finally {
            Pop-Location
        }
        if (
            -not $Experience -and
            -not (Test-Path -LiteralPath $teardownMarker -PathType Leaf)
        ) {
            throw "Playwright global teardown did not prove private state cleanup."
        }
        Push-Location -LiteralPath $backendDirectory
        try {
            & $pythonExecutable -m tests.live.product_catalog_live_harness `
                --run-id $runIdentifier `
                --manifest $manifestPath `
                evidence `
                --result $resultPath `
                --output $evidencePath
            if ($LASTEXITCODE -ne 0) {
                throw "$Milestone live evidence verification failed."
            }
        }
        finally {
            Pop-Location
        }
    }
    if ($Experience) {
        $manifest = Get-Content -Raw -LiteralPath $manifestPath |
            ConvertFrom-Json -AsHashtable
        if (
            $manifest.state -cne $(
                if ($ExperienceOnly) { "running" } else { "evidence_collected" }
            ) -or
            $manifest.run_id -cne $runIdentifier -or
            $manifest.database_name -cne $databaseName
        ) {
            throw "The live manifest could not prove experience ownership."
        }
        $experienceUsername = if ($ExperienceOnly) {
            $adminUsername
        }
        else {
            "catalog-live-manager-$runIdentifier"
        }
        $experiencePassword = if ($ExperienceOnly) {
            $adminPassword
        }
        else {
            $managerPassword
        }
        $experienceCredentials = [ordered]@{
            run_id = $runIdentifier
            username = $experienceUsername
            password = $experiencePassword
            storage_state = $env:CATALOG_LIVE_MANAGER_STATE
        }
        [IO.File]::WriteAllText(
            $experienceCredentialsPath,
            ($experienceCredentials | ConvertTo-Json -Compress),
            [Text.UTF8Encoding]::new($false)
        )
        $manifest.state = "experience_running"
        $manifest.details.experience = [ordered]@{
            frontend_url = "$frontendUrl/catalog"
            stop_marker = $experienceStopMarker
            credentials_path = $experienceCredentialsPath
        }
        [IO.File]::WriteAllText(
            $manifestPath,
            ($manifest | ConvertTo-Json -Depth 10),
            [Text.UTF8Encoding]::new($false)
        )
        Write-Host "Catalog experience READY."
        Write-Host "URL: $frontendUrl/catalog"
        Write-Host "Run ID: $runIdentifier"
        Write-Host "Stop: .\scripts\stop-product-catalog-experience.ps1 -RunId $runIdentifier"
        while (-not (Test-Path -LiteralPath $experienceStopMarker -PathType Leaf)) {
            foreach ($role in @("fastapi", "worker", "vite")) {
                $record = $processRecords |
                    Where-Object { $_.role -ceq $role } |
                    Select-Object -First 1
                if ($null -eq $record) {
                    throw "Experience monitor lost the runner-owned $role identity."
                }
                Assert-OwnedProcessIdentity -Record $record
                if ($null -eq (Get-Process -Id $record.pid -ErrorAction SilentlyContinue)) {
                    throw "Experience monitor detected that $role exited."
                }
            }
            $actualContainerLabel = @(
                & $script:dockerCommand.Source inspect `
                    --format '{{ index .Config.Labels "clsen.catalog-live.run" }}' `
                    $containerName 2>&1
            )
            if (
                $LASTEXITCODE -ne 0 -or
                ($actualContainerLabel -join "").Trim() -cne $runIdentifier
            ) {
                throw "Experience monitor lost the runner-owned database container."
            }
            try {
                $apiReady = Invoke-WebRequest `
                    -Uri "$apiUrl/api/health/ready" `
                    -UseBasicParsing `
                    -TimeoutSec 2
                $frontendReady = Invoke-WebRequest `
                    -Uri "$frontendUrl/api/health/ready" `
                    -UseBasicParsing `
                    -TimeoutSec 2
                if ($apiReady.StatusCode -ne 200 -or $frontendReady.StatusCode -ne 200) {
                    throw "Experience health endpoint returned a non-success status."
                }
            }
            catch {
                throw "Experience monitor detected an unhealthy API or frontend."
            }
            Start-Sleep -Seconds 2
        }
        $stopRequest = Get-Content -Raw -LiteralPath $experienceStopMarker |
            ConvertFrom-Json -AsHashtable
        if (
            $stopRequest.Count -ne 3 -or
            $stopRequest.run_id -cne $runIdentifier -or
            $stopRequest.action -cne "stop" -or
            [string]::IsNullOrWhiteSpace([string]$stopRequest.requested_at)
        ) {
            throw "Experience stop marker failed ownership validation."
        }
        Write-Host "Catalog experience stop request accepted."
    }
    }
    $success = $true
}
catch {
    $runFailure = $_
}
finally {
    $cleanupErrors = [Collections.Generic.List[string]]::new()
    if ($jobCreated) {
        try {
            foreach ($record in $processRecords) {
                Assert-OwnedProcessIdentity -Record $record
            }
            [CatalogLiveJob]::Close()
            $jobCreated = $false
        }
        catch {
            $cleanupErrors.Add("process job cleanup failed")
        }
    }
    if ($containerStarted) {
        try {
            $actualId = @(
                & $script:dockerCommand.Source inspect `
                    --format '{{.Id}}' $containerName 2>&1
            )
            $actualLabel = @(
                & $script:dockerCommand.Source inspect `
                    --format '{{ index .Config.Labels "clsen.catalog-live.run" }}' `
                    $containerName 2>&1
            )
            if (
                $LASTEXITCODE -ne 0 -or
                ($actualId -join "").Trim() -cne $containerId -or
                ($actualLabel -join "").Trim() -cne $runIdentifier
            ) {
                throw "container ownership changed"
            }
            $removeContainer = @(
                & $script:dockerCommand.Source rm --force $containerId 2>&1
            )
            if ($LASTEXITCODE -ne 0) {
                throw "container removal failed"
            }
            $containerStarted = $false
        }
        catch {
            $cleanupErrors.Add("container cleanup failed")
        }
    }

    foreach ($name in $managedEnvironment) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name])
    }
    $migrationPassword = $null
    $runtimePassword = $null
    $grantAdminPassword = $null
    $adminPassword = $null
    $managerPassword = $null
    $viewerPassword = $null
    $resolvedRuntimeRoot = Assert-SafeRuntimeRoot
    if (-not $success -and (Test-Path -LiteralPath $resolvedRuntimeRoot)) {
        $diagnosticPath = Join-Path $temporaryRoot "clsen-catalog-live-failure-$runIdentifier.log"
        $diagnostics = [Collections.Generic.List[string]]::new()
        foreach ($logPath in Get-ChildItem -LiteralPath (Join-Path $resolvedRuntimeRoot "logs") -File -ErrorAction SilentlyContinue) {
            $diagnostics.Add("==== $($logPath.Name) ====")
            foreach ($line in Get-Content -LiteralPath $logPath.FullName -Tail 100 -ErrorAction SilentlyContinue) {
                $diagnostics.Add($line)
            }
        }
        [IO.File]::WriteAllLines($diagnosticPath, $diagnostics, [Text.UTF8Encoding]::new($false))
        Write-Warning "Catalog live failure diagnostics: $diagnosticPath"
    }
    if (Test-Path -LiteralPath $resolvedRuntimeRoot) {
        try {
            Remove-Item -LiteralPath $resolvedRuntimeRoot -Recurse -Force
        }
        catch {
            $cleanupErrors.Add("runtime storage cleanup failed")
        }
    }
    if ($success -and $cleanupErrors.Count -eq 0 -and -not $ExperienceOnly) {
        $evidence = Get-Content -Raw -LiteralPath $evidencePath |
            ConvertFrom-Json -AsHashtable
        $evidence.cleanup = "PASS"
        $evidence.cleanup_checks = @(
            "job_object_closed",
            "container_label_verified_and_removed",
            "private_storage_states_removed",
            "runtime_root_removed"
        )
        [IO.File]::WriteAllText(
            $evidencePath,
            ($evidence | ConvertTo-Json -Depth 10),
            [Text.UTF8Encoding]::new($false)
        )
        Write-Host "$Milestone live acceptance PASS."
        Write-Host "Evidence: $evidencePath"
    }
    elseif ($success -and $cleanupErrors.Count -eq 0) {
        Write-Host "Catalog experience stopped."
    }
    elseif ($cleanupErrors.Count -gt 0) {
        $cleanupFailure = "Catalog live cleanup failed closed: $($cleanupErrors -join ', ')."
    }
}

if ($null -ne $runFailure) {
    throw $runFailure
}
if ($null -ne $cleanupFailure) {
    throw $cleanupFailure
}
