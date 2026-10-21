#Requires -Version 7.0

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$HostName = "127.0.0.1",

    [Parameter()]
    [ValidateRange(1, 65535)]
    [int]$Port = 3306,

    [Parameter()]
    [switch]$ForceEnvironmentFile,

    [Parameter()]
    [switch]$AllowExistingPrimaryDatabase,

    [Parameter()]
    [switch]$SkipApplicationAdmin
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$databaseName = "clsen_data"
$testDatabaseName = "clsen_data_test"
$migrationUser = "clsen_migrator"
$runtimeUser = "clsen_app"
$backupUser = "clsen_backup"

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$environmentFile = Join-Path $repositoryRoot ".env"
$pythonExecutable = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$alembicConfiguration = Join-Path $repositoryRoot "backend\alembic.ini"
$privilegeManifestPath = Join-Path $PSScriptRoot "database-privileges.json"
Import-Module (Join-Path $PSScriptRoot "DatabaseContract.psm1") -Force

$expectedSchemaRevision = Get-DatabaseSchemaRevision `
    -PythonExecutable $pythonExecutable `
    -BackendDirectory (Join-Path $repositoryRoot "backend")

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

function ConvertTo-MySqlStringLiteral {
    param(
        [Parameter(Mandatory)]
        [string]$Value
    )

    return $Value.Replace("\", "\\").Replace("'", "''")
}

function New-RandomSecret {
    $bytes = [byte[]]::new(32)
    try {
        [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
        return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
    }
    finally {
        [Array]::Clear($bytes, 0, $bytes.Length)
    }
}

function ConvertTo-OptionFileValue {
    param(
        [Parameter(Mandatory)]
        [string]$Value
    )

    return $Value.Replace("\", "\\").Replace('"', '\"')
}

function Assert-SafeSecretText {
    param(
        [Parameter(Mandatory)]
        [string]$Value,

        [Parameter(Mandatory)]
        [string]$Label
    )

    if ([string]::IsNullOrEmpty($Value)) {
        throw "$Label must not be empty."
    }
    if ($Value -match '[\x00-\x1F\x7F]') {
        throw "$Label must not contain control characters."
    }
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

function New-DatabaseUrl {
    param(
        [Parameter(Mandatory)]
        [string]$User,

        [Parameter(Mandatory)]
        [string]$Password,

        [Parameter(Mandatory)]
        [string]$Database
    )

    $encodedUser = [Uri]::EscapeDataString($User)
    $encodedPassword = [Uri]::EscapeDataString($Password)
    $urlHost = $connectionHost
    if ($connectionHost.Contains(":")) {
        $urlHost = "[$connectionHost]"
    }
    return "mysql+pymysql://${encodedUser}:${encodedPassword}@${urlHost}:${Port}/${Database}?charset=utf8mb4"
}

$databasePrivileges = Import-StrictDatabasePrivilegeManifest `
    -LiteralPath $privilegeManifestPath

if ([Uri]::CheckHostName($HostName) -eq [UriHostNameType]::Unknown) {
    throw "HostName must be a valid DNS name or IP address."
}
if (@("localhost", "127.0.0.1", "::1") -notcontains $HostName) {
    throw (
        "This local bootstrap script refuses remote MySQL hosts. " +
        "Use the reviewed deployment workflow for a production database."
    )
}
$connectionHost = switch ($HostName.ToLowerInvariant()) {
    "localhost" {
        Write-Verbose "Normalizing localhost to the explicit TCP loopback 127.0.0.1."
        "127.0.0.1"
    }
    "127.0.0.1" { "127.0.0.1" }
    "::1" { "::1" }
    default { throw "Unsupported local MySQL host '$HostName'." }
}
$accountHost = $connectionHost
if ($accountHost -cne $connectionHost) {
    throw "Internal error: the MySQL account host and connection host differ."
}
if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw "Virtual-environment Python was not found at '$pythonExecutable'."
}
if (-not (Test-Path -LiteralPath $alembicConfiguration -PathType Leaf)) {
    throw "Alembic configuration was not found at '$alembicConfiguration'."
}
$mysqlCommand = Get-Command -Name mysql.exe -ErrorAction SilentlyContinue
if ($null -eq $mysqlCommand) {
    throw "mysql.exe is not available on PATH."
}
if ((Test-Path -LiteralPath $environmentFile) -and -not $ForceEnvironmentFile) {
    throw "'$environmentFile' already exists. Use -ForceEnvironmentFile to replace it intentionally."
}

if (
    -not $PSCmdlet.ShouldProcess(
        "local MySQL at ${connectionHost}:$Port",
        "bootstrap databases, accounts, grants, migrations, and local configuration"
    )
) {
    return
}

# Get-Credential keeps the password as a SecureString; any future replacement
# based on Read-Host must retain -AsSecureString and confirmation semantics.
$adminCredential = Get-Credential -Message "MySQL administrator credential for local bootstrap"
if ($adminCredential.UserName -notmatch '^[A-Za-z0-9_.-]{1,64}$') {
    throw "The MySQL administrator username contains unsupported characters."
}

$temporaryRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$temporaryDirectory = [System.IO.Path]::GetFullPath(
    (Join-Path $temporaryRoot ("clsen-mysql-bootstrap-" + [guid]::NewGuid().ToString("N")))
)
if (-not $temporaryDirectory.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Temporary credential directory resolved outside the operating-system temporary root."
}

$adminPassword = $null
$migrationPassword = $null
$runtimePassword = $null
$backupPassword = $null
$sessionSecret = $null
$previousMigrationUrl = [Environment]::GetEnvironmentVariable("APP_MIGRATION_DATABASE_URL")
$previousRuntimeUrl = [Environment]::GetEnvironmentVariable("APP_DATABASE_URL")

try {
    New-Item -ItemType Directory -Path $temporaryDirectory -ErrorAction Stop | Out-Null
    Set-PrivatePathAcl -LiteralPath $temporaryDirectory -Directory

    $adminPassword = ConvertFrom-PrivateSecureString -Value $adminCredential.Password
    $migrationPassword = New-RandomSecret
    $runtimePassword = New-RandomSecret
    $backupPassword = New-RandomSecret
    $sessionSecret = New-RandomSecret
    if (
        $migrationPassword -ceq $runtimePassword -or
        $migrationPassword -ceq $backupPassword -or
        $runtimePassword -ceq $backupPassword -or
        $sessionSecret -ceq $migrationPassword -or
        $sessionSecret -ceq $runtimePassword -or
        $sessionSecret -ceq $backupPassword
    ) {
        throw "The cryptographic random generator returned duplicate secrets."
    }
    Assert-SafeSecretText -Value $adminPassword -Label "MySQL administrator password"
    Assert-SafeSecretText -Value $migrationPassword -Label "$migrationUser password"
    Assert-SafeSecretText -Value $runtimePassword -Label "$runtimeUser password"
    Assert-SafeSecretText -Value $backupPassword -Label "$backupUser password"
    Assert-SafeSecretText -Value $sessionSecret -Label "application session secret"

    $optionFile = Join-Path $temporaryDirectory "admin.cnf"
    $optionContent = @"
[client]
user="$(ConvertTo-OptionFileValue -Value $adminCredential.UserName)"
password="$(ConvertTo-OptionFileValue -Value $adminPassword)"
host=$connectionHost
port=$Port
default-character-set=utf8mb4
"@
    [System.IO.File]::WriteAllText($optionFile, $optionContent, [Text.UTF8Encoding]::new($false))
    Set-PrivatePathAcl -LiteralPath $optionFile

    function Invoke-MySqlAdministratorSql {
        param(
            [Parameter(Mandatory)]
            [string]$Sql,

            [Parameter(Mandatory)]
            [string]$Name
        )

        $sqlFile = Join-Path $temporaryDirectory ("$Name.sql")
        $sessionSql = @"
SET SESSION time_zone = '+00:00';
SET SESSION sql_mode = TRIM(
    BOTH ',' FROM REPLACE(
        CONCAT(',', @@SESSION.sql_mode, ','),
        ',NO_BACKSLASH_ESCAPES,',
        ','
    )
);
$Sql
"@
        [System.IO.File]::WriteAllText(
            $sqlFile,
            $sessionSql,
            [Text.UTF8Encoding]::new($false)
        )
        Set-PrivatePathAcl -LiteralPath $sqlFile
        try {
            $commandOutput = Get-Content -Raw -LiteralPath $sqlFile |
                & $mysqlCommand.Source `
                    "--defaults-extra-file=$optionFile" `
                    "--protocol=TCP" `
                    "--batch" `
                    "--raw" `
                    "--skip-column-names"
            if ($LASTEXITCODE -ne 0) {
                throw "mysql.exe failed while executing '$Name' with exit code $LASTEXITCODE."
            }
            return $commandOutput
        }
        finally {
            Remove-Item -LiteralPath $sqlFile -Force -ErrorAction SilentlyContinue
        }
    }

    if (-not $AllowExistingPrimaryDatabase) {
        $existingPrimaryOutput = Invoke-MySqlAdministratorSql `
            -Sql (
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.SCHEMATA " +
                "WHERE SCHEMA_NAME = '$databaseName';"
            ) `
            -Name "check-primary-database"
        $existingPrimaryCount = [int](($existingPrimaryOutput -join "").Trim())
        if ($existingPrimaryCount -ne 0) {
            throw (
                "Primary database '$databaseName' already exists. " +
                "Re-run with -AllowExistingPrimaryDatabase only after verifying " +
                "that this is the intended local development database."
            )
        }
    }

    $ambiguousAccountHostsOutput = Invoke-MySqlAdministratorSql `
        -Sql @"
SELECT COUNT(*)
FROM mysql.user
WHERE User IN ('$migrationUser', '$runtimeUser', '$backupUser')
  AND Host <> '$accountHost';
"@ `
        -Name "check-database-account-hosts"
    $ambiguousAccountHosts = [int](($ambiguousAccountHostsOutput -join "").Trim())
    if ($ambiguousAccountHosts -ne 0) {
        throw (
            "Dedicated CLSEN database accounts exist for another host. " +
            "Review and remove those ambiguous accounts before bootstrap so " +
            "the TCP connection cannot match a different privilege set."
        )
    }

    $existingRoleAssignmentsOutput = Invoke-MySqlAdministratorSql `
        -Sql @"
SELECT COUNT(*)
FROM mysql.role_edges
WHERE (TO_USER = '$migrationUser' AND TO_HOST = '$accountHost')
   OR (TO_USER = '$runtimeUser' AND TO_HOST = '$accountHost')
   OR (TO_USER = '$backupUser' AND TO_HOST = '$accountHost');
"@ `
        -Name "check-database-account-roles"
    $existingRoleAssignments = [int](
        ($existingRoleAssignmentsOutput -join "").Trim()
    )
    if ($existingRoleAssignments -ne 0) {
        throw (
            "Dedicated CLSEN database accounts have role assignments. " +
            "Remove and review those roles before bootstrap; direct grants alone " +
            "cannot guarantee least privilege while roles remain."
        )
    }

    $existingProxyGrantsOutput = Invoke-MySqlAdministratorSql `
        -Sql @"
SELECT COUNT(*)
FROM mysql.proxies_priv
WHERE User IN ('$migrationUser', '$runtimeUser', '$backupUser')
  AND Host = '$accountHost';
"@ `
        -Name "check-database-account-proxies"
    $existingProxyGrants = [int](($existingProxyGrantsOutput -join "").Trim())
    if ($existingProxyGrants -ne 0) {
        throw (
            "Dedicated CLSEN database accounts have proxy grants. " +
            "Remove and review those grants before bootstrap; REVOKE ALL does " +
            "not clear proxy impersonation privileges."
        )
    }

    $migrationPasswordSql = ConvertTo-MySqlStringLiteral -Value $migrationPassword
    $runtimePasswordSql = ConvertTo-MySqlStringLiteral -Value $runtimePassword
    $backupPasswordSql = ConvertTo-MySqlStringLiteral -Value $backupPassword
    $backupSchemaPrivilegeList = (
        [string[]]$databasePrivileges["backup"]["schema"]
    ) -join ", "
    $bootstrapSql = @"
SET PERSIST log_bin_trust_function_creators = ON;

CREATE DATABASE IF NOT EXISTS ``$databaseName`` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
ALTER DATABASE ``$databaseName`` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS ``$testDatabaseName`` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
ALTER DATABASE ``$testDatabaseName`` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS '$migrationUser'@'$accountHost' IDENTIFIED WITH caching_sha2_password BY '$migrationPasswordSql';
ALTER USER '$migrationUser'@'$accountHost' IDENTIFIED WITH caching_sha2_password BY '$migrationPasswordSql';
CREATE USER IF NOT EXISTS '$runtimeUser'@'$accountHost' IDENTIFIED WITH caching_sha2_password BY '$runtimePasswordSql';
ALTER USER '$runtimeUser'@'$accountHost' IDENTIFIED WITH caching_sha2_password BY '$runtimePasswordSql';
CREATE USER IF NOT EXISTS '$backupUser'@'$accountHost' IDENTIFIED WITH caching_sha2_password BY '$backupPasswordSql';
ALTER USER '$backupUser'@'$accountHost' IDENTIFIED WITH caching_sha2_password BY '$backupPasswordSql';

REVOKE IF EXISTS ALL PRIVILEGES, GRANT OPTION FROM '$migrationUser'@'$accountHost';
REVOKE IF EXISTS ALL PRIVILEGES, GRANT OPTION FROM '$runtimeUser'@'$accountHost';
REVOKE IF EXISTS ALL PRIVILEGES, GRANT OPTION FROM '$backupUser'@'$accountHost';
SET DEFAULT ROLE NONE TO '$migrationUser'@'$accountHost';
SET DEFAULT ROLE NONE TO '$runtimeUser'@'$accountHost';
SET DEFAULT ROLE NONE TO '$backupUser'@'$accountHost';

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES, TRIGGER
    ON ``$databaseName``.* TO '$migrationUser'@'$accountHost';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES, TRIGGER
    ON ``$testDatabaseName``.* TO '$migrationUser'@'$accountHost';
GRANT SELECT ON ``$databaseName``.* TO '$runtimeUser'@'$accountHost';
GRANT SELECT ON ``$testDatabaseName``.* TO '$runtimeUser'@'$accountHost';
GRANT $backupSchemaPrivilegeList
    ON ``$databaseName``.* TO '$backupUser'@'$accountHost';
GRANT $backupSchemaPrivilegeList
    ON ``$testDatabaseName``.* TO '$backupUser'@'$accountHost';
"@

    Invoke-MySqlAdministratorSql -Sql $bootstrapSql -Name "bootstrap" | Out-Null

    $triggerTrustOutput = Invoke-MySqlAdministratorSql `
        -Sql "SELECT @@GLOBAL.log_bin_trust_function_creators;" `
        -Name "verify-trigger-creation-policy"
    $triggerTrustEnabled = [int](($triggerTrustOutput -join "").Trim())
    if ($triggerTrustEnabled -ne 1) {
        throw (
            "MySQL did not retain log_bin_trust_function_creators=ON; " +
            "the least-privilege migration account cannot create required triggers."
        )
    }

    $migrationUrl = New-DatabaseUrl -User $migrationUser -Password $migrationPassword -Database $databaseName
    $runtimeUrl = New-DatabaseUrl -User $runtimeUser -Password $runtimePassword -Database $databaseName
    $backupUrl = New-DatabaseUrl -User $backupUser -Password $backupPassword -Database $databaseName
    $testMigrationUrl = New-DatabaseUrl -User $migrationUser -Password $migrationPassword -Database $testDatabaseName
    $testRuntimeUrl = New-DatabaseUrl -User $runtimeUser -Password $runtimePassword -Database $testDatabaseName
    $testBackupUrl = New-DatabaseUrl -User $backupUser -Password $backupPassword -Database $testDatabaseName
    $storageRoot = [IO.Path]::GetFullPath(
        (Join-Path -Path $repositoryRoot -ChildPath "data\raw")
    )
    $storageRootEnvironmentValue = $storageRoot.Replace('\', '/')

    if (Test-Path -LiteralPath $storageRoot) {
        if (-not (Test-Path -LiteralPath $storageRoot -PathType Container)) {
            throw "Storage root exists but is not a directory."
        }
        $storageRootItem = Get-Item -LiteralPath $storageRoot -Force
        if (
            ($storageRootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
        ) {
            throw "Storage root must not be a reparse point."
        }
    }
    else {
        [IO.Directory]::CreateDirectory($storageRoot) | Out-Null
    }
    Set-PrivatePathAcl -LiteralPath $storageRoot -Directory

    $environmentContent = @"
APP_ENVIRONMENT=development
APP_LOG_LEVEL=INFO
APP_SESSION_SECRET=$sessionSecret
APP_CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
APP_STORAGE_ROOT=$storageRootEnvironmentValue
APP_STORAGE_MAX_UPLOAD_BYTES=104857600
APP_STORAGE_LEASE_TTL_SECONDS=900
APP_STORAGE_LEASE_RENEW_INTERVAL_SECONDS=300
APP_STORAGE_ORPHAN_AGE_SECONDS=86400
APP_DATABASE_URL=$runtimeUrl
APP_MIGRATION_DATABASE_URL=$migrationUrl
APP_BACKUP_DATABASE_URL=$backupUrl
APP_TEST_DATABASE_URL=$testMigrationUrl
APP_TEST_RUNTIME_DATABASE_URL=$testRuntimeUrl
APP_TEST_BACKUP_DATABASE_URL=$testBackupUrl
"@

    $migrationTargets = @(
        [pscustomobject]@{ Database = $databaseName; Url = $migrationUrl },
        [pscustomobject]@{ Database = $testDatabaseName; Url = $testMigrationUrl }
    )
    foreach ($migrationTarget in $migrationTargets) {
        [Environment]::SetEnvironmentVariable(
            "APP_MIGRATION_DATABASE_URL",
            $migrationTarget.Url
        )
        & $pythonExecutable -m alembic -c $alembicConfiguration upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw (
                "Alembic failed for database '$($migrationTarget.Database)' " +
                "with exit code $LASTEXITCODE."
            )
        }

        $actualSchemaRevision = (
            Invoke-MySqlAdministratorSql `
                -Sql (
                    "SELECT version_num FROM ``$($migrationTarget.Database)``." +
                    "``alembic_version``;"
                ) `
                -Name "verify-$($migrationTarget.Database)-schema-revision"
        ) -join ""
        if ($actualSchemaRevision.Trim() -cne $expectedSchemaRevision) {
            throw (
                "Database '$($migrationTarget.Database)' is at schema revision " +
                "'$($actualSchemaRevision.Trim())'; expected " +
                "'$expectedSchemaRevision'."
            )
        }

        $lockCoverageOutput = Invoke-MySqlAdministratorSql `
            -Sql @"
SELECT
    (SELECT COUNT(*) FROM ``$($migrationTarget.Database)``.``daily_datasets``),
    (SELECT COUNT(*) FROM ``$($migrationTarget.Database)``.``daily_dataset_locks``),
    (
        SELECT COUNT(*)
        FROM ``$($migrationTarget.Database)``.``daily_datasets`` AS datasets
        LEFT JOIN ``$($migrationTarget.Database)``.``daily_dataset_locks`` AS locks
            ON locks.dataset_id = datasets.id
        WHERE locks.dataset_id IS NULL
    ),
    (
        SELECT COUNT(*)
        FROM ``$($migrationTarget.Database)``.``daily_dataset_locks`` AS locks
        LEFT JOIN ``$($migrationTarget.Database)``.``daily_datasets`` AS datasets
            ON datasets.id = locks.dataset_id
        WHERE datasets.id IS NULL
    );
"@ `
            -Name "verify-$($migrationTarget.Database)-dataset-lock-coverage"
        $lockCoverageValues = (
            ($lockCoverageOutput -join "").Trim() -split "`t"
        )
        if ($lockCoverageValues.Count -ne 4) {
            throw (
                "Dataset lock coverage verification returned an unexpected " +
                "result for database '$($migrationTarget.Database)'."
            )
        }
        $datasetCount = [long]$lockCoverageValues[0]
        $lockCount = [long]$lockCoverageValues[1]
        $missingLockCount = [long]$lockCoverageValues[2]
        $orphanLockCount = [long]$lockCoverageValues[3]
        if (
            $datasetCount -ne $lockCount -or
            $missingLockCount -ne 0 -or
            $orphanLockCount -ne 0
        ) {
            throw (
                "Dataset lock coverage verification failed for database " +
                "'$($migrationTarget.Database)': datasets=$datasetCount, " +
                "locks=$lockCount, missing=$missingLockCount, " +
                "orphaned=$orphanLockCount."
            )
        }
    }

    $runtimePrivileges = $databasePrivileges["runtime"]
    $insertOnlyTables = [string[]]$runtimePrivileges["insert_only"]
    $mutableInsertTables = [string[]]$runtimePrivileges["mutable_insert"]
    $updateTables = [string[]]$runtimePrivileges["update"]
    $columnUpdates = $runtimePrivileges["update_columns"]
    $deleteTables = [string[]]$runtimePrivileges["delete"]

    $grantStatements = [Collections.Generic.List[string]]::new()
    foreach ($database in @($databaseName, $testDatabaseName)) {
        foreach ($table in ($insertOnlyTables + $mutableInsertTables)) {
            $grantStatements.Add("GRANT INSERT ON ``$database``.``$table`` TO '$runtimeUser'@'$accountHost';")
        }
        foreach ($table in $updateTables) {
            $grantStatements.Add("GRANT UPDATE ON ``$database``.``$table`` TO '$runtimeUser'@'$accountHost';")
        }
        foreach ($table in $columnUpdates.Keys) {
            $columns = [string[]]$columnUpdates[$table]
            $columnList = ($columns | ForEach-Object { "``$_``" }) -join ", "
            $grantStatements.Add("GRANT UPDATE ($columnList) ON ``$database``.``$table`` TO '$runtimeUser'@'$accountHost';")
        }
        foreach ($table in $deleteTables) {
            $grantStatements.Add("GRANT DELETE ON ``$database``.``$table`` TO '$runtimeUser'@'$accountHost';")
        }
    }
    Invoke-MySqlAdministratorSql `
        -Sql ($grantStatements -join "`n") `
        -Name "runtime-grants" |
        Out-Null

    $backupPrivileges = $databasePrivileges["backup"]
    $backupGrantStatements = [Collections.Generic.List[string]]::new()
    foreach ($database in @($databaseName, $testDatabaseName)) {
        foreach ($table in [string[]]$backupPrivileges["insert"]) {
            $backupGrantStatements.Add(
                "GRANT INSERT ON ``$database``.``$table`` TO '$backupUser'@'$accountHost';"
            )
        }
        foreach ($table in [string[]]$backupPrivileges["update"]) {
            $backupGrantStatements.Add(
                "GRANT UPDATE ON ``$database``.``$table`` TO '$backupUser'@'$accountHost';"
            )
        }
    }
    Invoke-MySqlAdministratorSql `
        -Sql ($backupGrantStatements -join "`n") `
        -Name "backup-audit-grants" |
        Out-Null

    [System.IO.File]::WriteAllText(
        $environmentFile,
        $environmentContent,
        [Text.UTF8Encoding]::new($false)
    )
    Set-PrivatePathAcl -LiteralPath $environmentFile

    if (-not $SkipApplicationAdmin) {
        $existingApplicationAdminOutput = Invoke-MySqlAdministratorSql `
            -Sql @"
SELECT COUNT(*)
FROM ``$databaseName``.``user_roles`` AS ur
INNER JOIN ``$databaseName``.``roles`` AS r ON r.id = ur.role_id
WHERE r.code = 'admin';
"@ `
            -Name "check-application-admin"
        $existingApplicationAdmin = [int](
            ($existingApplicationAdminOutput -join "").Trim()
        )
        if ($existingApplicationAdmin -eq 0) {
            $applicationUsername = Read-Host "Initial application administrator username"
            if (
                [string]::IsNullOrWhiteSpace($applicationUsername) -or
                $applicationUsername -match '[\x00-\x1F\x7F]'
            ) {
                throw "Application administrator username must be non-blank and contain no control characters."
            }
            [Environment]::SetEnvironmentVariable("APP_DATABASE_URL", $runtimeUrl)
            & $pythonExecutable -m app.cli create-admin "--username=$applicationUsername"
            if ($LASTEXITCODE -ne 0) {
                throw "Application administrator creation failed with exit code $LASTEXITCODE."
            }
        }
        else {
            Write-Verbose "An application administrator already exists; creation was skipped."
        }
    }

    Write-Host "Database bootstrap completed. Secrets were written only to the protected .env file."
}
finally {
    if ($null -eq $previousMigrationUrl) {
        [Environment]::SetEnvironmentVariable("APP_MIGRATION_DATABASE_URL", $null)
    }
    else {
        [Environment]::SetEnvironmentVariable("APP_MIGRATION_DATABASE_URL", $previousMigrationUrl)
    }
    if ($null -eq $previousRuntimeUrl) {
        [Environment]::SetEnvironmentVariable("APP_DATABASE_URL", $null)
    }
    else {
        [Environment]::SetEnvironmentVariable("APP_DATABASE_URL", $previousRuntimeUrl)
    }

    $adminPassword = $null
    $migrationPassword = $null
    $runtimePassword = $null
    $backupPassword = $null
    $sessionSecret = $null
    $environmentContent = $null
    $migrationUrl = $null
    $runtimeUrl = $null
    $backupUrl = $null
    $testMigrationUrl = $null
    $testRuntimeUrl = $null
    $testBackupUrl = $null
    $migrationTargets = $null

    if (Test-Path -LiteralPath $temporaryDirectory) {
        $resolvedTemporaryDirectory = [System.IO.Path]::GetFullPath($temporaryDirectory)
        $temporaryLeaf = Split-Path -Leaf $resolvedTemporaryDirectory
        if (
            $resolvedTemporaryDirectory.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -and
            $temporaryLeaf -like "clsen-mysql-bootstrap-*"
        ) {
            Remove-Item -LiteralPath $resolvedTemporaryDirectory -Recurse -Force
        }
        else {
            Write-Warning "Refused to remove unexpected temporary path '$resolvedTemporaryDirectory'."
        }
    }
}
