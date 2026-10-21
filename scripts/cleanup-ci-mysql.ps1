#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$ContainerName = $env:MATRIX_CONTAINER,
    [string]$RunIdentifier = $env:MATRIX_RUN_ID
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ContainerName) -and
    [string]::IsNullOrWhiteSpace($RunIdentifier)) {
    return
}
$containerMatch = [regex]::Match($ContainerName, '\Aclsen-mysql-matrix-[0-9]+-([0-9a-f]{12})-8-[04]\z')
if ($RunIdentifier -cnotmatch '\A[0-9a-f]{32}\z' -or -not $containerMatch.Success) {
    throw "Invalid disposable MySQL container identity."
}
if ($containerMatch.Groups[1].Value -cne $RunIdentifier.Substring(0, 12)) {
    throw "MySQL container name and run identity differ."
}

$containers = @(& docker container ls --all --filter "name=^/$ContainerName`$" --format '{{.ID}}' 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "Could not check the disposable MySQL container."
}
if ($containers.Count -eq 0) {
    return
}
$label = @(& docker inspect --format '{{ index .Config.Labels "clsen.mysql-matrix.run" }}' $ContainerName 2>&1)
if ($LASTEXITCODE -ne 0 -or ($label -join "").Trim() -cne $RunIdentifier) {
    throw "Refused to remove a MySQL container with a different ownership label."
}
& docker rm --force --volumes $ContainerName
if ($LASTEXITCODE -ne 0) {
    throw "Could not remove the disposable MySQL container."
}
