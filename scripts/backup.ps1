#Requires -Version 7.0

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$Destination = ".\data\backups",

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$StorageRoot,

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$KeyringPath,

    [Parameter()]
    [ValidateSet("Backup", "InitializeKeyring", "RotateKey")]
    [string]$Action = "Backup",

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$KeyId,

    [Parameter()]
    [switch]$UseTestDatabase,

    [Parameter()]
    [ValidateRange(0, 300)]
    [int]$LockTimeoutSeconds = 30,

    [Parameter()]
    [ValidateRange(0, 3600)]
    [int]$LeaseWaitTimeoutSeconds = 300,

    [Parameter()]
    [ValidateRange(1, 3650)]
    [int]$RetentionCount = 30
)

$ErrorActionPreference = "Stop"
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$pythonExecutable = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$backendDirectory = Join-Path $repositoryRoot "backend"

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

function Assert-SafeNonRootPath {
    param(
        [Parameter(Mandatory)]
        [string]$LiteralPath,

        [Parameter(Mandatory)]
        [string]$Label
    )

    $resolved = [IO.Path]::GetFullPath($LiteralPath)
    $root = [IO.Path]::GetPathRoot($resolved)
    if ($resolved -eq $root -or $resolved -eq $repositoryRoot) {
        throw "$Label must not be a filesystem root or the repository root."
    }
    return $resolved
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

if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw "Project Python was not found at '$pythonExecutable'."
}

$destinationPath = Assert-SafeNonRootPath `
    -LiteralPath (Resolve-RepositoryRelativePath -Value $Destination) `
    -Label "Backup destination"
$storageRootOverride = $null
if (-not [string]::IsNullOrWhiteSpace($StorageRoot)) {
    $storageRootOverride = Assert-SafeNonRootPath `
        -LiteralPath (Resolve-RepositoryRelativePath -Value $StorageRoot) `
        -Label "Backup storage root"
    if (-not (Test-Path -LiteralPath $storageRootOverride -PathType Container)) {
        throw "Backup storage root does not exist."
    }
}

if ([string]::IsNullOrWhiteSpace($KeyringPath)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA is required when -KeyringPath is omitted."
    }
    $KeyringPath = Join-Path $env:LOCALAPPDATA "CLSEN\DataWeb\backup-keyring.json"
}
$resolvedKeyringPath = Assert-SafeNonRootPath `
    -LiteralPath $KeyringPath `
    -Label "Backup keyring"
$repositoryPrefix = $repositoryRoot.TrimEnd('\') + '\'
if ($resolvedKeyringPath.StartsWith(
    $repositoryPrefix,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "The backup keyring must remain outside the repository."
}

$keyringDirectory = Split-Path -Parent $resolvedKeyringPath
if (-not (Test-Path -LiteralPath $keyringDirectory)) {
    New-Item -ItemType Directory -Path $keyringDirectory -Force | Out-Null
}
Set-PrivatePathAcl -LiteralPath $keyringDirectory -Directory

if ($Action -in @("InitializeKeyring", "RotateKey")) {
    if ([string]::IsNullOrWhiteSpace($KeyId)) {
        $KeyId = "local-" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    }
    $command = if ($Action -eq "InitializeKeyring") {
        "keyring-init"
    }
    else {
        "keyring-rotate"
    }
    if ($PSCmdlet.ShouldProcess($resolvedKeyringPath, $Action)) {
        Push-Location -LiteralPath $backendDirectory
        try {
            & $pythonExecutable `
                -m app.maintenance.cli `
                $command `
                --path $resolvedKeyringPath `
                --key-id $KeyId
            if ($LASTEXITCODE -ne 0) {
                throw "Backup keyring operation failed with exit code $LASTEXITCODE."
            }
        }
        finally {
            Pop-Location
        }
        Set-PrivatePathAcl -LiteralPath $resolvedKeyringPath
    }
    return
}

if (-not (Test-Path -LiteralPath $resolvedKeyringPath -PathType Leaf)) {
    throw (
        "Backup keyring does not exist. Initialize it once with: " +
        ".\scripts\backup.ps1 -Action InitializeKeyring"
    )
}
Set-PrivatePathAcl -LiteralPath $resolvedKeyringPath
if (-not (Test-Path -LiteralPath $destinationPath)) {
    New-Item -ItemType Directory -Path $destinationPath -Force | Out-Null
}
Set-PrivatePathAcl -LiteralPath $destinationPath -Directory

$databaseEnvironment = if ($UseTestDatabase) {
    "APP_TEST_BACKUP_DATABASE_URL"
}
else {
    "APP_BACKUP_DATABASE_URL"
}
if ($PSCmdlet.ShouldProcess($destinationPath, "Create encrypted database and object backup")) {
    $previousStorageRoot = [Environment]::GetEnvironmentVariable(
        "APP_STORAGE_ROOT",
        [EnvironmentVariableTarget]::Process
    )
    try {
        if ($null -ne $storageRootOverride) {
            [Environment]::SetEnvironmentVariable(
                "APP_STORAGE_ROOT",
                $storageRootOverride,
                [EnvironmentVariableTarget]::Process
            )
        }
        Push-Location -LiteralPath $backendDirectory
        try {
            & $pythonExecutable `
                -m app.maintenance.cli `
                backup `
                --destination $destinationPath `
                --keyring $resolvedKeyringPath `
                --database-environment $databaseEnvironment `
                --lock-timeout $LockTimeoutSeconds `
                --lease-wait-timeout $LeaseWaitTimeoutSeconds `
                --retention-count $RetentionCount
            if ($LASTEXITCODE -ne 0) {
                throw "Encrypted backup failed with exit code $LASTEXITCODE."
            }
        }
        finally {
            Pop-Location
        }
    }
    finally {
        if ($null -ne $storageRootOverride) {
            [Environment]::SetEnvironmentVariable(
                "APP_STORAGE_ROOT",
                $previousStorageRoot,
                [EnvironmentVariableTarget]::Process
            )
        }
    }
}
