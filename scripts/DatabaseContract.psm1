Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-DatabaseSchemaRevision {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string]$PythonExecutable,
        [Parameter(Mandatory)] [string]$BackendDirectory
    )
    $previous = Get-Location
    try {
        Set-Location -LiteralPath $BackendDirectory
        $output = @(
            & $PythonExecutable -c (
                "from app.maintenance.schema_revision import " +
                "CURRENT_SCHEMA_REVISION; print(CURRENT_SCHEMA_REVISION)"
            ) 2>&1
        )
        if ($LASTEXITCODE -ne 0) {
            throw "Could not load the shared schema revision."
        }
    }
    finally { Set-Location -LiteralPath $previous }
    $revision = ($output -join "").Trim()
    if ($revision -cnotmatch '\A[0-9]{4}\z') {
        throw "The shared schema revision is invalid."
    }
    return $revision
}

function Assert-NoDuplicateJsonObjectKeys {
    param(
        [Parameter(Mandatory)] [System.Text.Json.JsonElement]$Element,
        [Parameter(Mandatory)] [string]$Path
    )
    if ($Element.ValueKind -eq [System.Text.Json.JsonValueKind]::Object) {
        $seen = [Collections.Generic.HashSet[string]]::new(
            [StringComparer]::Ordinal
        )
        foreach ($property in $Element.EnumerateObject()) {
            if (-not $seen.Add($property.Name)) {
                throw "Duplicate JSON object key '$($property.Name)' at '$Path'."
            }
            Assert-NoDuplicateJsonObjectKeys $property.Value "$Path.$($property.Name)"
        }
    }
    elseif ($Element.ValueKind -eq [System.Text.Json.JsonValueKind]::Array) {
        $index = 0
        foreach ($item in $Element.EnumerateArray()) {
            Assert-NoDuplicateJsonObjectKeys $item "${Path}[$index]"
            $index++
        }
    }
}

function Assert-IdentifierArray {
    param(
        [Parameter(Mandatory)] $Value,
        [Parameter(Mandatory)] [string]$Context
    )
    if ($Value -isnot [array] -or $Value.Count -eq 0) {
        throw "$Context must be a non-empty array."
    }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($identifier in $Value) {
        if ($identifier -isnot [string] -or
            $identifier -cnotmatch '\A[a-z][a-z0-9_]{0,63}\z') {
            throw "$Context contains an unsafe identifier."
        }
        if (-not $seen.Add($identifier)) {
            throw "$Context contains a duplicate identifier."
        }
    }
}

function Import-StrictDatabasePrivilegeManifest {
    [CmdletBinding()]
    param([Parameter(Mandatory)] [string]$LiteralPath)
    if (-not (Test-Path -LiteralPath $LiteralPath -PathType Leaf)) {
        throw "Database privilege manifest was not found at '$LiteralPath'."
    }
    $document = $null
    try {
        $json = Get-Content -LiteralPath $LiteralPath -Raw -Encoding UTF8
        $document = [System.Text.Json.JsonDocument]::Parse($json)
        Assert-NoDuplicateJsonObjectKeys $document.RootElement '$'
        $manifest = $json | ConvertFrom-Json -AsHashtable -Depth 100
    }
    catch {
        throw "Database privilege manifest is not valid JSON: $($_.Exception.Message)"
    }
    finally { if ($null -ne $document) { $document.Dispose() } }

    if ($manifest -isnot [Collections.IDictionary] -or
        (@($manifest.Keys | Sort-Object) -join '|') -cne 'backup|runtime|version' -or
        $manifest.version -isnot [long] -or $manifest.version -ne 5) {
        throw "Database privilege manifest must contain version 5, runtime, and backup."
    }
    $runtime = $manifest.runtime
    $categories = @("delete", "insert_only", "mutable_insert", "update", "update_columns")
    if ($runtime -isnot [Collections.IDictionary] -or
        (@($runtime.Keys | Sort-Object) -join '|') -cne ($categories -join '|')) {
        throw "Runtime privileges must contain exactly the five supported categories."
    }
    foreach ($category in @("insert_only", "mutable_insert", "update", "delete")) {
        Assert-IdentifierArray $runtime[$category] "Runtime privilege '$category'"
    }
    $columnUpdates = $runtime.update_columns
    if ($columnUpdates -isnot [Collections.IDictionary] -or $columnUpdates.Count -eq 0) {
        throw "Runtime privilege 'update_columns' must be a non-empty object."
    }
    foreach ($table in $columnUpdates.Keys) {
        if ([string]$table -cnotmatch '\A[a-z][a-z0-9_]{0,63}\z') {
            throw "Runtime update_columns contains an unsafe table."
        }
        Assert-IdentifierArray $columnUpdates[$table] "Runtime columns for '$table'"
    }
    $insertOnly = [Collections.Generic.HashSet[string]]::new(
        [string[]]$runtime.insert_only, [StringComparer]::Ordinal
    )
    $mutable = [Collections.Generic.HashSet[string]]::new(
        [string[]]$runtime.mutable_insert, [StringComparer]::Ordinal
    )
    if ($insertOnly.Overlaps($mutable)) {
        throw "Runtime insert_only and mutable_insert tables must be mutually exclusive."
    }
    foreach ($category in @("update", "delete")) {
        foreach ($table in $runtime[$category]) {
            if (-not $mutable.Contains($table)) {
                throw "Runtime privilege '$category' must be a subset of mutable_insert."
            }
        }
    }
    $tableUpdates = [Collections.Generic.HashSet[string]]::new(
        [string[]]$runtime.update, [StringComparer]::Ordinal
    )
    foreach ($table in $columnUpdates.Keys) {
        if (-not $mutable.Contains($table) -or $tableUpdates.Contains($table)) {
            throw "Runtime column UPDATE must be a non-overlapping mutable_insert subset."
        }
    }

    $backup = $manifest.backup
    if ($backup -isnot [Collections.IDictionary] -or
        (@($backup.Keys | Sort-Object) -join '|') -cne 'insert|schema|update' -or
        (@($backup.schema) -join '|') -cne 'SELECT|SHOW VIEW|TRIGGER|EVENT') {
        throw "Backup privileges have an invalid schema."
    }
    Assert-IdentifierArray $backup.insert "Backup INSERT privileges"
    Assert-IdentifierArray $backup.update "Backup UPDATE privileges"
    foreach ($table in $backup.update) {
        if ([string[]]$backup.insert -cnotcontains $table) {
            throw "Backup UPDATE privileges must be a subset of INSERT privileges."
        }
    }
    return $manifest
}

Export-ModuleMember -Function Get-DatabaseSchemaRevision,
    Import-StrictDatabasePrivilegeManifest
