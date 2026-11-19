#Requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[a-z][a-z0-9-]+$')][string]$ProjectName,
    [Parameter(Mandatory)][string]$EnvFile,
    [Parameter(Mandatory)][ValidatePattern('^[a-zA-Z0-9_.-]+$')][string]$KeyringFile
)
$ErrorActionPreference = 'Stop'
$compose = @('compose', '--project-name', $ProjectName, '--env-file', [IO.Path]::GetFullPath($EnvFile),
    '-f', (Join-Path $PSScriptRoot 'docker-compose.yml'), '-f', (Join-Path $PSScriptRoot 'docker-compose.production.yml'))
function Invoke-Compose([string[]]$Arguments) {
    & docker @compose @Arguments
    if ($LASTEXITCODE) { throw 'B compose operation failed' }
}
function Get-Writers {
    $rows = & docker @compose ps --format json
    if ($LASTEXITCODE) { throw 'Cannot verify B writer state' }
    $items = @($rows | ForEach-Object { $_ | ConvertFrom-Json })
    @($items | Where-Object { $_.Service -in @('backend', 'worker', 'production') -and $_.State -eq 'running' } | Select-Object -ExpandProperty Service)
}
$running = @(Get-Writers)
$id = [guid]::NewGuid().ToString('N')
try {
    if ($running.Count) { Invoke-Compose (@('stop') + $running) }
    if (@(Get-Writers).Count) { throw 'B writers are still running; backup refused' }
    Invoke-Compose @('--profile', 'maintenance', 'run', '--rm', '--no-deps', 'production-maintenance',
        'backup', '--quiesced', '--directory', "/var/lib/clsen/backups/$id", '--keyring', "/var/lib/clsen/keyring/$KeyringFile")
    Write-Host "B backup completed: $id"
} finally {
    if ($running.Count) { Invoke-Compose (@('up', '-d', '--no-deps') + $running) }
}
