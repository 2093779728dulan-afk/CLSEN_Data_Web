#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern("\A[0-9a-f]{40}\z")]
    [string]$SourceSha,

    [Parameter(Mandatory)]
    [string]$PythonExecutable,

    [Parameter(Mandatory)]
    [string]$EvidenceRoot,

    [Parameter()]
    [ValidateSet("Validate", "Collect", "Freeze")]
    [string]$Mode = "Validate",

    [Parameter()]
    [string]$ApprovedBy,

    [Parameter()]
    [string]$ApprovalReference,

    [Parameter()]
    [ValidateRange(1, 300)]
    [int]$HeartbeatSeconds = 10,

    [Parameter()]
    [ValidateRange(1, 900)]
    [int]$StaleSeconds = 30,

    [Parameter()]
    [ValidateRange(1, 1800)]
    [int]$OfflineSeconds = 60,

    [Parameter()]
    [ValidateRange(1, 300)]
    [int]$RefreshSeconds = 15,

    [Parameter()]
    [string]$BudgetOverridesPath,

    [Parameter()]
    [switch]$AcceptProposedBudgets,

    [Parameter()]
    [string]$ApprovedRunId,

    [Parameter()]
    [ValidatePattern("\A[0-9a-f]{64}\z")]
    [string]$ApprovedToken,

    [Parameter()]
    [switch]$CompleteFreeze
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$manifest = Join-Path $PSScriptRoot "project-optimization-baseline-manifest.json"
$approvalOutput = Join-Path `
    $repositoryRoot `
    "docs/operations/project-optimization-baseline-approval-v1.json"
$runDirectory = $null
$commandStagingDirectory = $null
$commandSequence = 0
$platformId = if ($IsWindows) { "win32" } elseif ($IsMacOS) { "darwin" } else { "linux" }
$privateCanaryEnvironmentNames = @(
    "APP_PRODUCT_CATALOG_CANARY_DATABASE_URL",
    "APP_PRODUCT_CATALOG_PRIVATE_MANIFEST",
    "APP_PRODUCT_CATALOG_PRIVATE_CORPUS_ROOT",
    "APP_REQUIRE_PRODUCT_CATALOG_CANARY",
    "APP_PRODUCT_CATALOG_CANARY_EVIDENCE_PATH"
)
$stage0PytestOutcomeEnvironmentNames = @(
    "APP_STAGE0_PYTEST_OUTCOME_DIRECTORY",
    "APP_STAGE0_PYTEST_OUTCOME_BINDING",
    "APP_STAGE0_PYTEST_OUTCOME_COMMAND_ID",
    "APP_STAGE0_PYTEST_OUTCOME_SHARD",
    "APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST",
    "APP_STAGE0_PYTEST_OUTCOME_SHARD_DIGESTS"
)
$managedEnvironmentNames = @(
    "APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT",
    "APP_PROJECT_OPTIMIZATION_RUN_DIR",
    "APP_RELEASE_SOURCE_SHA",
    "APP_BASELINE_MYSQL_VERSION",
    "APP_PROJECT_OPTIMIZATION_SYNTHETIC_ONLY",
    "PLAYWRIGHT_BASELINE_RETRIES",
    "PYTEST_ADDOPTS"
) + $stage0PytestOutcomeEnvironmentNames + $privateCanaryEnvironmentNames

function Get-ManagedEnvironmentSnapshot {
    param([Parameter(Mandatory)][string[]]$Names)
    $snapshot = @{}
    foreach ($name in $Names) {
        $snapshot[$name] = [Environment]::GetEnvironmentVariable(
            $name,
            [EnvironmentVariableTarget]::Process
        )
    }
    return $snapshot
}

function Clear-PrivateCanaryEnvironment {
    foreach ($name in $privateCanaryEnvironmentNames) {
        [Environment]::SetEnvironmentVariable(
            $name,
            [NullString]::Value,
            [EnvironmentVariableTarget]::Process
        )
    }
}

function Clear-Stage0PytestOutcomeEnvironment {
    foreach ($name in $stage0PytestOutcomeEnvironmentNames) {
        [Environment]::SetEnvironmentVariable(
            $name,
            [NullString]::Value,
            [EnvironmentVariableTarget]::Process
        )
    }
}

function Restore-ManagedEnvironment {
    param([Parameter(Mandatory)][Collections.IDictionary]$Snapshot)
    foreach ($name in $Snapshot.Keys) {
        $value = if ($null -eq $Snapshot[$name]) {
            [NullString]::Value
        }
        else {
            $Snapshot[$name]
        }
        [Environment]::SetEnvironmentVariable(
            [string]$name,
            $value,
            [EnvironmentVariableTarget]::Process
        )
    }
}

$previousEnvironment = Get-ManagedEnvironmentSnapshot -Names $managedEnvironmentNames

function Resolve-RequiredFile {
    param(
        [Parameter(Mandatory)][AllowNull()][AllowEmptyString()][string]$Value,
        [Parameter(Mandatory)][string]$Label,
        [switch]$RequireAbsolute
    )
    if (
        [string]::IsNullOrWhiteSpace($Value) -or
        ($RequireAbsolute -and -not [IO.Path]::IsPathFullyQualified($Value)) -or
        -not (Test-Path -LiteralPath $Value -PathType Leaf)
    ) {
        throw "$Label is unavailable."
    }
    return (Resolve-Path -LiteralPath $Value).Path
}

function Resolve-RequiredApplication {
    param([Parameter(Mandatory)][string[]]$Names)
    foreach ($name in $Names) {
        $application = Get-Command `
            -Name $name `
            -CommandType Application `
            -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $application) {
            return $application.Source
        }
    }
    throw "A required release tool is unavailable."
}

function Test-IsRepositoryPath {
    param([Parameter(Mandatory)][string]$Path)
    $resolved = [IO.Path]::GetFullPath($Path)
    $prefix = $repositoryRoot.TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    ) + [IO.Path]::DirectorySeparatorChar
    return (
        $resolved.Equals($repositoryRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
    )
}

function Resolve-ExternalEvidenceRoot {
    param(
        [Parameter(Mandatory)][string]$Value,
        [switch]$RequireEmpty
    )
    if (
        [string]::IsNullOrWhiteSpace($Value) -or
        -not [IO.Path]::IsPathFullyQualified($Value) -or
        -not (Test-Path -LiteralPath $Value -PathType Container)
    ) {
        throw "EvidenceRoot must be an existing external directory."
    }
    $resolved = (Resolve-Path -LiteralPath $Value).Path
    $item = Get-Item -LiteralPath $resolved -Force
    if (
        (Test-IsRepositoryPath -Path $resolved) -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "EvidenceRoot must be a real directory outside the repository."
    }
    if ($RequireEmpty -and @(Get-ChildItem -LiteralPath $resolved -Force).Count -ne 0) {
        throw "EvidenceRoot must be empty."
    }
    return [IO.Path]::GetFullPath($resolved)
}

function Assert-CleanSource {
    Push-Location -LiteralPath $repositoryRoot
    try {
        $actualSha = (@(git rev-parse HEAD 2>&1) -join "").Trim()
        if ($LASTEXITCODE -ne 0 -or $actualSha -cne $SourceSha) {
            throw "HEAD does not match SourceSha."
        }
        $dirty = @(
            git status --porcelain --untracked-files=all 2>&1 |
                ForEach-Object { [string]$_ } |
                Where-Object { $_ -notmatch '^\?\? data/' }
        )
        if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) {
            throw (
                "Baseline collection requires a clean candidate SHA outside " +
                "the user-owned data directory."
            )
        }
    }
    finally {
        Pop-Location
    }
}

function Get-Sha256Text {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Value)
    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    return [Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData($bytes)
    ).ToLowerInvariant()
}

function Get-Sha256Bytes {
    param([Parameter(Mandatory)][AllowNull()][AllowEmptyCollection()][byte[]]$Value)
    if ($null -eq $Value) {
        $Value = [byte[]]::new(0)
    }
    return [Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData($Value)
    ).ToLowerInvariant()
}

function Protect-Output {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Value)
    $safe = $Value -replace (
        '(?i)\b(?:mysql(?:\+[a-z0-9]+)?|https?)://\S+'
    ), '[redacted-url]'
    $safe = $safe -replace (
        '(?i)(--(?:password|secret|token|api[-_]?key|access[-_]?key|' +
        'client[-_]?secret|private[-_]?key|credential)(?:=|\s+))' +
        '(?:"[^"]*"|''[^'']*''|[^\s,;]+)'
    ), '$1[redacted]'
    $safe = $safe -replace (
        '(?i)(Authorization\s*:\s*Bearer\s+)[^\s,;]+'
    ), '$1[redacted]'
    $safe = $safe -replace (
        '(?i)(X-API-Key\s*:\s*)[^\s,;]+'
    ), '$1[redacted]'
    $safe = $safe -replace (
        '(?i)(["'']?(?:password|secret|token|api[-_]?key|access[-_]?key|' +
        'client[-_]?secret|private[-_]?key|credential)["'']?\s*[:=]\s*)' +
        '(?:"[^"]*"|''[^'']*''|[^\s,;]+)'
    ), '$1[redacted]'
    foreach ($entry in [Environment]::GetEnvironmentVariables(
            [EnvironmentVariableTarget]::Process
        ).GetEnumerator()) {
        if (
            ([string]$entry.Key) -match (
                '(?i)(password|secret|token|api_?key|access_?key|' +
                'client_?secret|private_?key|credential|database_url)\z'
            ) -and
            -not [string]::IsNullOrWhiteSpace([string]$entry.Value) -and
            ([string]$entry.Value).Length -ge 4
        ) {
            $safe = $safe -replace [regex]::Escape([string]$entry.Value), '[redacted-env]'
        }
    }
    return $safe
}

function Write-TimingLine {
    param(
        [Parameter(Mandatory)][string]$Phase,
        [Parameter(Mandatory)][string]$Status,
        [Parameter(Mandatory)][AllowEmptyString()][string]$Description,
        [AllowNull()][double]$ElapsedSeconds = $null
    )
    $elapsed = if ($null -eq $ElapsedSeconds) { "unavailable" } else {
        $ElapsedSeconds.ToString("F3", [Globalization.CultureInfo]::InvariantCulture)
    }
    Write-Host ("TIMING phase={0} status={1} elapsed_seconds={2} description={3}" -f
        $Phase, $Status, $elapsed, (Protect-Output -Value $Description))
}

function Write-PreflightFailureLog {
    param(
        [Parameter(Mandatory)][string]$EvidenceRoot,
        [Parameter(Mandatory)][string]$Stage,
        [Parameter(Mandatory)][string]$Message,
        [AllowEmptyCollection()][string[]]$Output = @()
    )
    $logPath = Join-Path $EvidenceRoot "preflight-failure.log"
    $lines = [Collections.Generic.List[string]]::new()
    $lines.Add("stage=$Stage")
    $lines.Add("utc=$([DateTimeOffset]::UtcNow.ToString('o'))")
    $lines.Add("message=$(Protect-Output -Value $Message)")
    foreach ($line in $Output) {
        $safe = Protect-Output -Value ([string]$line)
        if (-not [string]::IsNullOrWhiteSpace($safe)) {
            $lines.Add($safe)
        }
    }
    try {
        [IO.File]::WriteAllLines(
            $logPath,
            $lines,
            [Text.UTF8Encoding]::new($false)
        )
    }
    catch {
        throw "Preflight failed at $Stage; the failure log could not be written safely."
    }
    return $logPath
}

function Get-PlaywrightPort {
    $raw = [Environment]::GetEnvironmentVariable(
        "PLAYWRIGHT_PORT",
        [EnvironmentVariableTarget]::Process
    )
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return 5173
    }
    $port = 0
    if (
        -not [int]::TryParse($raw, [Globalization.NumberStyles]::Integer,
            [Globalization.CultureInfo]::InvariantCulture, [ref]$port) -or
        $port -lt 1 -or $port -gt 65535
    ) {
        throw "PLAYWRIGHT_PORT must be an integer from 1 through 65535."
    }
    return $port
}

function Get-PreflightViteProcessIds {
    param([Parameter(Mandatory)][int]$Port)
    if (-not $IsWindows) { return @() }
    $pattern = "vite.*--port[`"']?\s*[`"']?$([regex]::Escape([string]$Port))\b"
    try {
        return @(
            Get-CimInstance Win32_Process -ErrorAction Stop |
                Where-Object {
                    $_.Name -ieq "node.exe" -and
                    [string]$_.CommandLine -match $pattern
                } |
                ForEach-Object { [int]$_.ProcessId }
        )
    }
    catch {
        return @()
    }
}

function Invoke-PlaywrightServicePreflight {
    param(
        [Parameter(Mandatory)][string]$Pnpm,
        [Parameter(Mandatory)][string]$EvidenceRoot
    )
    try {
        $port = Get-PlaywrightPort
    }
    catch {
        $log = Write-PreflightFailureLog `
            -EvidenceRoot $EvidenceRoot `
            -Stage "playwright-port-config" `
            -Message $_.Exception.Message
        throw "Stage 0 UI preflight failed; see脱敏日志 '$log'."
    }
    $frontendDirectory = Join-Path $repositoryRoot "frontend"
    $configPath = Join-Path $frontendDirectory "playwright.baseline.config.ts"
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        $log = Write-PreflightFailureLog `
            -EvidenceRoot $EvidenceRoot `
            -Stage "playwright-config" `
            -Message "The baseline Playwright config is unavailable." `
            -Output @($configPath)
        throw "Stage 0 UI preflight failed; see脱敏日志 '$log'."
    }
    $configText = Get-Content -Raw -LiteralPath $configPath
    if (
        $configText -notmatch 'PLAYWRIGHT_PORT' -or
        $configText -notmatch 'pnpm dev --host 127\.0\.0\.1 --port' -or
        $configText -notmatch 'strictPort'
    ) {
        $log = Write-PreflightFailureLog `
            -EvidenceRoot $EvidenceRoot `
            -Stage "playwright-config" `
            -Message "The baseline Playwright config does not preserve the required host, port, and strictPort contract." `
            -Output @($configPath)
        throw "Stage 0 UI preflight failed; see脱敏日志 '$log'."
    }

    $listener = [Net.Sockets.TcpListener]::new(
        [Net.IPAddress]::Loopback,
        $port
    )
    try {
        try {
            $listener.Start()
        }
        catch {
            $log = Write-PreflightFailureLog `
                -EvidenceRoot $EvidenceRoot `
                -Stage "playwright-port-bind" `
                -Message ("Port {0} cannot be bound by this process." -f $port) `
                -Output @($_.Exception.Message)
            throw "Stage 0 UI preflight failed; see脱敏日志 '$log'."
        }
    }
    finally {
        $listener.Stop()
    }

    $preflightDirectory = Join-Path (
        [IO.Path]::GetTempPath()
    ) ("project-optimization-preflight-" + [guid]::NewGuid().ToString("N"))
    $stdoutPath = Join-Path $preflightDirectory "stdout"
    $stderrPath = Join-Path $preflightDirectory "stderr"
    $process = $null
    $stdoutTask = $null
    $stderrTask = $null
    $existingViteProcessIds = @(Get-PreflightViteProcessIds -Port $port)
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $ready = $false
    $failureMessage = $null
    $failureOutput = [Collections.Generic.List[string]]::new()
    try {
        $null = New-Item -ItemType Directory -Path $preflightDirectory -ErrorAction Stop
        $startInfo = [Diagnostics.ProcessStartInfo]::new()
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.WorkingDirectory = $frontendDirectory
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $startInfo.FileName = $Pnpm
        foreach ($argument in @(
                "dev", "--host", "127.0.0.1", "--port", [string]$port,
                "--strictPort"
            )) {
            $startInfo.ArgumentList.Add($argument)
        }
        $startInfo.Environment["VITE_PRODUCT_ANALYTICS_SOURCE"] = "p0_catalog"
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $startInfo
        $started = $process.Start()
        if (-not $started) {
            throw "The baseline UI server process did not start."
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        for ($attempt = 1; $attempt -le 30; $attempt++) {
            if ($process.HasExited) {
                $failureMessage = "The baseline UI server exited before readiness."
                break
            }
            try {
                $response = Invoke-WebRequest `
                    -UseBasicParsing `
                    -Uri ("http://127.0.0.1:{0}/" -f $port) `
                    -TimeoutSec 2
                if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                    $ready = $true
                    break
                }
            }
            catch {
                # Readiness is retried only while the process we started is alive.
            }
            Start-Sleep -Seconds 1
        }
        if (-not $ready -and [string]::IsNullOrWhiteSpace($failureMessage)) {
            $failureMessage = "The baseline UI server did not become HTTP-ready within 30 seconds."
        }
        if (-not $ready) {
            if ($null -ne $stdoutTask -and $stdoutTask.IsCompleted) {
                $failureOutput.Add($stdoutTask.GetAwaiter().GetResult())
            }
            if ($null -ne $stderrTask -and $stderrTask.IsCompleted) {
                $failureOutput.Add($stderrTask.GetAwaiter().GetResult())
            }
            $log = Write-PreflightFailureLog `
                -EvidenceRoot $EvidenceRoot `
                -Stage "playwright-service" `
                -Message $failureMessage `
                -Output @($failureOutput)
            throw "Stage 0 UI preflight failed; see脱敏日志 '$log'."
        }
        Write-TimingLine -Phase "service-preflight" -Status "passed" `
            -ElapsedSeconds $clock.Elapsed.TotalSeconds `
            -Description ("Vite readiness on 127.0.0.1:{0}" -f $port)
    }
    catch {
        if ($_.Exception.Message -notlike "Stage 0 UI preflight failed;*") {
            $failureMessage = $_.Exception.Message
            $log = Write-PreflightFailureLog `
                -EvidenceRoot $EvidenceRoot `
                -Stage "playwright-service" `
                -Message $failureMessage `
                -Output @($failureOutput)
            throw "Stage 0 UI preflight failed; see脱敏日志 '$log'."
        }
        throw
    }
    finally {
        $clock.Stop()
        if ($null -ne $process) {
            try {
                if (-not $process.HasExited) {
                    $process.Kill($true)
                    $null = $process.WaitForExit(5000)
                }
            }
            catch {
                # Do not touch processes we did not start; preserve the primary failure.
            }
        }
        foreach ($task in @($stdoutTask, $stderrTask)) {
            if ($null -ne $task -and -not $task.IsCompleted) {
                try { $task.Wait(500) | Out-Null } catch { }
            }
        }
        if ($null -ne $process) { $process.Dispose() }
        foreach ($attempt in 1..5) {
            $orphaned = @(
                Get-PreflightViteProcessIds -Port $port |
                    Where-Object { $existingViteProcessIds -notcontains $_ }
            )
            if ($orphaned.Count -eq 0) { break }
            foreach ($processId in $orphaned) {
                try { Stop-Process -Id $processId -Force -ErrorAction Stop } catch { }
            }
            Start-Sleep -Milliseconds 100
        }
        if (Test-Path -LiteralPath $preflightDirectory -PathType Container) {
            Remove-Item -LiteralPath $preflightDirectory -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Write-ExclusiveJson {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][Collections.IDictionary]$Payload
    )
    $json = $Payload | ConvertTo-Json -Depth 10 -Compress
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json + "`n")
    $stream = [IO.FileStream]::new(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally {
        $stream.Dispose()
    }
}

function Publish-CommandResults {
    if (
        [string]::IsNullOrWhiteSpace($commandStagingDirectory) -or
        -not (Test-Path -LiteralPath $commandStagingDirectory -PathType Container)
    ) {
        throw "Command result staging is unavailable."
    }
    $output = @(
        & $PythonExecutable `
            tools/project_optimization_baseline.py `
            publish-command-results `
            --staging-dir $commandStagingDirectory `
            --run-dir $runDirectory 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Exact command result publication failed."
    }
    $script:commandStagingDirectory = $null
}

function Get-PytestOutcomeBinding {
    param(
        [Parameter(Mandatory)][string]$CommandId,
        [Parameter(Mandatory)][string]$Profile,
        [Parameter(Mandatory)][string]$ProfileNodeDigest,
        [Parameter(Mandatory)][Collections.IDictionary]$ShardNodeDigests
    )
    $arguments = @(
        "tools/project_optimization_baseline.py",
        "pytest-outcome-binding",
        "--source-sha", $SourceSha,
        "--command-id", $CommandId,
        "--profile", $Profile,
        "--profile-node-digest", $ProfileNodeDigest,
        "--platform-id", $platformId
    )
    foreach ($shard in @($ShardNodeDigests.Keys | Sort-Object)) {
        $arguments += @(
            "--shard-node-digest",
            "$shard=$($ShardNodeDigests[$shard])"
        )
    }
    Clear-PrivateCanaryEnvironment
    Clear-Stage0PytestOutcomeEnvironment
    $output = @(& $PythonExecutable @arguments 2>$null)
    if ($LASTEXITCODE -ne 0) {
        throw "Pytest outcome binding could not be created."
    }
    try {
        $payload = ($output -join "") | ConvertFrom-Json -AsHashtable
    }
    catch {
        throw "Pytest outcome binding is invalid."
    }
    if (
        $payload.binding_sha256 -isnot [string] -or
        $payload.binding_sha256 -cnotmatch '\A[0-9a-f]{64}\z'
    ) {
        throw "Pytest outcome binding is invalid."
    }
    return $payload.binding_sha256
}

function Get-ValidatedPytestOutcome {
    param(
        [Parameter(Mandatory)][string]$ReportDirectory,
        [Parameter(Mandatory)][string]$CommandId,
        [Parameter(Mandatory)][string]$Profile,
        [Parameter(Mandatory)][string]$ProfileNodeDigest,
        [Parameter(Mandatory)][Collections.IDictionary]$ShardNodeDigests
    )
    $arguments = @(
        "tools/project_optimization_baseline.py",
        "validate-pytest-outcomes",
        "--manifest", $manifest,
        "--report-directory", $ReportDirectory,
        "--source-sha", $SourceSha,
        "--command-id", $CommandId,
        "--profile", $Profile,
        "--profile-node-digest", $ProfileNodeDigest,
        "--platform-id", $platformId
    )
    foreach ($shard in @($ShardNodeDigests.Keys | Sort-Object)) {
        $arguments += @(
            "--shard-node-digest",
            "$shard=$($ShardNodeDigests[$shard])"
        )
    }
    Clear-PrivateCanaryEnvironment
    Clear-Stage0PytestOutcomeEnvironment
    $output = @(& $PythonExecutable @arguments 2>$null)
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    try {
        return (($output -join "") | ConvertFrom-Json -AsHashtable)
    }
    catch {
        return $null
    }
}

function Remove-OwnedDirectRegularChildren {
    param([Parameter(Mandatory)][string]$Directory)
    $resolvedDirectory = [IO.Path]::GetFullPath($Directory)
    $directoryItem = Get-Item -LiteralPath $resolvedDirectory -Force -ErrorAction Stop
    if (
        -not $directoryItem.PSIsContainer -or
        ($directoryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "Owned cleanup directory is invalid."
    }
    $comparison = if ($IsWindows) {
        [StringComparison]::OrdinalIgnoreCase
    }
    else {
        [StringComparison]::Ordinal
    }
    $invalidChild = $false
    foreach ($entry in @(Get-ChildItem -LiteralPath $resolvedDirectory -Force)) {
        $childPath = [IO.Path]::GetFullPath($entry.FullName)
        $parentPath = [IO.Path]::GetDirectoryName($childPath)
        if (
            -not $parentPath.Equals($resolvedDirectory, $comparison) -or
            $entry.PSIsContainer -or
            ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
        ) {
            $invalidChild = $true
            continue
        }
        Remove-Item -LiteralPath $childPath -Force -ErrorAction Stop
    }
    if (
        $invalidChild -or
        @(Get-ChildItem -LiteralPath $resolvedDirectory -Force).Count -ne 0
    ) {
        throw "Owned cleanup directory contains a non-regular child."
    }
    Remove-Item -LiteralPath $resolvedDirectory -Force -ErrorAction Stop
}

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory)][string]$Description,
        [Parameter(Mandatory)][scriptblock]$Command,
        [string]$EvidenceKey,
        [AllowNull()][object]$ProfileNodeDigest = $null,
        [string]$PytestOutcomeCommandId,
        [string]$PytestOutcomeProfile,
        [string[]]$PytestOutcomeShards = @(),
        [AllowNull()][Collections.IDictionary]$PytestOutcomeShardDigests = $null,
        [switch]$SuppressOutput,
        [switch]$CaptureOutput
    )
    $startedAt = [DateTimeOffset]::UtcNow
    $commandStreamDirectory = Join-Path (
        [IO.Path]::GetTempPath()
    ) ("project-optimization-command-" + [guid]::NewGuid().ToString("N"))
    $stdoutPath = Join-Path $commandStreamDirectory "stdout"
    $stderrPath = Join-Path $commandStreamDirectory "stderr"
    $outcomeReportDirectory = Join-Path $commandStreamDirectory "pytest-outcomes"
    $usesPytestOutcomes = -not [string]::IsNullOrWhiteSpace($PytestOutcomeCommandId)
    if (
        $null -ne $ProfileNodeDigest -and
        (
            $ProfileNodeDigest -isnot [string] -or
            $ProfileNodeDigest -cnotmatch '\A[0-9a-f]{64}\z'
        )
    ) {
        throw "Command profile identity is invalid."
    }
    if (
        $usesPytestOutcomes -and
        (
            [string]::IsNullOrWhiteSpace($PytestOutcomeProfile) -or
            $ProfileNodeDigest -cnotmatch '\A[0-9a-f]{64}\z' -or
            $PytestOutcomeShards.Count -eq 0 -or
            @($PytestOutcomeShards | Select-Object -Unique).Count -ne
                $PytestOutcomeShards.Count -or
            $null -eq $PytestOutcomeShardDigests -or
            $PytestOutcomeShardDigests.Count -ne $PytestOutcomeShards.Count
        )
    ) {
        throw "Pytest outcome identity is incomplete."
    }
    if ($usesPytestOutcomes) {
        foreach ($shard in $PytestOutcomeShards) {
            if (
                -not $PytestOutcomeShardDigests.Contains($shard) -or
                $PytestOutcomeShardDigests[$shard] -isnot [string] -or
                $PytestOutcomeShardDigests[$shard] -cnotmatch
                    '\A[0-9a-f]{64}\z'
            ) {
                throw "Pytest outcome shard identity is incomplete."
            }
        }
    }
    $exitCode = 1
    $caughtFailure = $false
    $capturedOutput = $null
    $pytestOutcomeEvidence = $null
    $outcomeBinding = $null
    $primaryError = $null
    $cleanupFailed = $false
    try {
        try {
            $null = New-Item `
                -ItemType Directory `
                -Path $commandStreamDirectory `
                -ErrorAction Stop
            if (-not $IsWindows) {
                $ownerDirectoryMode = (
                    [IO.UnixFileMode]::UserRead -bor
                    [IO.UnixFileMode]::UserWrite -bor
                    [IO.UnixFileMode]::UserExecute
                )
                [IO.File]::SetUnixFileMode(
                    $commandStreamDirectory,
                    $ownerDirectoryMode
                )
                if (
                    [IO.File]::GetUnixFileMode($commandStreamDirectory) -ne
                        $ownerDirectoryMode
                ) {
                    throw "Owner-only command stream directory creation failed."
                }
            }
            if ($usesPytestOutcomes) {
                $null = New-Item `
                    -ItemType Directory `
                    -Path $outcomeReportDirectory `
                    -ErrorAction Stop
                if (-not $IsWindows) {
                    [IO.File]::SetUnixFileMode(
                        $outcomeReportDirectory,
                        $ownerDirectoryMode
                    )
                    if (
                        [IO.File]::GetUnixFileMode($outcomeReportDirectory) -ne
                            $ownerDirectoryMode
                    ) {
                        throw "Owner-only pytest report directory creation failed."
                    }
                }
            }
            foreach ($streamPath in @($stdoutPath, $stderrPath)) {
                $stream = [IO.File]::Open(
                    $streamPath,
                    [IO.FileMode]::CreateNew,
                    [IO.FileAccess]::ReadWrite,
                    [IO.FileShare]::None
                )
                $stream.Dispose()
                if (-not $IsWindows) {
                    $ownerFileMode = (
                        [IO.UnixFileMode]::UserRead -bor
                        [IO.UnixFileMode]::UserWrite
                    )
                    [IO.File]::SetUnixFileMode($streamPath, $ownerFileMode)
                    if (
                        [IO.File]::GetUnixFileMode($streamPath) -ne
                            $ownerFileMode
                    ) {
                        throw "Owner-only command stream file creation failed."
                    }
                }
            }
        }
        catch {
            throw "Secure command stream initialization failed."
        }
        Clear-PrivateCanaryEnvironment
        Clear-Stage0PytestOutcomeEnvironment
        [Environment]::SetEnvironmentVariable(
            "PYTEST_ADDOPTS",
            [NullString]::Value,
            [EnvironmentVariableTarget]::Process
        )
        if ($usesPytestOutcomes) {
            $outcomeBinding = Get-PytestOutcomeBinding `
                -CommandId $PytestOutcomeCommandId `
                -Profile $PytestOutcomeProfile `
                -ProfileNodeDigest $ProfileNodeDigest `
                -ShardNodeDigests $PytestOutcomeShardDigests
            $orderedShardDigests = [ordered]@{}
            foreach ($shard in $PytestOutcomeShards) {
                $orderedShardDigests[$shard] = `
                    $PytestOutcomeShardDigests[$shard]
            }
            $env:APP_STAGE0_PYTEST_OUTCOME_DIRECTORY = $outcomeReportDirectory
            $env:APP_STAGE0_PYTEST_OUTCOME_BINDING = $outcomeBinding
            $env:APP_STAGE0_PYTEST_OUTCOME_COMMAND_ID = $PytestOutcomeCommandId
            $env:APP_STAGE0_PYTEST_OUTCOME_SHARD_DIGESTS = (
                $orderedShardDigests | ConvertTo-Json -Compress
            )
        }
        try {
            & $Command 1> $stdoutPath 2> $stderrPath
            $exitCode = $LASTEXITCODE
        }
        catch {
            $caughtFailure = $true
            if ($LASTEXITCODE -is [int] -and $LASTEXITCODE -ne 0) {
                $exitCode = $LASTEXITCODE
            }
        }
        finally {
            Clear-Stage0PytestOutcomeEnvironment
            Clear-PrivateCanaryEnvironment
        }
        $endedAt = [DateTimeOffset]::UtcNow
        $commandStatus = if ($exitCode -eq 0 -and -not $caughtFailure) {
            "passed"
        }
        else {
            "failed"
        }
        if (-not $SuppressOutput) {
            Write-TimingLine `
                -Phase "command" `
                -Status $commandStatus `
                -ElapsedSeconds (($endedAt - $startedAt).TotalSeconds) `
                -Description $Description
        }
        $stdoutBytes = if (Test-Path -LiteralPath $stdoutPath -PathType Leaf) {
            [IO.File]::ReadAllBytes($stdoutPath)
        }
        else {
            [byte[]]::new(0)
        }
        $stderrBytes = if (Test-Path -LiteralPath $stderrPath -PathType Leaf) {
            [IO.File]::ReadAllBytes($stderrPath)
        }
        else {
            [byte[]]::new(0)
        }
        if ($null -eq $stdoutBytes) {
            $stdoutBytes = [byte[]]::new(0)
        }
        if ($null -eq $stderrBytes) {
            $stderrBytes = [byte[]]::new(0)
        }
        $stdoutText = [Text.Encoding]::UTF8.GetString($stdoutBytes)
        $stderrText = [Text.Encoding]::UTF8.GetString($stderrBytes)
        if (-not $SuppressOutput) {
            foreach ($streamText in @($stdoutText, $stderrText)) {
                if (-not [string]::IsNullOrEmpty($streamText)) {
                    Write-Host (Protect-Output -Value $streamText).TrimEnd("`r", "`n")
                }
            }
        }
        $counts = [ordered]@{
            skip_count = 0
            explained_skip_count = 0
            unexplained_skip_count = 0
            xfail_count = 0
            retry_count = 0
            flaky_count = 0
        }
        $pytestOutcomeInvalid = $false
        if ($usesPytestOutcomes) {
            $pytestOutcomeEvidence = Get-ValidatedPytestOutcome `
                -ReportDirectory $outcomeReportDirectory `
                -CommandId $PytestOutcomeCommandId `
                -Profile $PytestOutcomeProfile `
                -ProfileNodeDigest $ProfileNodeDigest `
                -ShardNodeDigests $PytestOutcomeShardDigests
            if ($null -eq $pytestOutcomeEvidence) {
                $pytestOutcomeInvalid = $true
                $pytestOutcomeEvidence = [ordered]@{
                    status = "invalid"
                    binding_sha256 = $outcomeBinding
                    platform_id = $platformId
                    profile = $PytestOutcomeProfile
                    expected_report_shards = @($PytestOutcomeShards)
                    shard_node_digests = $PytestOutcomeShardDigests
                }
            }
            else {
                foreach ($name in @($counts.Keys)) {
                    $counts[$name] = [int]$pytestOutcomeEvidence[$name]
                }
            }
        }
        if (-not [string]::IsNullOrWhiteSpace($EvidenceKey)) {
            if ([string]::IsNullOrWhiteSpace($commandStagingDirectory)) {
                throw "Command result staging is required before command evidence."
            }
            $script:commandSequence += 1
            $resultPath = Join-Path $commandStagingDirectory (
                "command-result-{0:D2}-{1}.json" -f $script:commandSequence, $EvidenceKey
            )
            $payload = [ordered]@{
                schema_version = 2
                command_id = $EvidenceKey
                started_at = $startedAt.UtcDateTime.ToString("o")
                ended_at = $endedAt.UtcDateTime.ToString("o")
                exit_code = $exitCode
                skip_count = $counts.skip_count
                explained_skip_count = $counts.explained_skip_count
                unexplained_skip_count = $counts.unexplained_skip_count
                xfail_count = $counts.xfail_count
                retry_count = $counts.retry_count
                flaky_count = $counts.flaky_count
                stdout_sha256 = Get-Sha256Bytes -Value $stdoutBytes
                stderr_sha256 = Get-Sha256Bytes -Value $stderrBytes
                profile_node_digest = $ProfileNodeDigest
                pytest_outcome_evidence = $pytestOutcomeEvidence
            }
            Write-ExclusiveJson -Path $resultPath -Payload $payload
        }
        if ($caughtFailure -or $exitCode -ne 0) {
            throw "$Description failed with exit code $exitCode."
        }
        if ($pytestOutcomeInvalid) {
            throw "$Description pytest outcome evidence is invalid."
        }
        if (
            $counts.unexplained_skip_count -ne 0 -or
            $counts.xfail_count -ne 0 -or
            $counts.retry_count -ne 0 -or
            $counts.flaky_count -ne 0
        ) {
            throw "$Description reported non-deterministic test outcomes."
        }
        if ($CaptureOutput) {
            $capturedOutput = $stdoutText
        }
    }
    catch {
        $primaryError = $_
    }
    finally {
        Clear-Stage0PytestOutcomeEnvironment
        Clear-PrivateCanaryEnvironment
        if (
            $usesPytestOutcomes -and
            (Test-Path -LiteralPath $outcomeReportDirectory -PathType Container)
        ) {
            try {
                Remove-OwnedDirectRegularChildren `
                    -Directory $outcomeReportDirectory
            }
            catch {
                $cleanupFailed = $true
            }
        }
        foreach ($streamPath in @($stdoutPath, $stderrPath)) {
            try {
                if (Test-Path -LiteralPath $streamPath -PathType Leaf) {
                    Remove-Item -LiteralPath $streamPath -Force -ErrorAction Stop
                }
            }
            catch {
                $cleanupFailed = $true
            }
        }
        try {
            if (Test-Path -LiteralPath $commandStreamDirectory -PathType Container) {
                # Refuse nonempty directories without a platform-specific confirmation prompt.
                [IO.Directory]::Delete($commandStreamDirectory, $false)
            }
        }
        catch {
            $cleanupFailed = $true
        }
    }
    if ($null -ne $primaryError) {
        throw $primaryError
    }
    if ($cleanupFailed) {
        throw "Command stream cleanup failed."
    }
    if ($CaptureOutput) {
        return $capturedOutput
    }
}

function Get-ProfileNodeDigest {
    param(
        [Parameter(Mandatory)][string]$Name,
        [AllowNull()][string]$MySqlVersion = $null
    )
    $arguments = @("-Profile", $Name, "-ListOnly")
    if ($Name -ne "frontend-full") {
        $arguments += @("-PythonExecutable", $PythonExecutable)
    }
    if (-not [string]::IsNullOrWhiteSpace($MySqlVersion)) {
        $arguments += @("-MySqlVersion", $MySqlVersion)
    }
    Clear-PrivateCanaryEnvironment
    Clear-Stage0PytestOutcomeEnvironment
    [Environment]::SetEnvironmentVariable(
        "PYTEST_ADDOPTS",
        [NullString]::Value,
        [EnvironmentVariableTarget]::Process
    )
    $listed = @(
        & $pwshCommand `
            -NoProfile `
            -File scripts/run-ci-profile.ps1 `
            @arguments 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Profile identity collection failed."
    }
    $text = ($listed | ForEach-Object { [string]$_ }) -join "`n"
    $summaryLine = @($listed | Where-Object { ([string]$_).StartsWith("{") }) |
        Select-Object -Last 1
    if ($null -ne $summaryLine) {
        try {
            $summary = ([string]$summaryLine) | ConvertFrom-Json -AsHashtable
            if (
                $summary.ContainsKey("node_digest") -and
                $summary.node_digest -is [string] -and
                $summary.node_digest -match '\A[0-9a-f]{64}\z'
            ) {
                return $summary.node_digest
            }
        }
        catch {
            throw "Profile identity output is invalid."
        }
    }
    return Get-Sha256Text -Value ($text + "`n")
}

function Get-Stage0PytestIdentity {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$ExpectedProfile,
        [Parameter(Mandatory)][string[]]$ExpectedShards,
        [AllowNull()][string]$MySqlVersion = $null,
        [AllowNull()][string]$ReleaseSuite = $null
    )
    $arguments = @(
        "-Profile", $Name,
        "-Stage0IdentityOnly",
        "-PythonExecutable", $PythonExecutable
    )
    if (-not [string]::IsNullOrWhiteSpace($MySqlVersion)) {
        $arguments += @("-MySqlVersion", $MySqlVersion)
    }
    if (-not [string]::IsNullOrWhiteSpace($ReleaseSuite)) {
        $arguments += @(
            "-ReleaseSuite", $ReleaseSuite,
            "-SourceSha", $SourceSha
        )
    }
    Clear-PrivateCanaryEnvironment
    Clear-Stage0PytestOutcomeEnvironment
    [Environment]::SetEnvironmentVariable(
        "PYTEST_ADDOPTS",
        [NullString]::Value,
        [EnvironmentVariableTarget]::Process
    )
    $listed = @(
        & $pwshCommand `
            -NoProfile `
            -File scripts/run-ci-profile.ps1 `
            @arguments 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Stage 0 pytest identity collection failed."
    }
    $summaryLine = @(
        $listed | Where-Object { ([string]$_).StartsWith("{") }
    ) | Select-Object -Last 1
    try {
        $identity = ([string]$summaryLine) | ConvertFrom-Json -AsHashtable
    }
    catch {
        throw "Stage 0 pytest identity output is invalid."
    }
    if (
        $identity -isnot [Collections.IDictionary] -or
        @($identity.Keys).Count -ne 6 -or
        -not $identity.Contains("schema_version") -or
        -not $identity.Contains("profile") -or
        -not $identity.Contains("profile_node_count") -or
        -not $identity.Contains("profile_node_digest") -or
        -not $identity.Contains("shard_node_counts") -or
        -not $identity.Contains("shard_node_digests") -or
        $identity.schema_version -ne 1 -or
        $identity.profile -cne $ExpectedProfile -or
        $identity.profile_node_count -isnot [long] -or
        $identity.profile_node_count -le 0 -or
        $identity.profile_node_digest -isnot [string] -or
        $identity.profile_node_digest -cnotmatch '\A[0-9a-f]{64}\z' -or
        $identity.shard_node_counts -isnot [Collections.IDictionary] -or
        $identity.shard_node_digests -isnot [Collections.IDictionary] -or
        $identity.shard_node_counts.Count -ne $ExpectedShards.Count -or
        $identity.shard_node_digests.Count -ne $ExpectedShards.Count
    ) {
        throw "Stage 0 pytest identity output is invalid."
    }
    $countTotal = 0
    foreach ($shard in $ExpectedShards) {
        if (
            -not $identity.shard_node_counts.Contains($shard) -or
            $identity.shard_node_counts[$shard] -isnot [long] -or
            $identity.shard_node_counts[$shard] -le 0 -or
            -not $identity.shard_node_digests.Contains($shard) -or
            $identity.shard_node_digests[$shard] -isnot [string] -or
            $identity.shard_node_digests[$shard] -cnotmatch
                '\A[0-9a-f]{64}\z'
        ) {
            throw "Stage 0 pytest shard identity output is invalid."
        }
        $countTotal += $identity.shard_node_counts[$shard]
    }
    if ($countTotal -ne $identity.profile_node_count) {
        throw "Stage 0 pytest aggregate identity output is invalid."
    }
    return $identity
}

function Assert-ValidationPrerequisites {
    param(
        [Parameter(Mandatory)][string]$Docker,
        [Parameter(Mandatory)][string]$Node,
        [Parameter(Mandatory)][string]$Pnpm
    )
    $boundSourceSha = [Environment]::GetEnvironmentVariable(
        "APP_RELEASE_SOURCE_SHA",
        [EnvironmentVariableTarget]::Process
    )
    if ($boundSourceSha -cne $SourceSha) {
        throw "Candidate source identity is not bound to SourceSha."
    }
    Push-Location -LiteralPath $repositoryRoot
    try {
        $tree = (@(git rev-parse "$SourceSha^{tree}" 2>&1) -join "").Trim()
        if ($LASTEXITCODE -ne 0 -or $tree -cnotmatch '\A[0-9a-f]{40}\z') {
            throw "Candidate source tree identity is unavailable."
        }
        Write-Host ("Preflight candidate identity: sha={0}; tree={1}." -f $SourceSha, $tree)
    }
    finally {
        Pop-Location
    }
    $mysqlUrlProbe = @'
import os
from sqlalchemy.engine import make_url

for name in (
    "APP_DATABASE_URL",
    "APP_MIGRATION_DATABASE_URL",
    "APP_TEST_DATABASE_URL",
    "APP_TEST_RUNTIME_DATABASE_URL",
    "APP_TEST_BACKUP_DATABASE_URL",
):
    value = os.getenv(name)
    if value and make_url(value).drivername != "mysql+pymysql":
        raise RuntimeError("invalid MySQL URL shape")
'@
    $null = @(& $PythonExecutable -c $mysqlUrlProbe 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Configured MySQL URLs are invalid."
    }
    foreach ($version in @("8.0", "8.4")) {
        $null = @(& $Docker image inspect "mysql:$version" --format '{{.Id}}' 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "The required MySQL image is unavailable."
        }
    }
    $null = @(& $Docker version --format '{{.Server.Version}}' 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "The Docker daemon is unavailable."
    }
    $null = @(& $Node --version 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Node.js is unavailable."
    }
    $null = @(& $Pnpm --version 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "pnpm is unavailable."
    }
    Push-Location -LiteralPath (Join-Path $repositoryRoot "frontend")
    try {
        $null = @(& $Pnpm exec playwright --version 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "Playwright is unavailable."
        }
        $chromiumOutput = @(
            & $Node -e (
                "const { chromium } = require('@playwright/test');" +
                "process.stdout.write(chromium.executablePath());"
            ) 2>&1
        )
        if (
            $LASTEXITCODE -ne 0 -or
            -not (Test-Path -LiteralPath ($chromiumOutput -join "") -PathType Leaf)
        ) {
            throw "The pinned Chromium executable is unavailable."
        }
    }
    finally {
        Pop-Location
    }
    foreach ($entry in @(
            @{ Name = "APP_PRODUCT_CATALOG_MYSQL80_SCALE_EVIDENCE"; Version = "8.0" },
            @{ Name = "APP_PRODUCT_CATALOG_MYSQL84_SCALE_EVIDENCE"; Version = "8.4" }
        )) {
        $value = [Environment]::GetEnvironmentVariable($entry.Name)
        $path = Resolve-RequiredFile -Value $value -Label "Product catalog evidence"
        try {
            $payload = Get-Content -Raw -LiteralPath $path | ConvertFrom-Json -AsHashtable
        }
        catch {
            throw "Product catalog evidence is invalid."
        }
        if (
            $payload.fixture -cne "analytics_scale_v1" -or
            $payload.mysql_version -cne $entry.Version
        ) {
            throw "Product catalog evidence identity is invalid."
        }
    }
    $null = @(
        & $PythonExecutable `
            tools/project_optimization_baseline.py `
            validate-external-evidence `
            --source-sha $SourceSha `
            --mysql80-evidence $env:APP_PRODUCT_CATALOG_MYSQL80_SCALE_EVIDENCE `
            --mysql84-evidence $env:APP_PRODUCT_CATALOG_MYSQL84_SCALE_EVIDENCE 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Product catalog evidence is not current for this source and environment."
    }
}

function Assert-PlaywrightDeterminism {
    $reportPath = Join-Path $runDirectory "playwright-report.json"
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
        throw "The baseline browser report is missing."
    }
    try {
        $report = Get-Content -Raw -LiteralPath $reportPath |
            ConvertFrom-Json -AsHashtable
    }
    catch {
        throw "The baseline browser report is invalid."
    }
    if (
        $report.stats.expected -ne 4 -or
        $report.stats.skipped -ne 0 -or
        $report.stats.unexpected -ne 0 -or
        $report.stats.flaky -ne 0
    ) {
        throw "The baseline browser report has non-deterministic outcomes."
    }
    foreach ($suite in @($report.suites)) {
        foreach ($spec in @($suite.specs)) {
            foreach ($test in @($spec.tests)) {
                foreach ($result in @($test.results)) {
                    if ($result.retry -ne 0 -or $result.status -cne "passed") {
                        throw "The baseline browser report used a repeated attempt."
                    }
                }
            }
        }
    }
}

$timingParameterNames = @(
    "HeartbeatSeconds",
    "StaleSeconds",
    "OfflineSeconds",
    "RefreshSeconds"
)
$timingParameterCount = @(
    $timingParameterNames | Where-Object { $PSBoundParameters.ContainsKey($_) }
).Count
if ($timingParameterCount -ne 0 -and $timingParameterCount -ne 4) {
    throw "Replacement timing requires all four explicit values."
}
if (
    $Mode -ne "Freeze" -and
    (
        -not [string]::IsNullOrWhiteSpace($ApprovedBy) -or
        -not [string]::IsNullOrWhiteSpace($ApprovalReference) -or
        -not [string]::IsNullOrWhiteSpace($BudgetOverridesPath) -or
        $AcceptProposedBudgets -or
        -not [string]::IsNullOrWhiteSpace($ApprovedRunId) -or
        -not [string]::IsNullOrWhiteSpace($ApprovedToken) -or
        $CompleteFreeze -or
        $timingParameterCount -ne 0
    )
) {
    throw "Approval, budgets, and timing values are accepted only by Freeze."
}

$PythonExecutable = Resolve-RequiredFile `
    -Value $PythonExecutable `
    -Label "PythonExecutable" `
    -RequireAbsolute
$pwshCommand = Resolve-RequiredApplication -Names @("pwsh")
$null = Resolve-RequiredApplication -Names @("git")
$dockerCommand = Resolve-RequiredApplication -Names @("docker")
$nodeCommand = Resolve-RequiredApplication -Names @("node")
$pnpmCommand = if ($IsWindows) {
    Resolve-RequiredApplication -Names @("pnpm.cmd", "pnpm")
}
else {
    Resolve-RequiredApplication -Names @("pnpm")
}

Assert-CleanSource
$resolvedEvidenceRoot = Resolve-ExternalEvidenceRoot `
    -Value $EvidenceRoot `
    -RequireEmpty:($Mode -ne "Freeze")

try {
    Clear-PrivateCanaryEnvironment
    Clear-Stage0PytestOutcomeEnvironment
    [Environment]::SetEnvironmentVariable(
        "PYTEST_ADDOPTS",
        [NullString]::Value,
        [EnvironmentVariableTarget]::Process
    )
    [Environment]::SetEnvironmentVariable(
        "APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT",
        $resolvedEvidenceRoot
    )
    [Environment]::SetEnvironmentVariable("APP_RELEASE_SOURCE_SHA", $SourceSha)
    $env:APP_PROJECT_OPTIMIZATION_SYNTHETIC_ONLY = "1"
    $env:PLAYWRIGHT_BASELINE_RETRIES = "0"

    Push-Location -LiteralPath $repositoryRoot
    try {
        Invoke-NativeChecked "manifest validation" {
            & $PythonExecutable `
                tools/project_optimization_baseline.py `
                validate-manifest `
                --manifest $manifest
        } -SuppressOutput

        if ($Mode -ne "Freeze") {
            try {
                Assert-ValidationPrerequisites `
                    -Docker $dockerCommand `
                    -Node $nodeCommand `
                    -Pnpm $pnpmCommand
                Invoke-PlaywrightServicePreflight `
                    -Pnpm $pnpmCommand `
                    -EvidenceRoot $resolvedEvidenceRoot
            }
            catch {
                if ($_.Exception.Message -notlike "*see脱敏日志*") {
                    $log = Write-PreflightFailureLog `
                        -EvidenceRoot $resolvedEvidenceRoot `
                        -Stage "canonical-input-or-environment" `
                        -Message $_.Exception.Message
                    throw "Canonical baseline preflight failed; see脱敏日志 '$log'."
                }
                throw
            }
        }

        if ($Mode -eq "Validate") {
            Write-Output "Validated canonical baseline prerequisites for $SourceSha."
            return
        }

        if ($Mode -eq "Freeze") {
            $runCandidates = @(
                Get-ChildItem -LiteralPath $resolvedEvidenceRoot -Force |
                    Where-Object {
                        $_.PSIsContainer -and
                        $_.Name -cmatch '\Astage0-[0-9a-f]{12}\z'
                    }
            )
            $allRootEntries = @(Get-ChildItem -LiteralPath $resolvedEvidenceRoot -Force)
            if ($runCandidates.Count -ne 1 -or $allRootEntries.Count -ne 1) {
                throw "Freeze requires exactly one complete prepared run."
            }
            $runDirectory = $runCandidates[0].FullName
            [Environment]::SetEnvironmentVariable(
                "APP_PROJECT_OPTIMIZATION_RUN_DIR",
                $runDirectory
            )
            $validatedJson = Invoke-NativeChecked "evidence validation" {
                & $PythonExecutable `
                    tools/project_optimization_baseline.py `
                    freeze `
                    --run-dir $runDirectory `
                    --manifest $manifest `
                    --source-sha $SourceSha
            } -SuppressOutput -CaptureOutput
            $validated = $validatedJson | ConvertFrom-Json -AsHashtable
            Write-Output "Measured scenario table requiring explicit approval:"
            foreach ($name in @($validated.scenarios.Keys | Sort-Object)) {
                $row = $validated.scenarios[$name]
                Write-Output (
                    "{0}: p50={1}; p95={2}; max={3}; proposed_ceiling={4} {5}" -f
                    $name,
                    $row.rounds[1].p50,
                    $row.median_round_p95,
                    (($row.rounds | ForEach-Object { $_.max } | Measure-Object -Maximum).Maximum),
                    $row.proposed_ceiling,
                    $row.unit
                )
            }
            Write-Output (
                "Candidate timing: heartbeat={0}; stale={1}; offline={2}; " +
                "refresh={3}; offline_visible={4}." -f
                $validated.candidate_timing.heartbeat_seconds,
                $validated.candidate_timing.stale_seconds,
                $validated.candidate_timing.offline_seconds,
                $validated.candidate_timing.refresh_seconds,
                $validated.candidate_timing.offline_visible_seconds
            )
            Write-Output "Approval token: $($validated.approval_token)"
            if (-not $CompleteFreeze) {
                Write-Output (
                    "No approval was written. Review run {0}, then invoke Freeze " +
                    "again with -CompleteFreeze -ApprovedRunId {0}, " +
                    "-ApprovedToken {1}, approval identity/reference, all four " +
                    "timing values, and exactly one budget selection." -f
                    $validated.run_id,
                    $validated.approval_token
                )
                return
            }
            if ([string]$validated.run_id -cne $ApprovedRunId) {
                throw "ApprovedRunId does not match the validated run."
            }
            if ([string]$validated.approval_token -cne $ApprovedToken) {
                throw "ApprovedToken does not match the validated evidence."
            }
            if (
                [string]::IsNullOrWhiteSpace($ApprovedBy) -or
                [string]::IsNullOrWhiteSpace($ApprovalReference)
            ) {
                throw (
                    "Completing Freeze requires ApprovedBy and ApprovalReference " +
                    "after explicit project-owner approval."
                )
            }
            if ($timingParameterCount -ne 4) {
                throw "Completing Freeze requires all four explicit timing values."
            }
            $budgetSelectionCount = @(
                -not [string]::IsNullOrWhiteSpace($BudgetOverridesPath),
                [bool]$AcceptProposedBudgets
            ).Where({ $_ }).Count
            if ($budgetSelectionCount -ne 1) {
                throw (
                    "Completing Freeze requires exactly one complete " +
                    "BudgetOverridesPath or AcceptProposedBudgets."
                )
            }
            $freezeArguments = @(
                "tools/project_optimization_baseline.py",
                "freeze",
                "--run-dir", $runDirectory,
                "--manifest", $manifest,
                "--source-sha", $SourceSha,
                "--approved-by", $ApprovedBy,
                "--approval-reference", $ApprovalReference,
                "--approved-run-id", $ApprovedRunId,
                "--approved-token", $ApprovedToken,
                "--complete-freeze",
                "--heartbeat-seconds", [string]$HeartbeatSeconds,
                "--stale-seconds", [string]$StaleSeconds,
                "--offline-seconds", [string]$OfflineSeconds,
                "--refresh-seconds", [string]$RefreshSeconds,
                "--output", $approvalOutput
            )
            if (-not [string]::IsNullOrWhiteSpace($BudgetOverridesPath)) {
                $freezeArguments += @("--budget-overrides", $BudgetOverridesPath)
            }
            else {
                $freezeArguments += "--accept-proposed-budgets"
            }
            Invoke-NativeChecked "Freeze record generation" {
                & $PythonExecutable @freezeArguments
            } -SuppressOutput
            Write-Output "Freeze record created after explicit project-owner approval."
            return
        }

        $prepareOutput = @(
            & $PythonExecutable `
                tools/project_optimization_baseline.py `
                prepare-run `
                --manifest $manifest `
                --evidence-root $resolvedEvidenceRoot `
                --source-sha $SourceSha 2>&1
        )
        if ($LASTEXITCODE -ne 0) {
            throw "Run preparation failed."
        }
        try {
            $prepared = ($prepareOutput -join "") | ConvertFrom-Json -AsHashtable
            $runDirectory = [IO.Path]::GetFullPath([string]$prepared.run_directory)
        }
        catch {
            throw "Run preparation returned an invalid identity."
        }
        if (
            -not $runDirectory.StartsWith(
                $resolvedEvidenceRoot + [IO.Path]::DirectorySeparatorChar,
                [StringComparison]::OrdinalIgnoreCase
            ) -or
            (Split-Path -Leaf $runDirectory) -cnotmatch '\Astage0-[0-9a-f]{12}\z' -or
            -not (Test-Path -LiteralPath $runDirectory -PathType Container) -or
            -not (Test-Path `
                -LiteralPath (Join-Path $runDirectory "run-identity.json") `
                -PathType Leaf)
        ) {
            throw "Prepared run identity is outside EvidenceRoot."
        }
        [Environment]::SetEnvironmentVariable(
            "APP_PROJECT_OPTIMIZATION_RUN_DIR",
            $runDirectory
        )
        $commandStagingDirectory = Join-Path $resolvedEvidenceRoot (
            ".{0}-command-results" -f (Split-Path -Leaf $runDirectory)
        )
        if (Test-Path -LiteralPath $commandStagingDirectory) {
            throw "Command result staging path already exists."
        }
        $null = [IO.Directory]::CreateDirectory($commandStagingDirectory)

        $profiles = @(
            @{
                Name = "ubuntu-full"
                Key = "ubuntu-full"
                OutcomeProfile = "ubuntu-full"
                OutcomeShards = @("pytest")
            },
            @{
                Name = "windows-smoke"
                Key = "windows-smoke"
                OutcomeProfile = "windows-smoke"
                OutcomeShards = @("pytest")
            },
            @{ Name = "frontend-full"; Key = "frontend-full" },
            @{
                Name = "mysql-compatibility"
                Key = "mysql-compatibility-8-0"
                MySqlVersion = "8.0"
                OutcomeProfile = "mysql-compatibility"
                OutcomeShards = @("migration", "scoped")
            },
            @{
                Name = "mysql-compatibility"
                Key = "mysql-compatibility-8-4"
                MySqlVersion = "8.4"
                OutcomeProfile = "mysql-compatibility"
                OutcomeShards = @("migration", "scoped")
            }
        )
        foreach ($profile in $profiles) {
            $profileVersion = if ($profile.ContainsKey("MySqlVersion")) {
                $profile.MySqlVersion
            }
            else {
                $null
            }
            $arguments = @("-Profile", $profile.Name)
            if ($profile.Name -ne "frontend-full") {
                $arguments += @("-PythonExecutable", $PythonExecutable)
            }
            if ($null -ne $profileVersion) {
                $arguments += @("-MySqlVersion", $profileVersion)
            }
            $outcomeCommandId = if ($profile.ContainsKey("OutcomeProfile")) {
                $profile.Key
            }
            else {
                $null
            }
            $outcomeProfile = if ($profile.ContainsKey("OutcomeProfile")) {
                $profile.OutcomeProfile
            }
            else {
                $null
            }
            $outcomeShards = @(
                if ($profile.ContainsKey("OutcomeShards")) {
                    $profile.OutcomeShards
                }
            )
            $profileIdentity = if ($outcomeShards.Count -gt 0) {
                Get-Stage0PytestIdentity `
                    -Name $profile.Name `
                    -ExpectedProfile $outcomeProfile `
                    -ExpectedShards $outcomeShards `
                    -MySqlVersion $profileVersion
            }
            else {
                $null
            }
            $profileDigest = if ($null -ne $profileIdentity) {
                [string]$profileIdentity.profile_node_digest
            }
            else {
                Get-ProfileNodeDigest `
                    -Name $profile.Name `
                    -MySqlVersion $profileVersion
            }
            $outcomeShardDigests = if ($null -ne $profileIdentity) {
                $profileIdentity.shard_node_digests
            }
            else {
                $null
            }
            Invoke-NativeChecked "$($profile.Name) $profileVersion" {
                & $pwshCommand `
                    -NoProfile `
                    -File scripts/run-ci-profile.ps1 `
                    @arguments
            } `
                -EvidenceKey $profile.Key `
                -ProfileNodeDigest $profileDigest `
                -PytestOutcomeCommandId $outcomeCommandId `
                -PytestOutcomeProfile $outcomeProfile `
                -PytestOutcomeShards $outcomeShards `
                -PytestOutcomeShardDigests $outcomeShardDigests
        }

        Invoke-NativeChecked "OpenAPI drift" {
            & $pwshCommand `
                -NoProfile `
                -File scripts/generate-api-client.ps1 `
                -PythonExecutable $PythonExecutable `
                -Check
        } -EvidenceKey "generated-contract"
        Invoke-NativeChecked "existing product catalog baseline" {
            & $pwshCommand `
                -NoProfile `
                -File scripts/run-product-catalog-performance.ps1 `
                -SourceSha $SourceSha `
                -PythonExecutable $PythonExecutable `
                -ValidateOnly
        } -EvidenceKey "product-catalog-evidence"
        $stage0BackendIdentity = Get-Stage0PytestIdentity `
            -Name "release-only" `
            -ExpectedProfile "project-optimization-baseline" `
            -ExpectedShards @("scoped") `
            -ReleaseSuite "project-optimization-baseline"
        foreach ($version in @("8.0", "8.4")) {
            $env:APP_BASELINE_MYSQL_VERSION = $version
            $key = "stage0-backend-$($version.Replace('.', '-'))"
            Invoke-NativeChecked "stage 0 backend MySQL $version" {
                & $pwshCommand `
                    -NoProfile `
                    -File scripts/test-mysql-matrix.ps1 `
                    -Versions $version `
                    -Suites project-optimization-baseline `
                    -PythonExecutable $PythonExecutable `
                    -Confirm:$false
            } `
                -EvidenceKey $key `
                -ProfileNodeDigest $stage0BackendIdentity.profile_node_digest `
                -PytestOutcomeCommandId $key `
                -PytestOutcomeProfile "project-optimization-baseline" `
                -PytestOutcomeShards @("scoped") `
                -PytestOutcomeShardDigests `
                    $stage0BackendIdentity.shard_node_digests
        }
        Push-Location -LiteralPath (Join-Path $repositoryRoot "frontend")
        try {
            Invoke-NativeChecked "stage 0 UI" {
                & $pnpmCommand test:e2e:baseline
            } -EvidenceKey "stage0-ui"
            Assert-PlaywrightDeterminism
            Invoke-NativeChecked "stage 0 bundle" {
                & $pnpmCommand baseline:bundle
            } -EvidenceKey "stage0-bundle"
        }
        finally {
            Pop-Location
        }
        Publish-CommandResults
        Invoke-NativeChecked "finalize evidence" {
            & $PythonExecutable `
                tools/project_optimization_baseline.py `
                finalize-run `
                --run-dir $runDirectory `
                --manifest $manifest `
                --source-sha $SourceSha `
                --mysql80-evidence $env:APP_PRODUCT_CATALOG_MYSQL80_SCALE_EVIDENCE `
                --mysql84-evidence $env:APP_PRODUCT_CATALOG_MYSQL84_SCALE_EVIDENCE
        } -SuppressOutput
        Invoke-NativeChecked "evidence validation" {
            & $PythonExecutable `
                tools/project_optimization_baseline.py `
                validate-run `
                --run-dir $runDirectory `
                --manifest $manifest `
                --source-sha $SourceSha
        } -SuppressOutput
        Write-Output "Canonical same-SHA baseline evidence is complete and validated."
    }
    finally {
        Pop-Location
    }
}
finally {
    Restore-ManagedEnvironment -Snapshot $previousEnvironment
}
