# Focused contract checks for the diagnostic single-node MySQL timing entry.
# This test must not start Docker, MySQL, pytest, or the canonical baseline.
#Requires -Version 7.0

$ErrorActionPreference = "Stop"
$matrix = Join-Path $PSScriptRoot "../test-mysql-matrix.ps1"
$ciProfile = Join-Path $PSScriptRoot "../run-ci-profile.ps1"
$quickTest = Join-Path $PSScriptRoot "../../backend/tests/performance/test_project_optimization_baseline.py"
$baselineHelper = Join-Path $PSScriptRoot "../../backend/tests/performance/project_optimization_baseline.py"
$formalValidator = Join-Path $PSScriptRoot "../../tools/project_optimization_baseline.py"
$tokens = $null
$errors = $null
[Management.Automation.Language.Parser]::ParseFile(
    $matrix,
    [ref]$tokens,
    [ref]$errors
) | Out-Null
if ($errors.Count -ne 0) { throw "MySQL matrix PowerShell syntax is invalid." }

$script:checks = 0
function Assert-Contract([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    $script:checks++
}

$source = Get-Content -Raw -LiteralPath $matrix
$ciProfileSource = Get-Content -Raw -LiteralPath $ciProfile
foreach ($token in @(
        "Diagnostic",
        "QuickDiagnostic",
        "DiagnosticNode",
        "DiagnosticEvidenceRoot",
        "SourceSha",
        "Resolve-DiagnosticEvidenceRoot",
        "Invoke-CanonicalDiagnosticIdentity",
        "_release_identity",
        "diagnostic-identity.json",
        "formal_evidence = `$false",
        "finalize_run = `$false",
        "executor_script_sha256",
        "expected_migration_head",
        "database_migration_head",
        "Update-DiagnosticMigrationHead",
        "database_migration_head_status",
        "APP_PROJECT_OPTIMIZATION_RUN_DIR",
        "APP_RELEASE_SOURCE_SHA",
        "Write-MatrixTiming"
    )) {
    Assert-Contract ($source.Contains($token)) "Missing diagnostic contract token: $token"
}

$quickSource = Get-Content -Raw -LiteralPath $quickTest
$helperSource = Get-Content -Raw -LiteralPath $baselineHelper
$validatorSource = Get-Content -Raw -LiteralPath $formalValidator
foreach ($token in @(
        "test_heartbeat_long_task_quick_check",
        "APP_PROJECT_OPTIMIZATION_QUICK_CHECK",
        "long_task_observation",
        "write_quick_diagnostic_result",
        '"formal_evidence": False',
        "len(observations) != 3",
        "quick diagnostic mode only permits its explicit quick node"
    )) {
    Assert-Contract ($quickSource.Contains($token) -or $helperSource.Contains($token)) `
        "Missing quick diagnostic contract token: $token"
}
Assert-Contract ($matrix -and $source.Contains('"diagnostic-quick"')) `
    "Quick diagnostic mode does not have an isolated identity marker."
Assert-Contract ($source.Contains("independent_checks_per_version = 3")) `
    "Quick diagnostic mode does not declare three independent checks."
Assert-Contract ($source.Contains("p50_p95_distribution = `$false")) `
    "Quick diagnostic mode must not emit a p50/p95 distribution claim."
Assert-Contract ($validatorSource.Contains("quick diagnostic evidence is not valid formal evidence")) `
    "Formal validator does not explicitly reject quick diagnostic evidence."
Assert-Contract ($helperSource.Contains("quick diagnostic evidence is not valid formal evidence")) `
    "Baseline preflight does not reject quick diagnostic evidence."
Assert-Contract ($source.Contains("heartbeat_long_task_operations = 69")) `
    "Formal diagnostic protocol no longer declares the existing 69-sample contract."
Assert-Contract ($source -match 'test_heartbeat_long_task_quick_check') `
    "Quick diagnostic node is not an explicit matrix target."
Assert-Contract ($source.Contains('$formalSelectionArguments = @("--deselect", $quickDiagnosticNode)')) `
    "Formal MySQL collection does not deselect the quick diagnostic node."
Assert-Contract ($source.Contains('@formalSelectionArguments')) `
    "Formal MySQL execution does not apply the quick-node deselection."
Assert-Contract ($ciProfileSource.Contains('$releasePytestArguments += @(') -and
    $ciProfileSource.Contains('"--deselect"') -and
    $ciProfileSource.Contains('test_heartbeat_long_task_quick_check')) `
    "Stage 0 identity collection does not deselect the quick diagnostic node."

$preflightIndex = $source.IndexOf("Invoke-CanonicalDiagnosticIdentity")
$dockerIndex = $source.IndexOf('$dockerCommand = Get-Command -Name docker')
Assert-Contract ($preflightIndex -ge 0 -and $preflightIndex -lt $dockerIndex) `
    "Diagnostic identity preflight must run before Docker discovery."
Assert-Contract (
    $source -match 'ValidateSet\(\s*"tests/performance/test_project_optimization_baseline\.py::test_heartbeat_candidate_baselines"'
) "DiagnosticNode is not limited to the approved single test node."
Assert-Contract ($source -match 'if \(\$diagnosticMode\) \{\s*@\(\$diagnosticTestTarget\)') `
    "Diagnostic mode does not replace the test target with the selected node."
Assert-Contract ($source -match 'if \(\$LASTEXITCODE -ne 0\) \{\s*throw "MySQL \$version scoped tests failed') `
    "Diagnostic test failures do not preserve the existing nonzero exit path."
Assert-Contract ($source.Contains('$previousEnvironment[$name]')) `
    "Diagnostic environment does not use the existing previousEnvironment cleanup contract."
Assert-Contract ($source.Contains('[Environment]::SetEnvironmentVariable(')) `
    "Diagnostic environment cleanup does not restore process variables."
Assert-Contract ($source -notmatch 'finalize-run') `
    "Diagnostic entry must not finalize a formal release run."
Assert-Contract ($source -match '\[String\]::Equals\(\s*\$resolvedFull,\s*\$repositoryExact') `
    "Diagnostic evidence root does not explicitly reject the repository root itself."

# Missing identity input must fail before the script reaches Docker discovery.
$python = (Get-Command python -CommandType Application -ErrorAction Stop |
    Select-Object -First 1).Source
$diagnosticRoot = Join-Path ([IO.Path]::GetTempPath()) (
    "clsen-diagnostic-contract-" + [guid]::NewGuid().ToString("N")
)
New-Item -ItemType Directory -Path $diagnosticRoot | Out-Null
try {
    $output = @(
        & pwsh -NoProfile -File $matrix `
            -Diagnostic `
            -Versions 8.0 `
            -Suites project-optimization-baseline `
            -DiagnosticNode "tests/performance/test_project_optimization_baseline.py::test_heartbeat_candidate_baselines" `
            -DiagnosticEvidenceRoot $diagnosticRoot `
            -PythonExecutable $python `
            -Confirm:$false 2>&1
    )
    Assert-Contract ($LASTEXITCODE -ne 0) "Missing SourceSha unexpectedly succeeded."
    Assert-Contract (($output -join "") -like "*requires an explicit clean checkout SourceSha*") `
        "Missing SourceSha did not fail with an explicit preflight reason."
    Assert-Contract (@(Get-ChildItem -LiteralPath $diagnosticRoot -Force).Count -eq 0) `
        "Missing identity input created diagnostic evidence before Docker preflight."
}
finally {
    if (Test-Path -LiteralPath $diagnosticRoot) {
        Remove-Item -LiteralPath $diagnosticRoot -Recurse -Force
    }
}

Write-Output "MySQL diagnostic timing contract checks passed: $script:checks."
