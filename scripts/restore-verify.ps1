#Requires -Version 7.0

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$BackupRoot = ".\data\backups",

    [Parameter()]
    [ValidatePattern('\A[0-9a-f]{32}\z')]
    [string]$BackupId,

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$TemporaryRoot = ".\data\restore-tests",

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$KeyringPath,

    [Parameter()]
    [switch]$UseTestDatabase,

    [Parameter()]
    [switch]$Cleanup
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$pythonExecutable = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$backendDirectory = Join-Path $repositoryRoot "backend"

function ConvertFrom-PrivateSecureString {
    param(
        [Parameter(Mandatory)]
        [Security.SecureString]$Value
    )

    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function ConvertTo-OptionFileValue {
    param(
        [Parameter(Mandatory)]
        [string]$Value
    )

    if ([string]::IsNullOrEmpty($Value) -or $Value -match '[\x00-\x1F\x7F]') {
        throw "MySQL option value is empty or contains control characters."
    }
    return $Value.Replace("\", "\\").Replace('"', '\"')
}

function Set-PrivatePathAcl {
    param(
        [Parameter(Mandatory)]
        [string]$LiteralPath,

        [Parameter()]
        [switch]$Directory
    )

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ($Directory) {
        $acl = [Security.AccessControl.DirectorySecurity]::new()
        $inheritance = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
    }
    else {
        $acl = [Security.AccessControl.FileSecurity]::new()
        $inheritance = [Security.AccessControl.InheritanceFlags]::None
    }
    $acl.SetAccessRuleProtection($true, $false)
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        $identity,
        [Security.AccessControl.FileSystemRights]::FullControl,
        $inheritance,
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow
    )
    $acl.AddAccessRule($rule)
    $pathInfo = if ($Directory) {
        [IO.DirectoryInfo]::new($LiteralPath)
    }
    else {
        [IO.FileInfo]::new($LiteralPath)
    }
    [IO.FileSystemAclExtensions]::SetAccessControl($pathInfo, $acl)
}

function Resolve-RepositoryRelativePath {
    param(
        [Parameter(Mandatory)]
        [string]$Value
    )

    if ([IO.Path]::IsPathFullyQualified($Value)) {
        return [IO.Path]::GetFullPath($Value)
    }
    return [IO.Path]::GetFullPath((Join-Path $repositoryRoot $Value))
}

function Assert-SafeNonRootPath {
    param(
        [Parameter(Mandatory)]
        [string]$LiteralPath,

        [Parameter(Mandatory)]
        [string]$Label
    )

    $resolved = [IO.Path]::GetFullPath($LiteralPath)
    if ($resolved -eq [IO.Path]::GetPathRoot($resolved) -or $resolved -eq $repositoryRoot) {
        throw "$Label must not be a filesystem root or the repository root."
    }
    return $resolved
}

if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw "Project Python was not found at '$pythonExecutable'."
}
$mysqlCommand = Get-Command -Name mysql.exe -ErrorAction SilentlyContinue
if ($null -eq $mysqlCommand) {
    throw "mysql.exe is not available on PATH."
}

$resolvedBackupRoot = Assert-SafeNonRootPath `
    -LiteralPath (Resolve-RepositoryRelativePath -Value $BackupRoot) `
    -Label "Backup root"
if (-not (Test-Path -LiteralPath $resolvedBackupRoot -PathType Container)) {
    throw "Backup root does not exist."
}
if ($BackupId) {
    $backupDirectory = Join-Path $resolvedBackupRoot $BackupId
    if (-not (Test-Path -LiteralPath $backupDirectory -PathType Container)) {
        throw "Requested backup ID was not found."
    }
}
else {
    $candidate = Get-ChildItem -LiteralPath $resolvedBackupRoot -Directory |
        Where-Object {
            $_.Name -cmatch '\A[0-9a-f]{32}\z' -and
            (Test-Path -LiteralPath (Join-Path $_.FullName "backup.json") -PathType Leaf)
        } |
        Sort-Object -Property LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $candidate) {
        throw "No verified backup directory was found under the backup root."
    }
    $backupDirectory = $candidate.FullName
}
$backupDirectory = [IO.Path]::GetFullPath($backupDirectory)
if (-not $backupDirectory.StartsWith(
    $resolvedBackupRoot.TrimEnd('\') + '\',
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Selected backup directory escaped the backup root."
}

$resolvedTemporaryRoot = Assert-SafeNonRootPath `
    -LiteralPath (Resolve-RepositoryRelativePath -Value $TemporaryRoot) `
    -Label "Temporary restore root"
if ($resolvedTemporaryRoot -eq $resolvedBackupRoot) {
    throw "Temporary restore root must differ from the backup root."
}
if (-not (Test-Path -LiteralPath $resolvedTemporaryRoot)) {
    New-Item -ItemType Directory -Path $resolvedTemporaryRoot -Force | Out-Null
}
Set-PrivatePathAcl -LiteralPath $resolvedTemporaryRoot -Directory

if ([string]::IsNullOrWhiteSpace($KeyringPath)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA is required when -KeyringPath is omitted."
    }
    $KeyringPath = Join-Path $env:LOCALAPPDATA "CLSEN\DataWeb\backup-keyring.json"
}
$resolvedKeyringPath = Assert-SafeNonRootPath `
    -LiteralPath $KeyringPath `
    -Label "Backup keyring"
if (-not (Test-Path -LiteralPath $resolvedKeyringPath -PathType Leaf)) {
    throw "Backup keyring does not exist."
}
$repositoryPrefix = $repositoryRoot.TrimEnd('\') + '\'
if ($resolvedKeyringPath.StartsWith(
    $repositoryPrefix,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "The backup keyring must remain outside the repository."
}
Set-PrivatePathAcl -LiteralPath $resolvedKeyringPath

if (-not $PSCmdlet.ShouldProcess(
    $backupDirectory,
    "Restore into a new random clsen_restore_<uuid> database and isolated directory"
)) {
    return
}

$credential = Get-Credential `
    -Message "MySQL administrator credential for isolated restore verification"
if ($credential.UserName -notmatch '^[A-Za-z0-9_.-]{1,64}$') {
    throw "The MySQL administrator username contains unsupported characters."
}
$temporaryCredentialRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$temporaryCredentialDirectory = [IO.Path]::GetFullPath(
    (Join-Path `
        $temporaryCredentialRoot `
        ("clsen-restore-credential-" + [guid]::NewGuid().ToString("N")))
)
if (-not $temporaryCredentialDirectory.StartsWith(
    $temporaryCredentialRoot,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Temporary credential directory escaped the system temp root."
}

$administratorPassword = $null
try {
    New-Item -ItemType Directory -Path $temporaryCredentialDirectory | Out-Null
    Set-PrivatePathAcl -LiteralPath $temporaryCredentialDirectory -Directory
    $administratorPassword = ConvertFrom-PrivateSecureString -Value $credential.Password
    $optionFile = Join-Path $temporaryCredentialDirectory "administrator.cnf"
    $optionContent = @"
[client]
user="$(ConvertTo-OptionFileValue -Value $credential.UserName)"
password="$(ConvertTo-OptionFileValue -Value $administratorPassword)"
host=127.0.0.1
port=3306
protocol=TCP
default-character-set=utf8mb4
"@
    [IO.File]::WriteAllText(
        $optionFile,
        $optionContent,
        [Text.UTF8Encoding]::new($false)
    )
    Set-PrivatePathAcl -LiteralPath $optionFile

    $sourceDatabaseEnvironment = if ($UseTestDatabase) {
        "APP_TEST_BACKUP_DATABASE_URL"
    }
    else {
        "APP_BACKUP_DATABASE_URL"
    }
    $arguments = @(
        "-m", "app.maintenance.cli",
        "restore-verify",
        "--backup-directory", $backupDirectory,
        "--temporary-root", $resolvedTemporaryRoot,
        "--keyring", $resolvedKeyringPath,
        "--administrator-option-file", $optionFile,
        "--source-database-environment", $sourceDatabaseEnvironment,
        "--mysql", $mysqlCommand.Source
    )
    if ($Cleanup) {
        $arguments += "--cleanup"
    }
    Push-Location -LiteralPath $backendDirectory
    try {
        & $pythonExecutable @arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Isolated restore verification failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    $administratorPassword = $null
    $resolvedCredentialDirectory = [IO.Path]::GetFullPath(
        $temporaryCredentialDirectory
    )
    $expectedCredentialPrefix = [IO.Path]::GetFullPath(
        (Join-Path $temporaryCredentialRoot "clsen-restore-credential-")
    )
    if (
        $resolvedCredentialDirectory.StartsWith(
            $expectedCredentialPrefix,
            [StringComparison]::OrdinalIgnoreCase
        ) -and
        (Test-Path -LiteralPath $resolvedCredentialDirectory)
    ) {
        Remove-Item `
            -LiteralPath $resolvedCredentialDirectory `
            -Recurse `
            -Force `
            -ErrorAction SilentlyContinue
    }
}
