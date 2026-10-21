# Focused A-batch runner contract and startup check.
# This test does not run MySQL, pytest, Storybook, or the canonical baseline.
# It starts only the Vite process owned by the preflight helper and verifies
# that the helper stops that process before returning.
#Requires -Version 7.0

$ErrorActionPreference = "Stop"
$runner = Join-Path $PSScriptRoot "../run-project-optimization-baseline.ps1"
$matrix = Join-Path $PSScriptRoot "../test-mysql-matrix.ps1"
$tokens = $null
$errors = $null
$runnerAst = [Management.Automation.Language.Parser]::ParseFile(
    $runner,
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count -ne 0) { throw "Baseline runner PowerShell syntax is invalid." }
$matrixTokens = $null
$matrixErrors = $null
[Management.Automation.Language.Parser]::ParseFile(
    $matrix,
    [ref]$matrixTokens,
    [ref]$matrixErrors
) | Out-Null
if ($matrixErrors.Count -ne 0) { throw "MySQL matrix PowerShell syntax is invalid." }

$script:checks = 0
function Assert-Contract([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    $script:checks++
}

$runnerSource = Get-Content -Raw -LiteralPath $runner
$matrixSource = Get-Content -Raw -LiteralPath $matrix
Assert-Contract ($runnerSource -match "Write-PreflightFailureLog") "Missing preflight failure log contract."
Assert-Contract ($runnerSource -match "Invoke-PlaywrightServicePreflight") "Missing service preflight contract."
Assert-Contract ($runnerSource.Contains('$process.Kill($true)')) "Preflight does not clean its own process tree."
Assert-Contract ($runnerSource.IndexOf("Assert-ValidationPrerequisites") -lt $runnerSource.IndexOf("prepare-run")) "Preflight runs after expensive preparation."
Assert-Contract ($runnerSource -match "PLAYWRIGHT_PORT") "Preflight does not honor the configured Playwright port."
foreach ($phase in @("database-startup", "migration", "tests", "cleanup")) {
    Assert-Contract ($matrixSource -match [regex]::Escape(("-Phase `"{0}`"" -f $phase))) "Missing MySQL $phase timing."
}
Assert-Contract ($matrixSource -match "Write-MatrixTiming") "MySQL timing output is not observable."

# Load only the helper function definitions; the runner's main body is not executed.
foreach ($name in @(
        "Protect-Output",
        "Write-TimingLine",
        "Write-PreflightFailureLog",
        "Get-PlaywrightPort",
        "Get-PreflightViteProcessIds",
        "Invoke-PlaywrightServicePreflight"
    )) {
    $function = $runnerAst.FindAll({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -ceq $name
    }, $true) | Select-Object -First 1
    if ($null -eq $function) { throw "Missing helper function $name." }
    . ([scriptblock]::Create($function.Extent.Text))
}

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../.."))
$pnpm = (Get-Command pnpm.cmd, pnpm -CommandType Application -ErrorAction Stop |
    Select-Object -First 1).Source
$evidenceRoot = Join-Path ([IO.Path]::GetTempPath()) (
    "clsen-preflight-contract-" + [guid]::NewGuid().ToString("N")
)
New-Item -ItemType Directory -Path $evidenceRoot | Out-Null
$portProbe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$null = $portProbe.Start()
$port = ([Net.IPEndPoint]$portProbe.LocalEndpoint).Port
$portProbe.Stop()
$previousPort = [Environment]::GetEnvironmentVariable("PLAYWRIGHT_PORT")
try {
    [Environment]::SetEnvironmentVariable("PLAYWRIGHT_PORT", [string]$port)
    Invoke-PlaywrightServicePreflight -Pnpm $pnpm -EvidenceRoot $evidenceRoot
    $leftListening = $false
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $client.Connect("127.0.0.1", $port)
        $leftListening = $true
    }
    catch { }
    finally { $client.Dispose() }
    Assert-Contract (-not $leftListening) "Preflight left a listener behind."
    [Environment]::SetEnvironmentVariable("PLAYWRIGHT_PORT", "not-a-port")
    $failureMessage = $null
    try {
        Invoke-PlaywrightServicePreflight -Pnpm $pnpm -EvidenceRoot $evidenceRoot
    }
    catch { $failureMessage = $_.Exception.Message }
    Assert-Contract ($failureMessage -like "*preflight-failure.log*") "Invalid port did not stop with a log path."
    $failureLog = Join-Path $evidenceRoot "preflight-failure.log"
    Assert-Contract (Test-Path -LiteralPath $failureLog -PathType Leaf) "Preflight failure log was not retained."
    Assert-Contract ((Get-Content -Raw -LiteralPath $failureLog) -notmatch "sentinel-password") "Preflight log was not sanitized."
}
finally {
    [Environment]::SetEnvironmentVariable("PLAYWRIGHT_PORT", $previousPort)
    if (Test-Path -LiteralPath $evidenceRoot) {
        Remove-Item -LiteralPath $evidenceRoot -Recurse -Force
    }
}

Write-Output "Project optimization A-batch contract/startup checks passed: $script:checks."
