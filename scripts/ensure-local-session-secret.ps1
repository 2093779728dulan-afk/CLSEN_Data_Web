#Requires -Version 7.0

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()]
    [switch]$Rotate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $IsWindows) {
    throw "This local environment upgrade script currently supports Windows only."
}

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$environmentFile = [IO.Path]::GetFullPath((Join-Path $repositoryRoot ".env"))
$expectedEnvironmentFile = Join-Path $repositoryRoot ".env"
if (-not $environmentFile.Equals($expectedEnvironmentFile, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Environment file resolved outside the repository root."
}

function Set-PrivatePathAcl {
    param(
        [Parameter(Mandatory)]
        [string]$LiteralPath
    )

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $acl = Get-Acl -LiteralPath $LiteralPath
    $acl.SetAccessRuleProtection($true, $false)
    $existingRules = @(
        $acl.GetAccessRules(
            $true,
            $false,
            [Security.Principal.NTAccount]
        )
    )
    foreach ($existingRule in $existingRules) {
        $acl.RemoveAccessRuleSpecific($existingRule)
    }
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        $identity,
        [Security.AccessControl.FileSystemRights]::FullControl,
        [Security.AccessControl.InheritanceFlags]::None,
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow
    )
    $acl.SetAccessRule($rule)
    [IO.FileSystemAclExtensions]::SetAccessControl(
        [IO.FileInfo]::new($LiteralPath),
        $acl
    )
}

function Test-PrivatePathAcl {
    param(
        [Parameter(Mandatory)]
        [string]$LiteralPath
    )

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $acl = Get-Acl -LiteralPath $LiteralPath
    if (-not $acl.AreAccessRulesProtected) {
        throw "The environment file ACL still inherits permissions."
    }
    $rules = @(
        $acl.GetAccessRules(
            $true,
            $true,
            [Security.Principal.NTAccount]
        )
    )
    if ($rules.Count -ne 1) {
        throw "The environment file ACL must contain exactly one explicit rule."
    }
    $rule = $rules[0]
    if (
        -not $rule.IdentityReference.Value.Equals(
            $identity,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        $rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
        ($rule.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -ne
            [Security.AccessControl.FileSystemRights]::FullControl
    ) {
        throw "The environment file ACL is not restricted to the current user."
    }
}

function New-RandomSessionSecret {
    $secretBytes = [byte[]]::new(32)
    try {
        [Security.Cryptography.RandomNumberGenerator]::Fill($secretBytes)
        return [Convert]::ToHexString($secretBytes).ToLowerInvariant()
    }
    finally {
        [Array]::Clear($secretBytes, 0, $secretBytes.Length)
    }
}

if (-not (Test-Path -LiteralPath $environmentFile -PathType Leaf)) {
    throw "The protected local .env file does not exist. Run the database bootstrap first."
}
$environmentItem = Get-Item -LiteralPath $environmentFile -Force
if (($environmentItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "The local .env file must not be a reparse point."
}

$utf8 = [Text.UTF8Encoding]::new($false, $true)
$environmentContent = [IO.File]::ReadAllText($environmentFile, $utf8)
if ($environmentContent.Contains([char]0)) {
    throw "The local .env file contains a NUL character."
}
$sessionEntries = [regex]::Matches(
    $environmentContent,
    '(?im)^[ \t]*APP_SESSION_SECRET=([^\r\n]*)'
)
if ($sessionEntries.Count -gt 1) {
    throw "Duplicate APP_SESSION_SECRET entries were found; repair the .env file manually."
}

$knownPublicValues = @(
    "development-only-session-secret-change-before-deployment",
    "CHANGE_ME_TO_A_LONG_RANDOM_SECRET"
)
$needsReplacement = $Rotate -or $sessionEntries.Count -eq 0
if ($sessionEntries.Count -eq 1) {
    $existingValue = $sessionEntries[0].Groups[1].Value
    $comparisonValue = $existingValue.Trim('"', "'")
    if (
        $comparisonValue.Length -lt 32 -or
        $comparisonValue -match '[\x00-\x20\x7F]' -or
        $knownPublicValues -ccontains $comparisonValue
    ) {
        $needsReplacement = $true
    }
}

$temporaryFile = $null
$sessionSecret = $null
try {
    if (-not $needsReplacement) {
        if ($PSCmdlet.ShouldProcess($environmentFile, "tighten and verify its private ACL")) {
            Set-PrivatePathAcl -LiteralPath $environmentFile
            Test-PrivatePathAcl -LiteralPath $environmentFile
            Write-Host "Local session secret is already configured; its private ACL was verified."
        }
        return
    }

    $action = if ($Rotate) {
        "rotate its session secret and atomically replace the protected file"
    }
    else {
        "add a random session secret and atomically replace the protected file"
    }
    if (-not $PSCmdlet.ShouldProcess($environmentFile, $action)) {
        return
    }

    $sessionSecret = New-RandomSessionSecret
    if ($sessionEntries.Count -eq 1) {
        $entry = $sessionEntries[0]
        $replacement = "APP_SESSION_SECRET=$sessionSecret"
        $updatedContent = $environmentContent.Substring(0, $entry.Index) +
            $replacement +
            $environmentContent.Substring($entry.Index + $entry.Length)
    }
    else {
        $lineEnding = if ($environmentContent.Contains("`r`n")) { "`r`n" } else { "`n" }
        $logLevelEntry = [regex]::Match(
            $environmentContent,
            '(?im)^[ \t]*APP_LOG_LEVEL=[^\r\n]*'
        )
        if ($logLevelEntry.Success) {
            $insertionIndex = $logLevelEntry.Index + $logLevelEntry.Length
            $updatedContent = $environmentContent.Substring(0, $insertionIndex) +
                $lineEnding +
                "APP_SESSION_SECRET=$sessionSecret" +
                $environmentContent.Substring($insertionIndex)
        }
        else {
            $updatedContent = "APP_SESSION_SECRET=$sessionSecret$lineEnding" +
                $environmentContent
        }
    }

    $temporaryFile = Join-Path (
        Split-Path -Parent $environmentFile
    ) (".env.session-secret-" + [guid]::NewGuid().ToString("N") + ".tmp")
    $temporaryFile = [IO.Path]::GetFullPath($temporaryFile)
    if (-not (Split-Path -Parent $temporaryFile).Equals(
        $repositoryRoot,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Temporary environment file resolved outside the repository root."
    }

    [IO.File]::WriteAllText($temporaryFile, $updatedContent, $utf8)
    Set-PrivatePathAcl -LiteralPath $temporaryFile
    Test-PrivatePathAcl -LiteralPath $temporaryFile
    [IO.File]::Move($temporaryFile, $environmentFile, $true)
    $temporaryFile = $null
    Set-PrivatePathAcl -LiteralPath $environmentFile
    Test-PrivatePathAcl -LiteralPath $environmentFile

    Write-Host (
        "Local session secret was updated without being displayed. " +
        "Unused pre-authentication CSRF tokens issued with the previous secret become invalid " +
        "when the application loads this value. " +
        "Existing database-backed login sessions remain valid; revoke them separately only when authorized."
    )
}
finally {
    $sessionSecret = $null
    $environmentContent = $null
    $updatedContent = $null
    if ($null -ne $temporaryFile -and (Test-Path -LiteralPath $temporaryFile)) {
        Remove-Item -LiteralPath $temporaryFile -Force
    }
}
