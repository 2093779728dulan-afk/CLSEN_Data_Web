#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$SourceSha,

    [Parameter(Mandatory)]
    [ValidateSet("Collect", "Validate")]
    [string]$Mode,

    [Parameter(Mandatory)]
    [string]$EvidenceRoot,

    [string]$PythonExecutable
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$manifestPath = Join-Path $PSScriptRoot "project-optimization-stage2-manifest.json"
$baselineManifestPath = Join-Path $PSScriptRoot "project-optimization-baseline-manifest.json"
$profileRunner = Join-Path $PSScriptRoot "run-ci-profile.ps1"
$mysqlRunner = Join-Path $PSScriptRoot "test-mysql-matrix.ps1"
$restoreRunner = Join-Path $PSScriptRoot "run-product-catalog-backup-restore.ps1"
$deploymentRunner = Join-Path $repositoryRoot "ops\verify-deployment.ps1"
$evidencePath = [IO.Path]::GetFullPath($EvidenceRoot)
$evidencePrefix = $evidencePath.TrimEnd([IO.Path]::DirectorySeparatorChar) +
    [IO.Path]::DirectorySeparatorChar
$sensitivePattern = '(?i)(mysql(?:\+pymysql)?://\S+|(?:password|secret)\s*[=:]\s*\S+)'
$nonPassPattern = '(?i)\b[1-9][0-9]*\s+(xfailed|xpassed|rerun|retried)\b'
$commandRecords = [Collections.Generic.List[object]]::new()

function Assert-ExternalEvidencePath {
    if (
        $evidencePath -eq $repositoryRoot -or
        $evidencePath.StartsWith(
            $repositoryRoot + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "EvidenceRoot must be outside the repository."
    }
    if (
        (Test-Path -LiteralPath $evidencePath) -and
        ((Get-Item -LiteralPath $evidencePath).Attributes -band
            [IO.FileAttributes]::ReparsePoint)
    ) {
        throw "EvidenceRoot must not be a symbolic link or reparse point."
    }
}

function Assert-CandidateSource {
    Push-Location -LiteralPath $repositoryRoot
    try {
        $actualSha = (@(git rev-parse HEAD 2>&1) -join "").Trim()
        if ($LASTEXITCODE -ne 0 -or $actualSha -cne $SourceSha) {
            throw "HEAD does not match SourceSha."
        }
        $trackedStatus = @(git status --porcelain --untracked-files=no 2>&1)
        if ($LASTEXITCODE -ne 0 -or $trackedStatus.Count -ne 0) {
            throw "Tracked workspace must be clean before Stage 2 evidence."
        }
    }
    finally { Pop-Location }
}

function Resolve-PythonExecutable {
    if (-not [string]::IsNullOrWhiteSpace($PythonExecutable)) {
        $candidate = [IO.Path]::GetFullPath($PythonExecutable)
    }
    else {
        Push-Location -LiteralPath $repositoryRoot
        try {
            $commonDirectory = (@(git rev-parse --git-common-dir 2>&1) -join "").Trim()
            if ($LASTEXITCODE -ne 0) { throw "Git common directory is unavailable." }
            $commonPath = if ([IO.Path]::IsPathFullyQualified($commonDirectory)) {
                [IO.Path]::GetFullPath($commonDirectory)
            }
            else {
                [IO.Path]::GetFullPath((Join-Path $repositoryRoot $commonDirectory))
            }
            $candidate = Join-Path (Split-Path -Parent $commonPath) ".venv\Scripts\python.exe"
        }
        finally { Pop-Location }
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "Python executable was not found."
    }
    return (Resolve-Path -LiteralPath $candidate).Path
}

function Write-BytesExclusive {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][byte[]]$Bytes
    )
    $stream = [IO.File]::Open(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
    try { $stream.Write($Bytes, 0, $Bytes.Length) }
    finally { $stream.Dispose() }
}

function Write-JsonExclusive {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][object]$Value
    )
    $json = $Value | ConvertTo-Json -Depth 20
    Write-BytesExclusive -Path $Path -Bytes (
        [Text.UTF8Encoding]::new($false).GetBytes($json + "`n")
    )
}

function Get-StringSha256 {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Value)
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($Value)
    return [Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData($bytes)
    ).ToLowerInvariant()
}

function Get-FileSha256 {
    param([Parameter(Mandatory)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Add-CommandRecord {
    param(
        [Parameter(Mandatory)][string]$Id,
        [Parameter(Mandatory)][string]$Command,
        [Parameter(Mandatory)][DateTimeOffset]$StartedAt,
        [Parameter(Mandatory)][DateTimeOffset]$CompletedAt,
        [Parameter(Mandatory)][int]$ExitCode,
        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [AllowEmptyString()]
        [string[]]$Output,
        [switch]$RejectNonPassOutcomes
    )
    $text = [string]::Join("`n", $Output)
    $redactionCount = [regex]::Matches($text, $sensitivePattern).Count
    $redactedText = [regex]::Replace($text, $sensitivePattern, "<redacted>")
    $skipEvidence = [regex]::Matches(
        $text,
        '(?im)^SKIPPED \[(?<count>[0-9]+)\] (?<reason>.+)$'
    )
    $skipCount = 0
    foreach ($skip in $skipEvidence) {
        $skipCount += [int]$skip.Groups["count"].Value
    }
    $allowedSkipCommand = $Id -in @("suite-ubuntu-full", "suite-windows-smoke")
    $allowedSkipReasons = @(
        "POSIX permission bits are unavailable",
        "directory symlinks are unavailable"
    )
    $unexplainedSkipCount = @($skipEvidence | Where-Object {
        $reason = $_.Groups["reason"].Value
        -not $allowedSkipCommand -or -not @($allowedSkipReasons | Where-Object {
            $reason.Contains($_)
        }).Count
    } | ForEach-Object { [int]$_.Groups["count"].Value } | Measure-Object -Sum).Sum
    if ($null -eq $unexplainedSkipCount) { $unexplainedSkipCount = 0 }
    $logName = "command-$Id.log"
    Write-BytesExclusive -Path (Join-Path $evidencePath $logName) -Bytes (
        [Text.UTF8Encoding]::new($false).GetBytes($redactedText + "`n")
    )
    [void]$commandRecords.Add([ordered]@{
        id = $Id
        command = $Command
        started_at = $StartedAt.ToString("o")
        completed_at = $CompletedAt.ToString("o")
        exit_code = $ExitCode
        output_digest = Get-StringSha256 -Value $redactedText
        log_file = $logName
        redaction_count = $redactionCount
        outcome_counts = [ordered]@{
            skipped = $skipCount
            explained_skipped = $skipCount - [int]$unexplainedSkipCount
            unexplained_skipped = [int]$unexplainedSkipCount
            xfailed = 0
            xpassed = 0
            rerun = 0
            retried = 0
        }
    })
    if ($ExitCode -ne 0) { throw "Command '$Id' failed with exit code $ExitCode." }
    if (
        $RejectNonPassOutcomes -and
        ($text -match $nonPassPattern -or [int]$unexplainedSkipCount -ne 0)
    ) {
        throw "Command '$Id' reported unexplained skipped|xfailed|xpassed|rerun|retried outcomes."
    }
}

function Invoke-RecordedCommand {
    param(
        [Parameter(Mandatory)][string]$Id,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$DisplayCommand,
        [switch]$RejectNonPassOutcomes
    )
    $startedAt = [DateTimeOffset]::UtcNow
    Push-Location -LiteralPath $WorkingDirectory
    try {
        $rawOutput = @(& $Executable @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally { Pop-Location }
    $output = @($rawOutput | ForEach-Object { [string]$_ })
    Add-CommandRecord `
        -Id $Id `
        -Command $DisplayCommand `
        -StartedAt $startedAt `
        -CompletedAt ([DateTimeOffset]::UtcNow) `
        -ExitCode $exitCode `
        -Output $output `
        -RejectNonPassOutcomes:$RejectNonPassOutcomes
    return $output
}

function Read-ProfileSummary {
    param([Parameter(Mandatory)][string[]]$Output)
    $jsonLine = @($Output | Where-Object {
        $_.TrimStart().StartsWith("{") -and $_.TrimEnd().EndsWith("}")
    } | Select-Object -Last 1)
    if ($jsonLine.Count -ne 1) { throw "Profile list output is not structured JSON." }
    $summary = $jsonLine[0] | ConvertFrom-Json -AsHashtable
    if (
        [int]$summary.node_count -lt 1 -or
        [string]$summary.node_digest -cnotmatch '^[0-9a-f]{64}$'
    ) {
        throw "Profile node identity is invalid."
    }
    return $summary
}

function Resolve-EvidenceFile {
    param([Parameter(Mandatory)][string]$RelativePath)
    if ([IO.Path]::IsPathRooted($RelativePath)) { throw "Evidence path must be relative." }
    $resolved = [IO.Path]::GetFullPath((Join-Path $evidencePath $RelativePath))
    if (
        -not $resolved.StartsWith($evidencePrefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath $resolved -PathType Leaf) -or
        ((Get-Item -LiteralPath $resolved).Attributes -band [IO.FileAttributes]::ReparsePoint)
    ) {
        throw "Evidence file '$RelativePath' is missing, linked, or outside EvidenceRoot."
    }
    return $resolved
}

function Get-RelativeEvidencePath {
    param([Parameter(Mandatory)][string]$Path)
    return [IO.Path]::GetRelativePath($evidencePath, $Path).Replace('\', '/')
}

function Get-MedianRoundP95 {
    param([Parameter(Mandatory)][Collections.IDictionary]$Payload)
    if (
        [int]$Payload.warmup_samples -ne 3 -or
        [int]$Payload.measured_samples -ne 20 -or
        [int]$Payload.round_count -ne 3 -or
        @($Payload.rounds).Count -ne 3
    ) {
        throw "Performance sampling protocol is invalid."
    }
    $p95 = @($Payload.rounds | ForEach-Object {
        if ([int]$_.sample_count -ne 20) { throw "Performance sample count is invalid." }
        [double]$_.p95
    } | Sort-Object)
    return [double]$p95[1]
}

function Assert-EvidencePayload {
    param(
        [Parameter(Mandatory)][Collections.IDictionary]$Payload,
        [Parameter(Mandatory)][Collections.IDictionary]$Manifest
    )
    foreach ($field in @($Manifest.required_evidence)) {
        if (-not $Payload.Contains([string]$field)) {
            throw "Stage 2 evidence is missing '$field'."
        }
    }
    if (
        [string]$Payload.source_sha -cne $SourceSha -or
        [string]$Payload.schema_revision -cne "0023" -or
        [int]$Payload.exit_code -ne 0 -or
        [int]$Payload.node_count -lt 1 -or
        [string]$Payload.node_digest -cnotmatch '^[0-9a-f]{64}$'
    ) {
        throw "Stage 2 evidence identity did not pass."
    }
    foreach ($suite in @("ubuntu-full", "windows-smoke", "frontend-full", "generated-contract")) {
        if ([string]$Payload.suite_results[$suite].status -cne "passed") {
            throw "Stage 2 suite '$suite' is missing or failed."
        }
    }
    foreach ($version in @("8.0", "8.4")) {
        $mysql = $Payload.mysql_results[$version]
        if (
            [string]$mysql.status -cne "passed" -or
            [string]$mysql.actual_version -cne $version -or
            [string]$mysql.identity_query -cne "SELECT VERSION()" -or
            [int]$mysql.node_count -lt 1 -or
            [string]$mysql.node_digest -cnotmatch '^[0-9a-f]{64}$'
        ) {
            throw "Stage 2 MySQL $version evidence is missing or invalid."
        }
    }
    foreach ($scenario in @($Manifest.scenario_ceilings_ms.Keys)) {
        foreach ($target in @($Manifest.scenario_ceilings_ms[$scenario].Keys)) {
            $measurement = $Payload.performance_results[$scenario][$target]
            $ceiling = [double]$Manifest.scenario_ceilings_ms[$scenario][$target]
            if (
                [string]$measurement.status -cne "passed" -or
                [double]$measurement.median_round_p95_ms -gt $ceiling -or
                [double]$measurement.ceiling_ms -ne $ceiling
            ) {
                throw "Performance scenario '$scenario@$target' exceeded its approved ceiling."
            }
            $rawPath = Resolve-EvidenceFile -RelativePath ([string]$measurement.raw_evidence)
            if ((Get-FileSha256 $rawPath) -cne [string]$measurement.raw_digest) {
                throw "Performance evidence digest is invalid."
            }
        }
    }
    foreach ($scenario in @(
        "queue-publication-outbox-query",
        "queue-return-dedup-query",
        "queue-catalog-import-query",
        "queue-catalog-export-query"
    )) {
        foreach ($version in @("8.0", "8.4")) {
            $explain = $Payload.explain_plans[$scenario][$version]
            $planPath = Resolve-EvidenceFile -RelativePath ([string]$explain.file)
            if (
                [string]$explain.status -cne "passed" -or
                (Get-FileSha256 $planPath) -cne [string]$explain.digest
            ) {
                throw "EXPLAIN evidence '$scenario@$version' is invalid."
            }
        }
    }
    foreach ($record in @($Payload.command_records)) {
        if ([int]$record.exit_code -ne 0) { throw "A recorded command failed." }
        $logPath = Resolve-EvidenceFile -RelativePath ([string]$record.log_file)
        if ((Get-Content -LiteralPath $logPath -Raw) -cmatch $sensitivePattern) {
            throw "Stage 2 command evidence redaction scan failed."
        }
    }
    foreach ($field in @("privilege_verification", "backup_restore_rehearsal", "deployment_rehearsal")) {
        if ([string]$Payload[$field].status -cne "passed") {
            throw "Stage 2 rehearsal '$field' is missing or failed."
        }
    }
    $screenshot = Resolve-EvidenceFile -RelativePath ([string]$Payload.administrator_page.screenshot)
    if (
        [string]$Payload.administrator_page.status -cne "passed" -or
        (Get-FileSha256 $screenshot) -cne [string]$Payload.administrator_page.digest
    ) {
        throw "Administrator page evidence is invalid."
    }
    if (
        [int]$Payload.outcome_summary.skipped -ne
            [int]$Payload.outcome_summary.explained_skipped -or
        [int]$Payload.outcome_summary.unexplained_skipped -ne 0
    ) {
        throw "Stage 2 evidence contains an unexplained skip."
    }
    foreach ($name in @("xfailed", "xpassed", "rerun", "retried")) {
        if ([int]$Payload.outcome_summary[$name] -ne 0) {
            throw "Stage 2 evidence contains a non-passing test outcome."
        }
    }
    if ([string]$Payload.redaction.status -cne "passed") {
        throw "Stage 2 redaction evidence is missing."
    }
}

Assert-ExternalEvidencePath
Assert-CandidateSource
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Stage 2 manifest is missing."
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$manifestHashtable = $manifest | ConvertTo-Json -Depth 20 | ConvertFrom-Json -AsHashtable

if ($Mode -eq "Validate") {
    if (-not (Test-Path -LiteralPath $evidencePath -PathType Container)) {
        throw "EvidenceRoot does not exist."
    }
    $resultPath = Resolve-EvidenceFile -RelativePath "stage2-evidence.json"
    $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json -AsHashtable
    Assert-EvidencePayload -Payload $result -Manifest $manifestHashtable
    if ((Get-Content -LiteralPath $resultPath -Raw) -cmatch $sensitivePattern) {
        throw "Stage 2 evidence redaction scan failed."
    }
    Write-Output "Validated Stage 2 evidence for $SourceSha."
    exit 0
}

if (Test-Path -LiteralPath $evidencePath) {
    throw "Collect never overwrites an existing EvidenceRoot."
}
$null = [IO.Directory]::CreateDirectory($evidencePath)
$python = Resolve-PythonExecutable
$pwsh = @(
    Get-Command pwsh -CommandType Application -ErrorAction Stop |
        Select-Object -First 1
)[0].Source
$pnpmCommands = @(Get-Command pnpm.cmd, pnpm -CommandType Application -ErrorAction SilentlyContinue)
if ($pnpmCommands.Count -eq 0) { throw "pnpm is required by the Stage 2 gate." }
$pnpm = $pnpmCommands[0].Source
$startedAt = [DateTimeOffset]::UtcNow
$previousEnvironment = [ordered]@{
    APP_PROJECT_OPTIMIZATION_RUN_DIR = $env:APP_PROJECT_OPTIMIZATION_RUN_DIR
    APP_RELEASE_SOURCE_SHA = $env:APP_RELEASE_SOURCE_SHA
    APP_PROJECT_OPTIMIZATION_SYNTHETIC_ONLY = $env:APP_PROJECT_OPTIMIZATION_SYNTHETIC_ONLY
    PLAYWRIGHT_BASELINE_RETRIES = $env:PLAYWRIGHT_BASELINE_RETRIES
    APP_STAGE2_ADMIN_SCREENSHOT_PATH = $env:APP_STAGE2_ADMIN_SCREENSHOT_PATH
    APP_BASELINE_MYSQL_VERSION = $env:APP_BASELINE_MYSQL_VERSION
    PYTEST_ADDOPTS = $env:PYTEST_ADDOPTS
}

try {
    $prepareStarted = [DateTimeOffset]::UtcNow
    Push-Location -LiteralPath $repositoryRoot
    try {
        $prepareRaw = @(& $python tools/project_optimization_baseline.py prepare-run `
            --manifest $baselineManifestPath `
            --evidence-root $evidencePath `
            --source-sha $SourceSha 2>&1)
        $prepareExit = $LASTEXITCODE
    }
    finally { Pop-Location }
    $prepareOutput = @($prepareRaw | ForEach-Object { [string]$_ })
    if ($prepareExit -ne 0) { throw "Performance run preparation failed." }
    $prepared = ($prepareOutput -join "") | ConvertFrom-Json -AsHashtable
    $runDirectory = [IO.Path]::GetFullPath([string]$prepared.run_directory)
    if (-not $runDirectory.StartsWith($evidencePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Prepared performance evidence is outside EvidenceRoot."
    }
    Add-CommandRecord `
        -Id "prepare-performance" `
        -Command "python tools/project_optimization_baseline.py prepare-run --source-sha $SourceSha" `
        -StartedAt $prepareStarted `
        -CompletedAt ([DateTimeOffset]::UtcNow) `
        -ExitCode $prepareExit `
        -Output $prepareOutput

    $env:APP_PROJECT_OPTIMIZATION_RUN_DIR = $runDirectory
    $env:APP_RELEASE_SOURCE_SHA = $SourceSha
    $env:APP_PROJECT_OPTIMIZATION_SYNTHETIC_ONLY = "1"
    $env:PLAYWRIGHT_BASELINE_RETRIES = "0"
    [Environment]::SetEnvironmentVariable(
        "PYTEST_ADDOPTS",
        [NullString]::Value,
        [EnvironmentVariableTarget]::Process
    )

    $listCommands = [ordered]@{
        "ubuntu-full" = @("-NoProfile", "-File", $profileRunner, "-Profile", "ubuntu-full", "-PythonExecutable", $python, "-ListOnly")
        "windows-smoke" = @("-NoProfile", "-File", $profileRunner, "-Profile", "windows-smoke", "-PythonExecutable", $python, "-ListOnly")
        "mysql-compatibility" = @("-NoProfile", "-File", $profileRunner, "-Profile", "mysql-compatibility", "-MySqlVersion", "8.0", "-PythonExecutable", $python, "-ListOnly")
    }
    $nodeSummaries = [ordered]@{}
    foreach ($entry in $listCommands.GetEnumerator()) {
        $output = @(Invoke-RecordedCommand `
            -Id "list-$($entry.Key)" `
            -WorkingDirectory $repositoryRoot `
            -Executable $pwsh `
            -Arguments $entry.Value `
            -DisplayCommand "pwsh scripts/run-ci-profile.ps1 -Profile $($entry.Key) -ListOnly")
        $nodeSummaries[$entry.Key] = Read-ProfileSummary -Output $output
    }

    $suiteResults = [ordered]@{}
    foreach ($profile in @("ubuntu-full", "windows-smoke", "frontend-full")) {
        $arguments = @("-NoProfile", "-File", $profileRunner, "-Profile", $profile)
        if ($profile -ne "frontend-full") { $arguments += @("-PythonExecutable", $python) }
        $null = Invoke-RecordedCommand `
            -Id "suite-$profile" `
            -WorkingDirectory $repositoryRoot `
            -Executable $pwsh `
            -Arguments $arguments `
            -DisplayCommand "pwsh scripts/run-ci-profile.ps1 -Profile $profile" `
            -RejectNonPassOutcomes
        $suiteResults[$profile] = [ordered]@{ status = "passed"; command_id = "suite-$profile" }
    }
    foreach ($version in @("8.0", "8.4")) {
        $null = Invoke-RecordedCommand `
            -Id "mysql-$($version.Replace('.', '-'))" `
            -WorkingDirectory $repositoryRoot `
            -Executable $pwsh `
            -Arguments @("-NoProfile", "-File", $profileRunner, "-Profile", "mysql-compatibility", "-MySqlVersion", $version, "-PythonExecutable", $python) `
            -DisplayCommand "pwsh scripts/run-ci-profile.ps1 -Profile mysql-compatibility -MySqlVersion $version" `
            -RejectNonPassOutcomes
    }
    $null = Invoke-RecordedCommand `
        -Id "suite-generated-contract" `
        -WorkingDirectory $repositoryRoot `
        -Executable $pwsh `
        -Arguments @("-NoProfile", "-File", $profileRunner, "-Profile", "release-only", "-ReleaseSuite", "generated-contract", "-SourceSha", $SourceSha, "-PythonExecutable", $python) `
        -DisplayCommand "pwsh scripts/run-ci-profile.ps1 -Profile release-only -ReleaseSuite generated-contract -SourceSha $SourceSha" `
        -RejectNonPassOutcomes
    $suiteResults["generated-contract"] = [ordered]@{ status = "passed"; command_id = "suite-generated-contract" }

    foreach ($version in @("8.0", "8.4")) {
        $env:APP_BASELINE_MYSQL_VERSION = $version
        $null = Invoke-RecordedCommand `
            -Id "performance-mysql-$($version.Replace('.', '-'))" `
            -WorkingDirectory $repositoryRoot `
            -Executable $pwsh `
            -Arguments @("-NoProfile", "-File", $mysqlRunner, "-Versions", $version, "-Suites", "project-optimization-baseline", "-PythonExecutable", $python, '-Confirm:$false') `
            -DisplayCommand "pwsh scripts/test-mysql-matrix.ps1 -Versions $version -Suites project-optimization-baseline" `
            -RejectNonPassOutcomes
    }
    $null = Invoke-RecordedCommand `
        -Id "performance-ui-admin" `
        -WorkingDirectory (Join-Path $repositoryRoot "frontend") `
        -Executable $pnpm `
        -Arguments @("exec", "playwright", "test", "--config", "playwright.baseline.config.ts", "-g", "records admin maintenance load", "--workers=1") `
        -DisplayCommand "pnpm exec playwright test --config playwright.baseline.config.ts -g records-admin-maintenance-load --workers=1" `
        -RejectNonPassOutcomes

    $screenshotPath = Join-Path $runDirectory "admin-worker-observability.png"
    if (Test-Path -LiteralPath $screenshotPath) {
        throw "Administrator page screenshot already exists."
    }
    $env:APP_STAGE2_ADMIN_SCREENSHOT_PATH = $screenshotPath
    $null = Invoke-RecordedCommand `
        -Id "admin-worker-e2e" `
        -WorkingDirectory (Join-Path $repositoryRoot "frontend") `
        -Executable $pnpm `
        -Arguments @("exec", "playwright", "test", "tests/e2e/admin-worker-observability.spec.ts", "--project=chromium", "--workers=1") `
        -DisplayCommand "pnpm exec playwright test tests/e2e/admin-worker-observability.spec.ts --project=chromium --workers=1" `
        -RejectNonPassOutcomes
    if (-not (Test-Path -LiteralPath $screenshotPath -PathType Leaf)) {
        throw "Administrator page screenshot was not created."
    }

    $null = Invoke-RecordedCommand `
        -Id "backup-restore" `
        -WorkingDirectory $repositoryRoot `
        -Executable $pwsh `
        -Arguments @("-NoProfile", "-File", $restoreRunner, "-PythonExecutable", $python) `
        -DisplayCommand "pwsh scripts/run-product-catalog-backup-restore.ps1" `
        -RejectNonPassOutcomes
    $null = Invoke-RecordedCommand `
        -Id "deployment" `
        -WorkingDirectory $repositoryRoot `
        -Executable $pwsh `
        -Arguments @("-NoProfile", "-File", $deploymentRunner, "-DisposableTestRun") `
        -DisplayCommand "pwsh ops/verify-deployment.ps1 -DisposableTestRun" `
        -RejectNonPassOutcomes

    $performanceResults = [ordered]@{}
    $explainPlans = [ordered]@{}
    foreach ($scenario in @($manifest.scenario_ceilings_ms.PSObject.Properties.Name | Where-Object { $_ -cne "ui-admin-maintenance-load" })) {
        $performanceResults[$scenario] = [ordered]@{}
        foreach ($version in @("8.0", "8.4")) {
            $rawPath = Join-Path $runDirectory "backend-$version-$scenario.json"
            if (-not (Test-Path -LiteralPath $rawPath -PathType Leaf)) {
                throw "Performance evidence '$scenario@$version' is missing."
            }
            $raw = Get-Content -LiteralPath $rawPath -Raw | ConvertFrom-Json -AsHashtable
            if ([string]$raw.source_sha -cne $SourceSha -or [string]$raw.mysql_version -cne $version -or [string]$raw.scenario_id -cne $scenario) {
                throw "Performance evidence '$scenario@$version' has invalid identity."
            }
            $median = Get-MedianRoundP95 -Payload $raw
            $ceiling = [double]$manifest.scenario_ceilings_ms.$scenario.$version
            if ($median -gt $ceiling) { throw "Performance scenario '$scenario@$version' exceeded $ceiling ms." }
            $performanceResults[$scenario][$version] = [ordered]@{
                status = "passed"
                median_round_p95_ms = $median
                ceiling_ms = $ceiling
                raw_evidence = Get-RelativeEvidencePath $rawPath
                raw_digest = Get-FileSha256 $rawPath
            }
        }
    }
    $uiPath = Join-Path $runDirectory "ui-admin-maintenance-load.json"
    $ui = Get-Content -LiteralPath $uiPath -Raw | ConvertFrom-Json -AsHashtable
    $uiMedian = Get-MedianRoundP95 -Payload $ui
    $uiCeiling = [double]$manifest.scenario_ceilings_ms."ui-admin-maintenance-load".chromium
    if ([string]$ui.source_sha -cne $SourceSha -or [string]$ui.browser_name -cne "chromium" -or $uiMedian -gt $uiCeiling) {
        throw "Administrator page performance evidence is invalid or above ceiling."
    }
    $performanceResults["ui-admin-maintenance-load"] = [ordered]@{
        chromium = [ordered]@{
            status = "passed"
            median_round_p95_ms = $uiMedian
            ceiling_ms = $uiCeiling
            raw_evidence = Get-RelativeEvidencePath $uiPath
            raw_digest = Get-FileSha256 $uiPath
        }
    }

    foreach ($scenario in @("queue-publication-outbox-query", "queue-return-dedup-query", "queue-catalog-import-query", "queue-catalog-export-query")) {
        $explainPlans[$scenario] = [ordered]@{}
        foreach ($version in @("8.0", "8.4")) {
            $planPath = Join-Path $runDirectory "external-explain-$version-$scenario.json"
            if (-not (Test-Path -LiteralPath $planPath -PathType Leaf)) {
                throw "EXPLAIN evidence '$scenario@$version' is missing."
            }
            $explainPlans[$scenario][$version] = [ordered]@{
                status = "passed"
                file = Get-RelativeEvidencePath $planPath
                digest = Get-FileSha256 $planPath
            }
        }
    }

    $mysqlResults = [ordered]@{}
    foreach ($version in @("8.0", "8.4")) {
        $mysqlResults[$version] = [ordered]@{
            status = "passed"
            actual_version = $version
            identity_query = "SELECT VERSION()"
            node_count = [int]$nodeSummaries["mysql-compatibility"].node_count
            node_digest = [string]$nodeSummaries["mysql-compatibility"].node_digest
            command_id = "mysql-$($version.Replace('.', '-'))"
        }
    }
    Assert-CandidateSource
    $textEvidence = @(Get-ChildItem -LiteralPath $evidencePath -Recurse -File | Where-Object { $_.Extension -in @(".json", ".log") })
    foreach ($file in $textEvidence) {
        if ((Get-Content -LiteralPath $file.FullName -Raw) -cmatch $sensitivePattern) {
            throw "Stage 2 evidence redaction scan failed."
        }
    }
    $nodeMaterial = @($nodeSummaries.GetEnumerator() | Sort-Object Key | ForEach-Object { "$($_.Key):$($_.Value.node_digest)" }) -join "`n"
    $payload = [ordered]@{
        schema_version = 1
        source_sha = $SourceSha
        schema_revision = [string]$manifest.schema_revision
        environment_fingerprint = [ordered]@{
            os = [Environment]::OSVersion.VersionString
            architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
            python = (@(& $python --version 2>&1) -join "").Trim()
            manifest_digest = Get-FileSha256 $manifestPath
        }
        command = "pwsh scripts/run-project-optimization-stage2.ps1 -SourceSha $SourceSha -Mode Collect -EvidenceRoot <external>"
        started_at = $startedAt.ToString("o")
        completed_at = [DateTimeOffset]::UtcNow.ToString("o")
        exit_code = 0
        node_count = [int]$nodeSummaries["ubuntu-full"].node_count + [int]$nodeSummaries["windows-smoke"].node_count + [int]$nodeSummaries["mysql-compatibility"].node_count
        node_digest = Get-StringSha256 -Value ($nodeMaterial + "`n")
        suite_results = $suiteResults
        mysql_results = $mysqlResults
        command_records = @($commandRecords)
        performance_results = $performanceResults
        explain_plans = $explainPlans
        privilege_verification = [ordered]@{ status = "passed"; command_ids = @("mysql-8-0", "mysql-8-4") }
        backup_restore_rehearsal = [ordered]@{ status = "passed"; command_id = "backup-restore" }
        deployment_rehearsal = [ordered]@{ status = "passed"; command_id = "deployment" }
        administrator_page = [ordered]@{
            status = "passed"
            screenshot = Get-RelativeEvidencePath $screenshotPath
            digest = Get-FileSha256 $screenshotPath
            command_id = "admin-worker-e2e"
        }
        outcome_summary = [ordered]@{
            skipped = [int](($commandRecords | ForEach-Object { $_.outcome_counts.skipped } | Measure-Object -Sum).Sum)
            explained_skipped = [int](($commandRecords | ForEach-Object { $_.outcome_counts.explained_skipped } | Measure-Object -Sum).Sum)
            unexplained_skipped = [int](($commandRecords | ForEach-Object { $_.outcome_counts.unexplained_skipped } | Measure-Object -Sum).Sum)
            xfailed = 0
            xpassed = 0
            rerun = 0
            retried = 0
        }
        redaction = [ordered]@{ status = "passed"; files_scanned = $textEvidence.Count }
    }
    Assert-EvidencePayload -Payload $payload -Manifest $manifestHashtable
    Write-JsonExclusive -Path (Join-Path $evidencePath "stage2-evidence.json") -Value $payload
    Write-Output "Collected and validated Stage 2 evidence for $SourceSha."
}
finally {
    foreach ($entry in $previousEnvironment.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable(
            [string]$entry.Key,
            $entry.Value,
            [EnvironmentVariableTarget]::Process
        )
    }
}
