#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$PathManifest,

    [Parameter()]
    [string]$BaselineRoot = $env:APP_PLAN_BASELINE_ROOT,

    [Parameter()]
    [string]$ReplacementLedger
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

function Get-Sha256Hex {
    param([Parameter(Mandatory)][byte[]]$Bytes)

    return [Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData($Bytes)
    ).ToLowerInvariant()
}

function Get-StrictJson {
    param(
        [Parameter(Mandatory)][string]$LiteralPath,
        [Parameter(Mandatory)][string]$Label
    )

    $bytes = [IO.File]::ReadAllBytes($LiteralPath)
    try {
        $text = [Text.UTF8Encoding]::new($false, $true).GetString($bytes)
    }
    catch {
        throw "$Label is not strict UTF-8."
    }
    $document = $null
    try {
        $document = [Text.Json.JsonDocument]::Parse($text)
        $seenByPath = @{}
        function Assert-NoDuplicateKeys {
            param(
                [Parameter(Mandatory)][Text.Json.JsonElement]$Element,
                [Parameter(Mandatory)][string]$JsonPath
            )
            if ($Element.ValueKind -eq [Text.Json.JsonValueKind]::Object) {
                $seen = [Collections.Generic.HashSet[string]]::new(
                    [StringComparer]::Ordinal
                )
                foreach ($property in $Element.EnumerateObject()) {
                    if (-not $seen.Add($property.Name)) {
                        throw "$Label has a duplicate key at $JsonPath."
                    }
                    Assert-NoDuplicateKeys `
                        -Element $property.Value `
                        -JsonPath "$JsonPath.$($property.Name)"
                }
            }
            elseif ($Element.ValueKind -eq [Text.Json.JsonValueKind]::Array) {
                $index = 0
                foreach ($item in $Element.EnumerateArray()) {
                    Assert-NoDuplicateKeys -Element $item -JsonPath "$JsonPath[$index]"
                    $index++
                }
            }
        }
        Assert-NoDuplicateKeys -Element $document.RootElement -JsonPath '$'
        return $text | ConvertFrom-Json -Depth 100 -ErrorAction Stop
    }
    catch {
        throw "$Label is not valid closed JSON: $($_.Exception.Message)"
    }
    finally {
        if ($null -ne $document) { $document.Dispose() }
    }
}

function Get-ValidatedManifest {
    param(
        [Parameter(Mandatory)][string]$LiteralPath,
        [Parameter(Mandatory)][string]$RepositoryRoot
    )

    if (-not (Test-Path -LiteralPath $LiteralPath -PathType Leaf)) {
        throw "Path manifest was not found."
    }
    $manifest = @(Get-StrictJson -LiteralPath $LiteralPath -Label "Path manifest")
    if ($manifest.Count -eq 0) { throw "Path manifest is empty." }
    $ordinal = [string[]]$manifest.Clone()
    [Array]::Sort($ordinal, [StringComparer]::Ordinal)
    if (($manifest -join "`n") -cne ($ordinal -join "`n")) {
        throw "Path manifest must be ordinal-sorted."
    }
    if (($manifest | Select-Object -Unique).Count -ne $manifest.Count) {
        throw "Path manifest must contain unique paths."
    }
    $repositoryPrefix = $RepositoryRoot + [IO.Path]::DirectorySeparatorChar
    foreach ($path in $manifest) {
        if (
            $path -isnot [string] -or
            [string]::IsNullOrWhiteSpace($path) -or
            [IO.Path]::IsPathRooted($path) -or
            $path.Contains("\")
        ) {
            throw "Path manifest contains an unsafe path."
        }
        $resolved = [IO.Path]::GetFullPath((Join-Path $repositoryPrefix $path))
        if (-not $resolved.StartsWith(
                $repositoryPrefix,
                [StringComparison]::OrdinalIgnoreCase
            )) {
            throw "Path manifest path escapes the repository."
        }
    }
    return [string[]]$manifest
}

function Invoke-GitBytes {
    param(
        [Parameter(Mandatory)][string]$RepositoryRoot,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = "git"
    $start.WorkingDirectory = $RepositoryRoot
    $start.UseShellExecute = $false
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($argument in $Arguments) { [void]$start.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::Start($start)
    $memory = [IO.MemoryStream]::new()
    try {
        $process.StandardOutput.BaseStream.CopyTo($memory)
        $errorText = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw "Git inspection failed without changing the worktree: $errorText"
        }
        return $memory.ToArray()
    }
    finally {
        $memory.Dispose()
        $process.Dispose()
    }
}

function ConvertFrom-GitStatusBytes {
    param(
        [Parameter(Mandatory)][byte[]]$Bytes,
        [Parameter(Mandatory)][string]$Label
    )

    try {
        $text = [Text.UTF8Encoding]::new($false, $true).GetString($Bytes)
    }
    catch {
        throw "$Label is not strict UTF-8."
    }
    $parts = $text.Split([char]0)
    $entries = [Collections.Generic.List[object]]::new()
    for ($index = 0; $index -lt $parts.Count; $index++) {
        $record = $parts[$index]
        if ([string]::IsNullOrEmpty($record)) { continue }
        if ($record.Length -lt 4 -or $record[2] -ne " ") {
            throw "$Label contains an invalid porcelain record."
        }
        $status = $record.Substring(0, 2)
        $path = $record.Substring(3).Replace("\", "/")
        $paths = [Collections.Generic.List[string]]::new()
        [void]$paths.Add($path)
        $token = "$status`0$path"
        if ($status.Contains("R") -or $status.Contains("C")) {
            $index++
            if ($index -ge $parts.Count -or [string]::IsNullOrEmpty($parts[$index])) {
                throw "$Label contains an incomplete rename/copy record."
            }
            $sourcePath = $parts[$index].Replace("\", "/")
            [void]$paths.Add($sourcePath)
            $token += "`0$sourcePath"
        }
        [void]$entries.Add([pscustomobject]@{
            Token = $token
            Paths = [string[]]$paths
        })
    }
    return [object[]]$entries
}

$repositoryRoot = [IO.Path]::GetFullPath(
    ((git rev-parse --show-toplevel) -join "").Trim()
)
if ([string]::IsNullOrWhiteSpace($BaselineRoot)) {
    throw "APP_PLAN_BASELINE_ROOT or -BaselineRoot is required."
}
$resolvedBaseline = [IO.Path]::GetFullPath($BaselineRoot)
$repositoryPrefix = $repositoryRoot + [IO.Path]::DirectorySeparatorChar
if ($resolvedBaseline.StartsWith(
        $repositoryPrefix,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Private baseline must remain outside the repository."
}
if (-not (Test-Path -LiteralPath $resolvedBaseline -PathType Container)) {
    throw "Private baseline directory was not found."
}
$baselineInfo = Get-Item -LiteralPath $resolvedBaseline -Force
if (($baselineInfo.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "Private baseline must not be a reparse point."
}

$manifestPath = [IO.Path]::GetFullPath($PathManifest)
$manifest = Get-ValidatedManifest `
    -LiteralPath $manifestPath `
    -RepositoryRoot $repositoryRoot
$manifestBytes = [IO.File]::ReadAllBytes($manifestPath)
$manifestSha256 = Get-Sha256Hex -Bytes $manifestBytes

$requiredBaselineFiles = @(
    "baseline.json",
    "git-ls-files-stage-z.bin",
    "git-status-z.bin",
    "head.txt",
    "manifest.json",
    "path-ownership.json",
    "repo-root.txt",
    "task0-gate.json"
)
foreach ($name in $requiredBaselineFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $resolvedBaseline $name) -PathType Leaf)) {
        throw "Private baseline is missing required evidence '$name'."
    }
}

$baseline = Get-StrictJson `
    -LiteralPath (Join-Path $resolvedBaseline "baseline.json") `
    -Label "Private baseline metadata"
$ownership = Get-StrictJson `
    -LiteralPath (Join-Path $resolvedBaseline "path-ownership.json") `
    -Label "Path ownership metadata"
$taskZeroGate = Get-StrictJson `
    -LiteralPath (Join-Path $resolvedBaseline "task0-gate.json") `
    -Label "Task 0 gate metadata"

$repositorySha256 = Get-Sha256Hex -Bytes (
    [Text.Encoding]::UTF8.GetBytes($repositoryRoot)
)
if (
    $baseline.format_version -ne 1 -or
    $baseline.repository_sha256 -cne $repositorySha256 -or
    $baseline.manifest_sha256 -cne $manifestSha256 -or
    $baseline.manifest_count -ne $manifest.Count -or
    $ownership.manifest_sha256 -cne $manifestSha256 -or
    @($ownership.records).Count -ne $manifest.Count -or
    @($ownership.unmapped_paths).Count -ne 0 -or
    $taskZeroGate.manifest_count -ne $manifest.Count
) {
    throw "Private baseline metadata is forged or inconsistent."
}
$storedRepositoryRoot = [IO.File]::ReadAllText(
    (Join-Path $resolvedBaseline "repo-root.txt"),
    [Text.Encoding]::UTF8
)
if ($storedRepositoryRoot -cne $repositoryRoot) {
    throw "Private baseline repository identity is inconsistent."
}
$storedManifest = [IO.File]::ReadAllBytes((Join-Path $resolvedBaseline "manifest.json"))
if ((Get-Sha256Hex -Bytes $storedManifest) -cne $manifestSha256) {
    throw "Private baseline manifest digest is inconsistent."
}
$currentHead = ((git -C $repositoryRoot rev-parse HEAD) -join "").Trim()
$storedHead = [IO.File]::ReadAllText(
    (Join-Path $resolvedBaseline "head.txt"),
    [Text.Encoding]::UTF8
).Trim()
if ($baseline.head -cne $storedHead -or $currentHead -cne $storedHead) {
    throw "Private baseline HEAD does not match the current worktree."
}

$manifestSet = [Collections.Generic.HashSet[string]]::new(
    [string[]]$manifest,
    [StringComparer]::Ordinal
)
$statusBytes = Invoke-GitBytes `
    -RepositoryRoot $repositoryRoot `
    -Arguments @("status", "--porcelain=v1", "-z", "--untracked-files=all")
$baselineStatusBytes = [IO.File]::ReadAllBytes(
    (Join-Path $resolvedBaseline "git-status-z.bin")
)
$currentStatusEntries = @(
    ConvertFrom-GitStatusBytes -Bytes $statusBytes -Label "Current Git status"
)
$baselineStatusEntries = @(
    ConvertFrom-GitStatusBytes -Bytes $baselineStatusBytes -Label "Task 0 Git status"
)
$baselineUnregisteredTokens = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::Ordinal
)
foreach ($entry in $baselineStatusEntries) {
    if (@($entry.Paths | Where-Object { $manifestSet.Contains($_) }).Count -eq 0) {
        [void]$baselineUnregisteredTokens.Add($entry.Token)
    }
}
$currentUnregisteredTokens = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::Ordinal
)
foreach ($entry in $currentStatusEntries) {
    if (@($entry.Paths | Where-Object { $manifestSet.Contains($_) }).Count -eq 0) {
        [void]$currentUnregisteredTokens.Add($entry.Token)
        if (-not $baselineUnregisteredTokens.Contains($entry.Token)) {
            throw "Worktree contains an unregistered path changed since Task 0: $($entry.Paths[0])"
        }
    }
}
foreach ($entry in $baselineStatusEntries) {
    if (
        @($entry.Paths | Where-Object { $manifestSet.Contains($_) }).Count -eq 0 -and
        -not $currentUnregisteredTokens.Contains($entry.Token)
    ) {
        throw "Worktree lost or changed a pre-existing unregistered path: $($entry.Paths[0])"
    }
}

$entryByPath = @{}
foreach ($entry in @($baseline.entries)) { $entryByPath[[string]$entry.path] = $entry }
$ownerByPath = @{}
foreach ($record in @($ownership.records)) { $ownerByPath[[string]$record.path] = $record }
$allowedReplacementKeys = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::Ordinal
)
if ([string]::IsNullOrWhiteSpace($ReplacementLedger)) {
    $candidateLedger = Join-Path $resolvedBaseline "task1-replacements.json"
    if (Test-Path -LiteralPath $candidateLedger -PathType Leaf) {
        $ReplacementLedger = $candidateLedger
    }
}
if (-not [string]::IsNullOrWhiteSpace($ReplacementLedger)) {
    $resolvedReplacementLedger = [IO.Path]::GetFullPath($ReplacementLedger)
    if (-not $resolvedReplacementLedger.StartsWith(
            $resolvedBaseline + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )) {
        throw "Task 1 replacement ledger must remain inside the private baseline root."
    }
    $ledgerInfo = Get-Item -LiteralPath $resolvedReplacementLedger -Force
    if (($ledgerInfo.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Task 1 replacement ledger must not be a reparse point."
    }
    $replacementLedgerData = Get-StrictJson `
        -LiteralPath $resolvedReplacementLedger `
        -Label "Task 1 replacement ledger"
    if (
        $replacementLedgerData.format_version -ne 1 -or
        $replacementLedgerData.task_id -cne "1" -or
        $replacementLedgerData.manifest_sha256 -cne $manifestSha256 -or
        $replacementLedgerData.baseline_head -cne $storedHead
    ) {
        throw "Task 1 replacement ledger is forged or bound to another baseline."
    }
    $previousReplacementKey = $null
    foreach ($replacement in @($replacementLedgerData.entries)) {
        $replacementPath = [string]$replacement.path
        $originalLineSha256 = [string]$replacement.original_line_sha256
        $currentFileSha256 = [string]$replacement.current_file_sha256
        $replacementKey = "$replacementPath`0$originalLineSha256"
        if (
            -not $manifestSet.Contains($replacementPath) -or
            -not $entryByPath.ContainsKey($replacementPath) -or
            -not $entryByPath[$replacementPath].overlap -or
            $originalLineSha256 -notmatch "\A[0-9a-f]{64}\z" -or
            $currentFileSha256 -notmatch "\A[0-9a-f]{64}\z" -or
            $replacement.reason_code -cne "task1_semantic_replacement" -or
            ($null -ne $previousReplacementKey -and
                [StringComparer]::Ordinal.Compare(
                    $previousReplacementKey,
                    $replacementKey
                ) -ge 0)
        ) {
            throw "Task 1 replacement ledger contains an invalid or unsorted entry."
        }
        $currentReplacementPath = Join-Path $repositoryRoot $replacementPath
        if (-not (Test-Path -LiteralPath $currentReplacementPath -PathType Leaf)) {
            throw "Task 1 replacement ledger references a missing worktree file."
        }
        if ((Get-Sha256Hex -Bytes ([IO.File]::ReadAllBytes($currentReplacementPath))) -cne
            $currentFileSha256) {
            throw "Task 1 replacement ledger does not match the current candidate file."
        }
        if (-not $allowedReplacementKeys.Add($replacementKey)) {
            throw "Task 1 replacement ledger contains a duplicate entry."
        }
        $previousReplacementKey = $replacementKey
    }
}
foreach ($path in $manifest) {
    if (-not $entryByPath.ContainsKey($path) -or -not $ownerByPath.ContainsKey($path)) {
        throw "Private baseline omitted a manifest path."
    }
    $entry = $entryByPath[$path]
    $owner = $ownerByPath[$path]
    if (@($owner.owner_tasks_in_order).Count -eq 0) {
        throw "Path ownership metadata omitted an owner task."
    }
    if ($entry.overlap -ne $owner.overlap) {
        throw "Path ownership overlap metadata is inconsistent."
    }
    if ($null -ne $entry.raw_object) {
        $rawPath = [IO.Path]::GetFullPath((Join-Path $resolvedBaseline $entry.raw_object))
        if (-not $rawPath.StartsWith(
                $resolvedBaseline + [IO.Path]::DirectorySeparatorChar,
                [StringComparison]::OrdinalIgnoreCase
            )) {
            throw "Private baseline raw object escapes its root."
        }
        $rawBytes = [IO.File]::ReadAllBytes($rawPath)
        if (
            $rawBytes.LongLength -ne $entry.length -or
            (Get-Sha256Hex -Bytes $rawBytes) -cne $entry.sha256
        ) {
            throw "Private baseline raw object metadata is forged."
        }
    }
    if ($entry.overlap) {
        $currentPath = Join-Path $repositoryRoot $path
        if (-not (Test-Path -LiteralPath $currentPath -PathType Leaf)) {
            throw "A path containing original user content was removed: $path"
        }
        $currentText = [IO.File]::ReadAllText($currentPath, [Text.Encoding]::UTF8)
        $diffPath = Join-Path $resolvedBaseline $entry.git_evidence.unstaged_diff
        foreach ($line in [IO.File]::ReadAllLines($diffPath, [Text.Encoding]::UTF8)) {
            if (
                $line.StartsWith("+") -and
                -not $line.StartsWith("+++") -and
                -not [string]::IsNullOrWhiteSpace($line.Substring(1)) -and
                -not $currentText.Contains($line.Substring(1), [StringComparison]::Ordinal)
            ) {
                $originalLineSha256 = Get-Sha256Hex -Bytes (
                    [Text.Encoding]::UTF8.GetBytes($line.Substring(1))
                )
                if (-not $allowedReplacementKeys.Contains(
                        "$path`0$originalLineSha256"
                    )) {
                    throw "A path lost original user content without a private Task 1 replacement record: $path"
                }
            }
        }
    }
}

Write-Output ((
    "Plan baseline PASS: {0} registered paths; original user content and " +
    "unregistered path boundaries verified."
) -f $manifest.Count)
