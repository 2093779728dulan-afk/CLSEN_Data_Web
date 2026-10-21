#Requires -Version 7.0

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$DatabaseName = "clsen_data_test",

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$RuntimeUser = "clsen_app",

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$BackupUser = "clsen_backup",

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$HostName = "127.0.0.1",

    [Parameter()]
    [ValidateRange(1, 65535)]
    [int]$Port = 3306
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$pythonExecutable = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$manifestPath = Join-Path $PSScriptRoot "database-privileges.json"
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

function ConvertTo-OptionFileValue {
    param(
        [Parameter(Mandatory)]
        [string]$Value
    )

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

function Assert-SafeIdentifier {
    param(
        [Parameter(Mandatory)]
        [string]$Value,

        [Parameter(Mandatory)]
        [string]$Label
    )

    if ($Value -cnotmatch '\A[a-z][a-z0-9_]{0,63}\z') {
        throw "$Label contains an unsafe identifier."
    }
}

function ConvertTo-OutputLines {
    param(
        [Parameter()]
        [AllowNull()]
        [object[]]$Value
    )

    return @(
        $Value |
            ForEach-Object { ([string]$_).TrimEnd() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
}

function Assert-EquivalentStringSets {
    param(
        [Parameter(Mandatory)]
        [Collections.Generic.HashSet[string]]$Expected,

        [Parameter()]
        [AllowNull()]
        [object[]]$Actual,

        [Parameter(Mandatory)]
        [string]$Label
    )

    $actualSet = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($line in (ConvertTo-OutputLines -Value $Actual)) {
        $null = $actualSet.Add($line)
    }
    if (-not $Expected.SetEquals($actualSet)) {
        $missing = @($Expected | Where-Object { -not $actualSet.Contains($_) }) |
            Sort-Object
        $unexpected = @($actualSet | Where-Object { -not $Expected.Contains($_) }) |
            Sort-Object
        throw (
            "$Label did not converge. Missing: [$($missing -join ', ')]; " +
            "unexpected: [$($unexpected -join ', ')]."
        )
    }
}

if ($DatabaseName -cnotmatch '\Aclsen_data_test(?:_[a-z0-9_]+)?\z') {
    throw (
        "This script only accepts disposable databases named " +
        "clsen_data_test or clsen_data_test_<suffix>."
    )
}
Assert-SafeIdentifier -Value $RuntimeUser -Label "Runtime user"
Assert-SafeIdentifier -Value $BackupUser -Label "Backup user"
if (@("localhost", "127.0.0.1", "::1") -notcontains $HostName) {
    throw "This local grant script refuses a non-loopback MySQL host."
}
$connectionHost = if ($HostName -eq "localhost") { "127.0.0.1" } else { $HostName }
$accountHost = $connectionHost

if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Database privilege manifest was not found at '$manifestPath'."
}
$manifest = Import-StrictDatabasePrivilegeManifest -LiteralPath $manifestPath
if ($manifest["version"] -ne 5) {
    throw "Database privilege manifest version 5 is required."
}
$runtime = $manifest["runtime"]
$expectedCategories = @(
    "insert_only",
    "mutable_insert",
    "update",
    "update_columns",
    "delete"
)
if (
    $runtime -isnot [Collections.IDictionary] -or
    $runtime.Count -ne $expectedCategories.Count
) {
    throw "Runtime privilege manifest has an unexpected shape."
}
foreach ($category in $expectedCategories) {
    if (-not $runtime.Contains($category)) {
        throw "Runtime privilege manifest is missing '$category'."
    }
}

$allTables = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::Ordinal
)
foreach ($category in @("insert_only", "mutable_insert", "update", "delete")) {
    $tables = $runtime[$category]
    if ($tables -isnot [array] -or $tables.Count -eq 0) {
        throw "Runtime privilege '$category' must be a non-empty array."
    }
    foreach ($table in $tables) {
        if ($table -isnot [string]) {
            throw "Runtime privilege '$category' contains a non-string table."
        }
        Assert-SafeIdentifier -Value $table -Label "Runtime table"
        $null = $allTables.Add($table)
    }
}
$columnUpdates = $runtime["update_columns"]
if ($columnUpdates -isnot [Collections.IDictionary] -or $columnUpdates.Count -eq 0) {
    throw "Runtime update_columns must be a non-empty object."
}
$allColumnTargets = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::Ordinal
)
foreach ($table in $columnUpdates.Keys) {
    Assert-SafeIdentifier -Value $table -Label "Column-update table"
    $null = $allTables.Add($table)
    $columns = $columnUpdates[$table]
    if ($columns -isnot [array] -or $columns.Count -eq 0) {
        throw "Column-update table '$table' has no columns."
    }
    foreach ($column in $columns) {
        if ($column -isnot [string]) {
            throw "Column-update table '$table' contains a non-string column."
        }
        Assert-SafeIdentifier -Value $column -Label "Runtime column"
        if (-not $allColumnTargets.Add("$table|$column")) {
            throw "Runtime update_columns contains a duplicate '$table.$column'."
        }
    }
}

$backup = $manifest["backup"]
if (
    $backup -isnot [Collections.IDictionary] -or
    $backup.Count -ne 3 -or
    -not $backup.Contains("schema") -or
    -not $backup.Contains("insert") -or
    -not $backup.Contains("update")
) {
    throw "Backup privilege manifest has an unexpected shape."
}
$expectedBackupSchemaPrivileges = @("SELECT", "SHOW VIEW", "TRIGGER", "EVENT")
if (
    $backup["schema"] -isnot [array] -or
    $backup["schema"].Count -ne $expectedBackupSchemaPrivileges.Count -or
    @(
        Compare-Object `
            -ReferenceObject $expectedBackupSchemaPrivileges `
            -DifferenceObject ([string[]]$backup["schema"]) `
            -CaseSensitive
    ).Count -ne 0
) {
    throw "Backup schema privileges must be SELECT, SHOW VIEW, TRIGGER, and EVENT."
}
foreach ($category in @("insert", "update")) {
    $tables = $backup[$category]
    if ($tables -isnot [array] -or $tables.Count -eq 0) {
        throw "Backup privilege '$category' must be a non-empty array."
    }
    $seenBackupTables = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($table in $tables) {
        if ($table -isnot [string]) {
            throw "Backup privilege '$category' contains a non-string table."
        }
        Assert-SafeIdentifier -Value $table -Label "Backup table"
        if (-not $seenBackupTables.Add($table)) {
            throw "Backup privilege '$category' contains duplicate table '$table'."
        }
        $null = $allTables.Add($table)
    }
}
foreach ($table in $backup["update"]) {
    if (-not ([string[]]$backup["insert"] -ccontains $table)) {
        throw "Backup UPDATE privileges must be a subset of INSERT privileges."
    }
}

$expectedBackupPrivilegeSignatures = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::Ordinal
)
foreach ($privilege in $backup["schema"]) {
    $null = $expectedBackupPrivilegeSignatures.Add("SCHEMA|$privilege|||NO")
}
foreach ($table in $backup["insert"]) {
    $null = $expectedBackupPrivilegeSignatures.Add("TABLE|INSERT|$table||NO")
}
foreach ($table in $backup["update"]) {
    $null = $expectedBackupPrivilegeSignatures.Add("TABLE|UPDATE|$table||NO")
}

$expectedPrivilegeSignatures = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::Ordinal
)
$null = $expectedPrivilegeSignatures.Add("SCHEMA|SELECT|||NO")
$insertTables = @($runtime["insert_only"] + $runtime["mutable_insert"]) |
    Sort-Object -Unique
foreach ($table in $insertTables) {
    $null = $expectedPrivilegeSignatures.Add("TABLE|INSERT|$table||NO")
}
foreach ($table in $runtime["update"]) {
    $null = $expectedPrivilegeSignatures.Add("TABLE|UPDATE|$table||NO")
}
foreach ($table in $columnUpdates.Keys) {
    foreach ($column in $columnUpdates[$table]) {
        $null = $expectedPrivilegeSignatures.Add(
            "COLUMN|UPDATE|$table|$column|NO"
        )
    }
}
foreach ($table in $runtime["delete"]) {
    $null = $expectedPrivilegeSignatures.Add("TABLE|DELETE|$table||NO")
}

$mysqlCommand = Get-Command -Name mysql.exe -ErrorAction SilentlyContinue
if ($null -eq $mysqlCommand) {
    throw "mysql.exe is not available on PATH."
}
if (
    -not $PSCmdlet.ShouldProcess(
        "'$RuntimeUser' and '$BackupUser' at '$accountHost' on $DatabaseName",
        "reconcile manifest-declared runtime and backup grants on the disposable test database"
    )
) {
    return
}

$adminCredential = Get-Credential `
    -Message "MySQL administrator credential for test-only grant synchronization"
if ($adminCredential.UserName -notmatch '^[A-Za-z0-9_.-]{1,64}$') {
    throw "The MySQL administrator username contains unsupported characters."
}

$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$temporaryDirectory = [IO.Path]::GetFullPath(
    (Join-Path $temporaryRoot ("clsen-test-grants-" + [guid]::NewGuid().ToString("N")))
)
if (-not $temporaryDirectory.StartsWith(
    $temporaryRoot,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Temporary credential directory resolved outside the system temp root."
}

$adminPassword = $null
try {
    New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null
    Set-PrivatePathAcl -LiteralPath $temporaryDirectory -Directory
    $adminPassword = ConvertFrom-PrivateSecureString -Value $adminCredential.Password
    if ([string]::IsNullOrEmpty($adminPassword) -or $adminPassword -match '[\x00-\x1F\x7F]') {
        throw "MySQL administrator password is empty or contains control characters."
    }
    $optionFile = Join-Path $temporaryDirectory "admin.cnf"
    $optionContent = @"
[client]
user="$(ConvertTo-OptionFileValue -Value $adminCredential.UserName)"
password="$(ConvertTo-OptionFileValue -Value $adminPassword)"
host=$connectionHost
port=$Port
default-character-set=utf8mb4
"@
    [IO.File]::WriteAllText(
        $optionFile,
        $optionContent,
        [Text.UTF8Encoding]::new($false)
    )
    Set-PrivatePathAcl -LiteralPath $optionFile

    function Invoke-AdministratorSql {
        param(
            [Parameter(Mandatory)]
            [string]$Sql,

            [Parameter(Mandatory)]
            [string]$Name
        )

        $sqlFile = Join-Path $temporaryDirectory "$Name.sql"
        [IO.File]::WriteAllText(
            $sqlFile,
            "SET SESSION time_zone = '+00:00';`n$Sql`n",
            [Text.UTF8Encoding]::new($false)
        )
        Set-PrivatePathAcl -LiteralPath $sqlFile
        try {
            $output = Get-Content -Raw -LiteralPath $sqlFile |
                & $mysqlCommand.Source `
                    "--defaults-extra-file=$optionFile" `
                    "--protocol=TCP" `
                    "--batch" `
                    "--raw" `
                    "--skip-column-names"
            if ($LASTEXITCODE -ne 0) {
                throw "mysql.exe failed during '$Name' with exit code $LASTEXITCODE."
            }
            return $output
        }
        finally {
            Remove-Item -LiteralPath $sqlFile -Force -ErrorAction SilentlyContinue
        }
    }

    $actualSchemaRevision = (
        Invoke-AdministratorSql `
            -Name "schema-revision-preflight" `
            -Sql "SELECT version_num FROM ``$DatabaseName``.``alembic_version``;"
    ) -join ""
    if ($actualSchemaRevision.Trim() -cne $expectedSchemaRevision) {
        throw (
            "Disposable database '$DatabaseName' is at schema revision " +
            "'$($actualSchemaRevision.Trim())'; expected " +
            "'$expectedSchemaRevision'."
        )
    }

    $tableLiterals = @($allTables) |
        Sort-Object |
        ForEach-Object { "'$_'" }
    $existingOutput = Invoke-AdministratorSql -Name "preflight" -Sql @"
SELECT COUNT(*)
FROM information_schema.tables
WHERE table_schema = '$DatabaseName'
  AND table_type = 'BASE TABLE'
  AND table_name IN ($($tableLiterals -join ','));
"@
    $existingCount = [int](($existingOutput -join "").Trim())
    if ($existingCount -ne $allTables.Count) {
        throw (
            "The test database is not at the schema expected by the privilege " +
            "manifest; no grants were changed."
        )
    }
    $columnPredicates = @($allColumnTargets) |
        Sort-Object |
        ForEach-Object {
            $table, $column = $_ -split '\|', 2
            "(table_name = '$table' AND column_name = '$column')"
        }
    $existingColumnOutput = Invoke-AdministratorSql -Name "column-preflight" -Sql @"
SELECT COUNT(*)
FROM information_schema.columns
WHERE table_schema = '$DatabaseName'
  AND ($($columnPredicates -join ' OR '));
"@
    $existingColumnCount = [int](($existingColumnOutput -join "").Trim())
    if ($existingColumnCount -ne $allColumnTargets.Count) {
        throw (
            "The test database columns do not match the privilege manifest; " +
            "no grants were changed."
        )
    }

    $granteeSql = @"
CONCAT(
    CHAR(39), '$RuntimeUser', CHAR(39), '@',
    CHAR(39), '$accountHost', CHAR(39)
)
"@
    $untargetedPrivilegeSnapshot = ConvertTo-OutputLines -Value @(
        Invoke-AdministratorSql -Name "untargeted-before" -Sql @"
SELECT signature
FROM (
    SELECT CONCAT(
               'GLOBAL|', privilege_type, '||||', is_grantable
           ) AS signature
    FROM information_schema.user_privileges
    WHERE grantee = $granteeSql
    UNION ALL
    SELECT CONCAT(
               'SCHEMA|', privilege_type, '|', table_schema,
               '|||', is_grantable
           ) AS signature
    FROM information_schema.schema_privileges
    WHERE grantee = $granteeSql
      AND table_schema <> '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'TABLE|', privilege_type, '|', table_schema, '|',
               table_name, '||', is_grantable
           ) AS signature
    FROM information_schema.table_privileges
    WHERE grantee = $granteeSql
      AND table_schema <> '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'COLUMN|', privilege_type, '|', table_schema, '|',
               table_name, '|', column_name, '|', is_grantable
           ) AS signature
    FROM information_schema.column_privileges
    WHERE grantee = $granteeSql
      AND table_schema <> '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'ROUTINE|', routine_privileges.privilege_type, '|',
               routine_grants.Db, '|', routine_grants.Routine_type, ':',
               routine_grants.Routine_name, '||NO'
           ) AS signature
    FROM mysql.procs_priv AS routine_grants
    INNER JOIN (
        SELECT 'EXECUTE' AS privilege_type, 'Execute' AS set_member
        UNION ALL
        SELECT 'ALTER ROUTINE', 'Alter Routine'
        UNION ALL
        SELECT 'GRANT OPTION', 'Grant'
    ) AS routine_privileges
        ON FIND_IN_SET(
            routine_privileges.set_member,
            routine_grants.Proc_priv
        ) > 0
    WHERE routine_grants.User = '$RuntimeUser'
      AND routine_grants.Host = '$accountHost'
      AND routine_grants.Db <> '$DatabaseName'
) AS untargeted
ORDER BY signature;
"@
    )
    $expectedUntargetedPrivilegeSnapshot = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($line in $untargetedPrivilegeSnapshot) {
        $null = $expectedUntargetedPrivilegeSnapshot.Add($line)
    }

    $revokeStatements = ConvertTo-OutputLines -Value @(
        Invoke-AdministratorSql -Name "target-revokes" -Sql @"
SELECT statement_text
FROM (
    SELECT CONCAT(
               'REVOKE ', privilege_type, ' ON ``',
               REPLACE(table_schema, '``', '````'),
               '``.* FROM ''$RuntimeUser''@''$accountHost'';'
           ) AS statement_text
    FROM information_schema.schema_privileges
    WHERE grantee = $granteeSql
      AND table_schema = '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'REVOKE ', privilege_type, ' ON ``',
               REPLACE(table_schema, '``', '````'), '``.``',
               REPLACE(table_name, '``', '````'),
               '`` FROM ''$RuntimeUser''@''$accountHost'';'
           ) AS statement_text
    FROM information_schema.table_privileges
    WHERE grantee = $granteeSql
      AND table_schema = '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'REVOKE ', privilege_type, ' (``',
               REPLACE(column_name, '``', '````'), '``) ON ``',
               REPLACE(table_schema, '``', '````'), '``.``',
               REPLACE(table_name, '``', '````'),
               '`` FROM ''$RuntimeUser''@''$accountHost'';'
           ) AS statement_text
    FROM information_schema.column_privileges
    WHERE grantee = $granteeSql
      AND table_schema = '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'REVOKE ', routine_privileges.privilege_type, ' ON ',
               routine_grants.Routine_type, ' ``',
               REPLACE(routine_grants.Db, '``', '````'), '``.``',
               REPLACE(routine_grants.Routine_name, '``', '````'),
               '`` FROM ''$RuntimeUser''@''$accountHost'';'
           ) AS statement_text
    FROM mysql.procs_priv AS routine_grants
    INNER JOIN (
        SELECT 'EXECUTE' AS privilege_type, 'Execute' AS set_member
        UNION ALL
        SELECT 'ALTER ROUTINE', 'Alter Routine'
        UNION ALL
        SELECT 'GRANT OPTION', 'Grant'
    ) AS routine_privileges
        ON FIND_IN_SET(
            routine_privileges.set_member,
            routine_grants.Proc_priv
        ) > 0
    WHERE routine_grants.User = '$RuntimeUser'
      AND routine_grants.Host = '$accountHost'
      AND routine_grants.Db = '$DatabaseName'
) AS target_grants
ORDER BY statement_text;
"@
    )
    if ($revokeStatements.Count -gt 0) {
        Invoke-AdministratorSql `
            -Name "remove-target-grants" `
            -Sql ($revokeStatements -join "`n") |
            Out-Null
    }

    $grants = [Collections.Generic.List[string]]::new()
    $grants.Add(
        "GRANT SELECT ON ``$DatabaseName``.* TO '$RuntimeUser'@'$accountHost';"
    )
    foreach ($table in $insertTables) {
        $grants.Add(
            "GRANT INSERT ON ``$DatabaseName``.``$table`` " +
            "TO '$RuntimeUser'@'$accountHost';"
        )
    }
    foreach ($table in $runtime["update"]) {
        $grants.Add(
            "GRANT UPDATE ON ``$DatabaseName``.``$table`` " +
            "TO '$RuntimeUser'@'$accountHost';"
        )
    }
    foreach ($table in $columnUpdates.Keys) {
        $columns = @($columnUpdates[$table]) |
            ForEach-Object { "``$_``" }
        $grants.Add(
            "GRANT UPDATE ($($columns -join ',')) ON " +
            "``$DatabaseName``.``$table`` TO '$RuntimeUser'@'$accountHost';"
        )
    }
    foreach ($table in $runtime["delete"]) {
        $grants.Add(
            "GRANT DELETE ON ``$DatabaseName``.``$table`` " +
            "TO '$RuntimeUser'@'$accountHost';"
        )
    }
    Invoke-AdministratorSql `
        -Name "runtime-grants" `
        -Sql ($grants -join "`n") |
        Out-Null

    $actualPrivilegeSignatures = ConvertTo-OutputLines -Value @(
        Invoke-AdministratorSql -Name "verify-target-grants" -Sql @"
SELECT signature
FROM (
    SELECT CONCAT(
               'SCHEMA|', privilege_type, '|||', is_grantable
           ) AS signature
    FROM information_schema.schema_privileges
    WHERE grantee = $granteeSql
      AND table_schema = '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'TABLE|', privilege_type, '|', table_name,
               '||', is_grantable
           ) AS signature
    FROM information_schema.table_privileges
    WHERE grantee = $granteeSql
      AND table_schema = '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'COLUMN|', privilege_type, '|', table_name, '|',
               column_name, '|', is_grantable
           ) AS signature
    FROM information_schema.column_privileges
    WHERE grantee = $granteeSql
      AND table_schema = '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'ROUTINE|', routine_privileges.privilege_type, '|',
               routine_grants.Routine_type, ':',
               routine_grants.Routine_name, '||NO'
           ) AS signature
    FROM mysql.procs_priv AS routine_grants
    INNER JOIN (
        SELECT 'EXECUTE' AS privilege_type, 'Execute' AS set_member
        UNION ALL
        SELECT 'ALTER ROUTINE', 'Alter Routine'
        UNION ALL
        SELECT 'GRANT OPTION', 'Grant'
    ) AS routine_privileges
        ON FIND_IN_SET(
            routine_privileges.set_member,
            routine_grants.Proc_priv
        ) > 0
    WHERE routine_grants.User = '$RuntimeUser'
      AND routine_grants.Host = '$accountHost'
      AND routine_grants.Db = '$DatabaseName'
) AS target_grants
ORDER BY signature;
"@
    )
    Assert-EquivalentStringSets `
        -Expected $expectedPrivilegeSignatures `
        -Actual $actualPrivilegeSignatures `
        -Label "Target test-database runtime privileges"

    $backupGranteeSql = @"
CONCAT(
    CHAR(39), '$BackupUser', CHAR(39), '@',
    CHAR(39), '$accountHost', CHAR(39)
)
"@
    $backupRevokeStatements = ConvertTo-OutputLines -Value @(
        Invoke-AdministratorSql -Name "backup-target-revokes" -Sql @"
SELECT statement_text
FROM (
    SELECT CONCAT(
               'REVOKE ', privilege_type, ' ON ``',
               REPLACE(table_schema, '``', '````'),
               '``.* FROM ''$BackupUser''@''$accountHost'';'
           ) AS statement_text
    FROM information_schema.schema_privileges
    WHERE grantee = $backupGranteeSql
      AND table_schema = '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'REVOKE ', privilege_type, ' ON ``',
               REPLACE(table_schema, '``', '````'), '``.``',
               REPLACE(table_name, '``', '````'),
               '`` FROM ''$BackupUser''@''$accountHost'';'
           ) AS statement_text
    FROM information_schema.table_privileges
    WHERE grantee = $backupGranteeSql
      AND table_schema = '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'REVOKE ', privilege_type, ' (``',
               REPLACE(column_name, '``', '````'), '``) ON ``',
               REPLACE(table_schema, '``', '````'), '``.``',
               REPLACE(table_name, '``', '````'),
               '`` FROM ''$BackupUser''@''$accountHost'';'
           ) AS statement_text
    FROM information_schema.column_privileges
    WHERE grantee = $backupGranteeSql
      AND table_schema = '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'REVOKE ', routine_privileges.privilege_type, ' ON ',
               routine_grants.Routine_type, ' ``',
               REPLACE(routine_grants.Db, '``', '````'), '``.``',
               REPLACE(routine_grants.Routine_name, '``', '````'),
               '`` FROM ''$BackupUser''@''$accountHost'';'
           ) AS statement_text
    FROM mysql.procs_priv AS routine_grants
    INNER JOIN (
        SELECT 'EXECUTE' AS privilege_type, 'Execute' AS set_member
        UNION ALL
        SELECT 'ALTER ROUTINE', 'Alter Routine'
        UNION ALL
        SELECT 'GRANT OPTION', 'Grant'
    ) AS routine_privileges
        ON FIND_IN_SET(
            routine_privileges.set_member,
            routine_grants.Proc_priv
        ) > 0
    WHERE routine_grants.User = '$BackupUser'
      AND routine_grants.Host = '$accountHost'
      AND routine_grants.Db = '$DatabaseName'
) AS target_grants
ORDER BY statement_text;
"@
    )
    if ($backupRevokeStatements.Count -gt 0) {
        Invoke-AdministratorSql `
            -Name "remove-backup-target-grants" `
            -Sql ($backupRevokeStatements -join "`n") |
            Out-Null
    }

    $backupGrants = [Collections.Generic.List[string]]::new()
    $backupSchemaPrivilegeList = ([string[]]$backup["schema"]) -join ", "
    $backupGrants.Add(
        "GRANT $backupSchemaPrivilegeList ON ``$DatabaseName``.* TO '$BackupUser'@'$accountHost';"
    )
    foreach ($table in $backup["insert"]) {
        $backupGrants.Add(
            "GRANT INSERT ON ``$DatabaseName``.``$table`` " +
            "TO '$BackupUser'@'$accountHost';"
        )
    }
    foreach ($table in $backup["update"]) {
        $backupGrants.Add(
            "GRANT UPDATE ON ``$DatabaseName``.``$table`` " +
            "TO '$BackupUser'@'$accountHost';"
        )
    }
    Invoke-AdministratorSql `
        -Name "backup-grants" `
        -Sql ($backupGrants -join "`n") |
        Out-Null

    $actualBackupPrivilegeSignatures = ConvertTo-OutputLines -Value @(
        Invoke-AdministratorSql -Name "verify-backup-target-grants" -Sql @"
SELECT signature
FROM (
    SELECT CONCAT(
               'SCHEMA|', privilege_type, '|||', is_grantable
           ) AS signature
    FROM information_schema.schema_privileges
    WHERE grantee = $backupGranteeSql
      AND table_schema = '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'TABLE|', privilege_type, '|', table_name,
               '||', is_grantable
           ) AS signature
    FROM information_schema.table_privileges
    WHERE grantee = $backupGranteeSql
      AND table_schema = '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'COLUMN|', privilege_type, '|', table_name, '|',
               column_name, '|', is_grantable
           ) AS signature
    FROM information_schema.column_privileges
    WHERE grantee = $backupGranteeSql
      AND table_schema = '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'ROUTINE|', routine_privileges.privilege_type, '|',
               routine_grants.Routine_type, ':',
               routine_grants.Routine_name, '||NO'
           ) AS signature
    FROM mysql.procs_priv AS routine_grants
    INNER JOIN (
        SELECT 'EXECUTE' AS privilege_type, 'Execute' AS set_member
        UNION ALL
        SELECT 'ALTER ROUTINE', 'Alter Routine'
        UNION ALL
        SELECT 'GRANT OPTION', 'Grant'
    ) AS routine_privileges
        ON FIND_IN_SET(
            routine_privileges.set_member,
            routine_grants.Proc_priv
        ) > 0
    WHERE routine_grants.User = '$BackupUser'
      AND routine_grants.Host = '$accountHost'
      AND routine_grants.Db = '$DatabaseName'
) AS target_grants
ORDER BY signature;
"@
    )
    Assert-EquivalentStringSets `
        -Expected $expectedBackupPrivilegeSignatures `
        -Actual $actualBackupPrivilegeSignatures `
        -Label "Target test-database backup privileges"

    $untargetedPrivilegeAfter = ConvertTo-OutputLines -Value @(
        Invoke-AdministratorSql -Name "untargeted-after" -Sql @"
SELECT signature
FROM (
    SELECT CONCAT(
               'GLOBAL|', privilege_type, '||||', is_grantable
           ) AS signature
    FROM information_schema.user_privileges
    WHERE grantee = $granteeSql
    UNION ALL
    SELECT CONCAT(
               'SCHEMA|', privilege_type, '|', table_schema,
               '|||', is_grantable
           ) AS signature
    FROM information_schema.schema_privileges
    WHERE grantee = $granteeSql
      AND table_schema <> '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'TABLE|', privilege_type, '|', table_schema, '|',
               table_name, '||', is_grantable
           ) AS signature
    FROM information_schema.table_privileges
    WHERE grantee = $granteeSql
      AND table_schema <> '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'COLUMN|', privilege_type, '|', table_schema, '|',
               table_name, '|', column_name, '|', is_grantable
           ) AS signature
    FROM information_schema.column_privileges
    WHERE grantee = $granteeSql
      AND table_schema <> '$DatabaseName'
    UNION ALL
    SELECT CONCAT(
               'ROUTINE|', routine_privileges.privilege_type, '|',
               routine_grants.Db, '|', routine_grants.Routine_type, ':',
               routine_grants.Routine_name, '||NO'
           ) AS signature
    FROM mysql.procs_priv AS routine_grants
    INNER JOIN (
        SELECT 'EXECUTE' AS privilege_type, 'Execute' AS set_member
        UNION ALL
        SELECT 'ALTER ROUTINE', 'Alter Routine'
        UNION ALL
        SELECT 'GRANT OPTION', 'Grant'
    ) AS routine_privileges
        ON FIND_IN_SET(
            routine_privileges.set_member,
            routine_grants.Proc_priv
        ) > 0
    WHERE routine_grants.User = '$RuntimeUser'
      AND routine_grants.Host = '$accountHost'
      AND routine_grants.Db <> '$DatabaseName'
) AS untargeted
ORDER BY signature;
"@
    )
    Assert-EquivalentStringSets `
        -Expected $expectedUntargetedPrivilegeSnapshot `
        -Actual $untargetedPrivilegeAfter `
        -Label "Global and non-target runtime privileges"

    Write-Host (
        "Test runtime and backup grants synchronized from manifest v$($manifest['version']). " +
        "No migrations ran and the primary database was not addressed."
    )
}
finally {
    $adminPassword = $null
    $resolvedTemporaryDirectory = [IO.Path]::GetFullPath($temporaryDirectory)
    $expectedPrefix = [IO.Path]::GetFullPath(
        (Join-Path $temporaryRoot "clsen-test-grants-")
    )
    if (
        $resolvedTemporaryDirectory.StartsWith(
            $expectedPrefix,
            [StringComparison]::OrdinalIgnoreCase
        ) -and
        (Test-Path -LiteralPath $resolvedTemporaryDirectory)
    ) {
        Remove-Item `
            -LiteralPath $resolvedTemporaryDirectory `
            -Recurse `
            -Force `
            -ErrorAction SilentlyContinue
    }
}
