#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter()]
    [switch]$SkipBuild,

    [Parameter()]
    [switch]$SkipMigrationRoundtrip,

    [Parameter()]
    [switch]$SkipBackupRestore,

    [Parameter()]
    [switch]$DisposableTestRun
)

$ErrorActionPreference = "Stop"
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$composeFile = Join-Path $PSScriptRoot "docker-compose.yml"
$secretRoot = Join-Path $PSScriptRoot "secrets"
$previousBackendSource = [Environment]::GetEnvironmentVariable(
    "APP_PRODUCT_ANALYTICS_SOURCE",
    "Process"
)
$previousFrontendSource = [Environment]::GetEnvironmentVariable(
    "VITE_PRODUCT_ANALYTICS_SOURCE",
    "Process"
)
$env:APP_PRODUCT_ANALYTICS_SOURCE = "p0_catalog"
$env:VITE_PRODUCT_ANALYTICS_SOURCE = "p0_catalog"
$composeInvocationArguments = [Collections.Generic.List[string]]::new()
$composeInvocationArguments.Add("-f")
$composeInvocationArguments.Add($composeFile)
$disposableCleanupProfiles = @(
    "--profile", "operations",
    "--profile", "verification",
    "--profile", "maintenance",
    "--profile", "load-test"
)
$disposableOverridePath = $null
$disposableComposeStarted = $false
$previousBindAddress = [Environment]::GetEnvironmentVariable("BIND_ADDRESS", "Process")
$previousHttpsPort = [Environment]::GetEnvironmentVariable("HTTPS_PORT", "Process")

if (-not (Test-Path -LiteralPath $composeFile -PathType Leaf)) {
    throw "The deployment compose file is unavailable."
}
if (-not (Test-Path -LiteralPath $secretRoot -PathType Container)) {
    throw "Run ops/bootstrap-secrets.ps1 before deployment verification."
}

if ($DisposableTestRun) {
    $runIdentifier = [guid]::NewGuid().ToString("N")
    $composeProjectName = "clsen-deployment-verify-$($runIdentifier.Substring(0, 12))"
    $disposableOverridePath = Join-Path `
        ([IO.Path]::GetTempPath()) `
        "$composeProjectName.yml"
    $disposableDatabase = "clsen_data_test_$($runIdentifier.Substring(0, 16))"
    $override = @"
services:
  mysql:
    environment:
      MYSQL_DATABASE: $disposableDatabase
  migrate:
    environment:
      APP_DEPLOYMENT_DATABASE: $disposableDatabase
      APP_DEPLOYMENT_TEST_DATABASE: $disposableDatabase
  backend:
    environment:
      APP_DEPLOYMENT_DATABASE: $disposableDatabase
  worker:
    environment:
      APP_DEPLOYMENT_DATABASE: $disposableDatabase
  test-runner:
    environment:
      APP_DEPLOYMENT_DATABASE: $disposableDatabase
      APP_DEPLOYMENT_TEST_DATABASE: $disposableDatabase
      APP_TEST_DATABASE_SCOPE: disposable-compose
      APP_TEST_COMPOSE_PROJECT: $composeProjectName
      APP_TEST_RUN_ID: $runIdentifier
  verification-backend:
    environment:
      APP_DEPLOYMENT_DATABASE: $disposableDatabase
  maintenance:
    environment:
      APP_DEPLOYMENT_DATABASE: $disposableDatabase
  restore-verifier:
    environment:
      APP_DEPLOYMENT_DATABASE: $disposableDatabase
"@
    [IO.File]::WriteAllText(
        $disposableOverridePath,
        $override,
        [Text.UTF8Encoding]::new($false)
    )
    $composeInvocationArguments.Add("-f")
    $composeInvocationArguments.Add($disposableOverridePath)
    $composeInvocationArguments.Add("--project-name")
    $composeInvocationArguments.Add($composeProjectName)
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory, ValueFromRemainingArguments)]
        [string[]]$Arguments
    )

    & docker compose @composeInvocationArguments @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed with exit code $LASTEXITCODE."
    }
}

function Invoke-ComposeCaptured {
    param(
        [Parameter(Mandatory, ValueFromRemainingArguments)]
        [string[]]$Arguments
    )

    $output = @(& docker compose @composeInvocationArguments @Arguments 2>&1)
    $output | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed with exit code $LASTEXITCODE."
    }
    return $output
}

function Wait-ServiceHealth {
    param(
        [Parameter(Mandatory)]
        [string]$Service,

        [Parameter()]
        [int]$TimeoutSeconds = 120
    )

    $containerId = (& docker compose @composeInvocationArguments ps -q $Service).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $containerId) {
        throw "Container for service '$Service' is unavailable."
    }
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $status = (& docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $containerId).Trim()
        if ($LASTEXITCODE -ne 0) {
            throw "Could not inspect service '$Service'."
        }
        if ($status -eq "healthy") {
            return
        }
        if ($status -in @("unhealthy", "exited", "dead")) {
            Invoke-Compose logs --tail 100 $Service
            throw "Service '$Service' entered state '$status'."
        }
        Start-Sleep -Seconds 2
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Service '$Service' did not become healthy within $TimeoutSeconds seconds."
}

Push-Location $repositoryRoot
try {
    if ($DisposableTestRun) {
        # Let Docker allocate an isolated loopback port without a check/bind race.
        $env:BIND_ADDRESS = "127.0.0.1"
        $env:HTTPS_PORT = "0"
    }
    Invoke-Compose config --quiet
    if (-not $SkipBuild) {
        Invoke-Compose --profile operations --profile verification --profile maintenance `
            --profile load-test build --pull
    }
    if ($DisposableTestRun) { $disposableComposeStarted = $true }
    Invoke-Compose --profile operations run --rm migrate
    Invoke-Compose up --detach
    foreach ($service in @("mysql", "backend", "worker", "frontend", "nginx")) {
        Wait-ServiceHealth -Service $service
    }

    $readinessUri = "https://localhost:8443/api/health/ready"
    if ($DisposableTestRun) {
        $binding = @(& docker compose @composeInvocationArguments port nginx 8443)
        if (
            $LASTEXITCODE -ne 0 -or $binding.Count -ne 1 -or
            $binding[0] -notmatch '^127\.0\.0\.1:([0-9]+)$'
        ) {
            throw "Disposable HTTPS loopback binding is unavailable."
        }
        $httpsPort = [int]$Matches[1]
        if ($httpsPort -lt 1 -or $httpsPort -gt 65535) {
            throw "Disposable HTTPS port is invalid."
        }
        $readinessUri = "https://localhost:$httpsPort/api/health/ready"
    }
    $ready = Invoke-WebRequest `
        -Uri $readinessUri `
        -SkipCertificateCheck
    if ($ready.StatusCode -ne 200) {
        throw "HTTPS readiness did not return 200."
    }
    foreach ($header in @(
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "X-Content-Type-Options"
    )) {
        if (-not $ready.Headers.ContainsKey($header)) {
            throw "HTTPS readiness omitted security header '$header'."
        }
    }

    if ($DisposableTestRun) {
        Invoke-Compose stop nginx frontend backend worker
    }

    Invoke-Compose --profile load-test stop verification-nginx verification-backend
    # Reuse the matrix's exact historical nodes, limited to this verifier's files.
    $historicalTestFiles = @(
        "tests/integration/test_stage_five_schema.py",
        "tests/integration/test_stage_six_schema.py",
        "tests/integration/test_admin_operation_permissions.py"
    )
    if (-not $SkipMigrationRoundtrip) {
        $historicalTestFiles += "tests/integration/test_migrations.py"
    }
    $historicalNodes = @(
        Get-Content -LiteralPath (Join-Path $repositoryRoot "backend/tests/fixtures/ci/mysql-historical-nodeids.txt") |
            Where-Object { $_ -and -not $_.StartsWith("#") } |
            Where-Object { $historicalTestFiles -ccontains ($_ -split "::", 2)[0] }
    )
    $historicalExclusions = @($historicalNodes | ForEach-Object { "--deselect=$_" })
    # Historical roundtrips must precede irreversible current-head migrations.
    Invoke-Compose --profile operations run --rm migrate reset-test-database --empty
    Invoke-Compose --profile verification run --rm test-runner `
        pytest @historicalNodes --require-mysql -q -x
    Invoke-Compose --profile operations run --rm migrate reset-test-database

    Invoke-Compose --profile verification run --rm test-runner `
        pytest tests/integration/test_database_constraints.py --require-mysql -q
    foreach ($testFile in @(
        "tests/integration/test_stage_five_schema.py",
        "tests/integration/test_stage_six_schema.py",
        "tests/integration/test_draft_transactions.py",
        "tests/integration/test_draft_date_reassignment.py"
    )) {
        Invoke-Compose --profile verification run --rm test-runner `
            pytest $testFile --require-mysql -q @historicalExclusions
    }
    Invoke-Compose --profile verification run --rm test-runner pytest `
        tests/integration/test_admin_management_api.py `
        tests/integration/test_admin_operation_permissions.py `
        tests/integration/test_authentication_api.py `
        tests/integration/test_data_calendar_api.py `
        tests/integration/test_review_workspace_api.py `
        --require-mysql -q @historicalExclusions
    Invoke-Compose --profile verification run --rm test-runner pytest `
        tests/integration/test_review_workflow.py `
        tests/integration/test_publication_transactions.py `
        tests/integration/test_publication_concurrency.py `
        --require-mysql -q
    Invoke-Compose --profile verification run --rm test-runner `
        pytest tests/integration/test_published_analytics.py --require-mysql -q

    Invoke-Compose --profile operations run --rm migrate reset-test-database
    Invoke-Compose --profile verification run --rm test-runner pytest `
        tests/integration/test_admin_cli.py `
        tests/integration/test_backup_write_barrier.py `
        tests/integration/test_file_ingest.py `
        tests/integration/test_outbox_worker.py `
        tests/integration/test_parse_workflow.py `
        --require-mysql -q

    Invoke-Compose --profile operations run --rm migrate reset-test-database
    Invoke-Compose run --rm edge-tls-init
    Invoke-Compose --profile load-test up --detach --force-recreate `
        verification-backend verification-nginx
    Wait-ServiceHealth -Service verification-backend
    Wait-ServiceHealth -Service verification-nginx
    Invoke-Compose --profile verification --profile load-test run --rm `
        --env APP_DEPLOYMENT_HTTPS_BASE_URL=https://verification-nginx:9443 `
        --env APP_DEPLOYMENT_HTTPS_CA=/run/secrets/tls_certificate `
        test-runner pytest tests/integration/test_server_deployment_load.py `
        --require-mysql -q
    Invoke-Compose --profile load-test stop verification-nginx verification-backend

    if (-not $SkipBackupRestore) {
        $keyringState = Invoke-ComposeCaptured --profile maintenance run --rm `
            --entrypoint sh maintenance -ec `
            'if [ -s /var/lib/clsen/keyring/backup-keyring.json ]; then echo exists; else echo missing; fi'
        if ($keyringState -contains "missing") {
            Invoke-Compose --profile maintenance run --rm maintenance maintenance `
                keyring-init `
                --path /var/lib/clsen/keyring/backup-keyring.json `
                --key-id server-initial
        }
        $backupOutput = Invoke-ComposeCaptured --profile maintenance run --rm `
            maintenance maintenance backup `
            --destination /var/lib/clsen/backups `
            --keyring /var/lib/clsen/keyring/backup-keyring.json
        $backupJsonLine = $backupOutput | Where-Object { $_ -match '^\{"status"' } | Select-Object -Last 1
        if (-not $backupJsonLine) {
            throw "Backup did not return a machine-readable success result."
        }
        $backupResult = $backupJsonLine | ConvertFrom-Json
        if ($backupResult.status -ne "succeeded") {
            throw "Backup did not succeed."
        }
        Invoke-Compose --profile maintenance run --rm restore-verifier `
            restore-verify `
            --backup-directory $backupResult.directory `
            --temporary-root /var/lib/clsen/restore-tests `
            --keyring /var/lib/clsen/keyring/backup-keyring.json `
            --cleanup
    }

    Write-Host "Server deployment verification completed successfully."
}
finally {
    if ($DisposableTestRun -and $disposableComposeStarted) {
        & docker compose @composeInvocationArguments @disposableCleanupProfiles `
            down --volumes --remove-orphans
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Disposable deployment verification cleanup failed."
        }
    }
    if (
        $null -ne $disposableOverridePath -and
        (Test-Path -LiteralPath $disposableOverridePath -PathType Leaf)
    ) {
        Remove-Item -LiteralPath $disposableOverridePath -Force
    }
    [Environment]::SetEnvironmentVariable(
        "APP_PRODUCT_ANALYTICS_SOURCE",
        $previousBackendSource,
        "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "VITE_PRODUCT_ANALYTICS_SOURCE",
        $previousFrontendSource,
        "Process"
    )
    if ($DisposableTestRun) {
        [Environment]::SetEnvironmentVariable("BIND_ADDRESS", $previousBindAddress, "Process")
        [Environment]::SetEnvironmentVariable("HTTPS_PORT", $previousHttpsPort, "Process")
    }
    Pop-Location
}
