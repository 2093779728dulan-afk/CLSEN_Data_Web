[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$frontendDirectory = Join-Path $repositoryRoot "frontend"
$packageManifest = Join-Path $frontendDirectory "package.json"

if (-not (Test-Path -LiteralPath $packageManifest -PathType Leaf)) {
    throw "Frontend package manifest not found at '$packageManifest'. The repository checkout may be incomplete."
}

$packageManagerSpecifier = (Get-Content -LiteralPath $packageManifest -Raw | ConvertFrom-Json).packageManager
if (
    $packageManagerSpecifier -isnot [string] -or
    $packageManagerSpecifier -notmatch '^pnpm@[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+sha[0-9]+\.[0-9A-Fa-f]+)?$'
) {
    throw "The frontend packageManager must pin a pnpm version (for example, 'pnpm@11.16.0')."
}
$expectedPnpmVersion = $packageManagerSpecifier.Substring('pnpm@'.Length) -replace '\+sha[0-9]+\.[0-9A-Fa-f]+$', ''

$nodeCommand = Get-Command -Name node -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $nodeCommand) {
    throw "Node.js is not available on PATH. Install the Node.js version required by the project before starting the frontend."
}

$runningOnWindows = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [System.Runtime.InteropServices.OSPlatform]::Windows
)
if ($runningOnWindows) {
    $corepackCommand = Get-Command -Name corepack.cmd -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $pnpmCommand = Get-Command -Name pnpm.cmd -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
}
else {
    $corepackCommand = Get-Command -Name corepack -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $pnpmCommand = Get-Command -Name pnpm -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
}

if (-not $corepackCommand -and -not $pnpmCommand) {
    throw "Neither Corepack nor pnpm is available on PATH. Install a supported Node.js release with Corepack, or install pnpm, before starting the frontend."
}

if (-not $corepackCommand) {
    $pnpmVersionOutput = @(& $pnpmCommand.Source --version)
    $pnpmVersionExitCode = $LASTEXITCODE
    if ($pnpmVersionExitCode -ne 0) {
        throw "pnpm failed while checking its version (exit code $pnpmVersionExitCode)."
    }
    $installedPnpmVersion = ($pnpmVersionOutput | Select-Object -Last 1)
    if ($installedPnpmVersion -isnot [string] -or [string]::IsNullOrWhiteSpace($installedPnpmVersion)) {
        throw "pnpm did not report its version."
    }
    $installedPnpmVersion = $installedPnpmVersion.Trim()
    if ($installedPnpmVersion -ne $expectedPnpmVersion) {
        throw "pnpm $installedPnpmVersion is available, but the frontend requires pnpm $expectedPnpmVersion. Install the required version or use Node.js with Corepack."
    }
}

Push-Location -LiteralPath $frontendDirectory
try {
    # Specify the manifest's package-manager version explicitly. Corepack otherwise
    # may resolve a different pnpm version when invoked from another working directory.
    if ($corepackCommand) {
        & $corepackCommand.Source $packageManagerSpecifier dev
    }
    else {
        & $pnpmCommand.Source dev
    }

    if ($LASTEXITCODE -ne 0) {
        throw "The frontend development server exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
