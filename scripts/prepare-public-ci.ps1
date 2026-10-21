#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$manifest = Get-Content -LiteralPath (Join-Path $root 'public-ci-source.json') -Raw | ConvertFrom-Json
$committedBlobs = @{}
git -C $root ls-tree -r HEAD | ForEach-Object {
    if ($_ -match '^\d+ blob ([0-9a-f]{40})\t(.+)$') { $committedBlobs[$Matches[2]] = $Matches[1] }
}
if ($LASTEXITCODE -ne 0) { throw 'Unable to read committed publication tree.' }
git -C $root diff --quiet HEAD --
if ($LASTEXITCODE -ne 0) { throw 'Published checkout contains modified tracked files.' }
foreach ($entry in $manifest.files) {
    $storedPath = if ($entry.path -match '^\.github/workflows/([^/]+\.yml)$') {
        '.github/private-workflow-reference/' + $Matches[1]
    } else { $entry.path }
    # Canonical Git blobs avoid false mismatches from Windows CRLF checkout.
    if ($committedBlobs[$storedPath] -cne $entry.git_blob) {
        throw "Published Git blob differs from recorded source: $($entry.path)"
    }
}
# These files are data for private-source policy tests, not public job definitions.
# Job scheduling has already used public-ci.yml. No private workflow is dispatched.
foreach ($name in @('compatibility.yml', 'release-gates.yml', 'self-hosted-smoke.yml')) {
    Copy-Item -LiteralPath (Join-Path $root ".github/private-workflow-reference/$name") `
        -Destination (Join-Path $root ".github/workflows/$name") -Force
}
Write-Host "Verified published source $($manifest.source_sha); restored reference files for source contract tests."
