#Requires -Version 7.0

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$SecretDirectory = (Join-Path $PSScriptRoot "secrets"),

    [Parameter()]
    [ValidatePattern('^[A-Za-z0-9.-]{1,253}$')]
    [string]$HostName = "localhost",

    [Parameter()]
    [switch]$Force,

    [Parameter()]
    [switch]$RotateEdgeCertificate
)

$ErrorActionPreference = "Stop"
$secretRoot = [IO.Path]::GetFullPath($SecretDirectory)
$opsRoot = [IO.Path]::GetFullPath($PSScriptRoot)
if (-not $secretRoot.StartsWith(
    $opsRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) +
        [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "The generated secret directory must remain under the ops directory."
}

function New-RandomSecret {
    $bytes = [byte[]]::new(48)
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Set-PrivatePathAcl {
    param(
        [Parameter(Mandatory)]
        [string]$LiteralPath,

        [Parameter()]
        [switch]$Directory
    )

    if (-not $IsWindows) {
        & chmod $(if ($Directory) { "700" } else { "600" }) $LiteralPath
        if ($LASTEXITCODE -ne 0) {
            throw "chmod failed for generated deployment material."
        }
        return
    }

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $acl = if ($Directory) {
        [Security.AccessControl.DirectorySecurity]::new()
    }
    else {
        [Security.AccessControl.FileSecurity]::new()
    }
    $inheritance = if ($Directory) {
        [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
    }
    else {
        [Security.AccessControl.InheritanceFlags]::None
    }
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $identity,
        [Security.AccessControl.FileSystemRights]::FullControl,
        $inheritance,
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow
    ))
    $pathInfo = if ($Directory) {
        [IO.DirectoryInfo]::new($LiteralPath)
    }
    else {
        [IO.FileInfo]::new($LiteralPath)
    }
    [IO.FileSystemAclExtensions]::SetAccessControl($pathInfo, $acl)
}

if ($Force -and $RotateEdgeCertificate) {
    throw "-Force and -RotateEdgeCertificate cannot be used together."
}
if ((Test-Path -LiteralPath $secretRoot) -and -not $Force -and -not $RotateEdgeCertificate) {
    throw "The deployment secret directory already exists. Use -Force only to rotate all secrets on an empty deployment."
}
if ($RotateEdgeCertificate -and -not (Test-Path -LiteralPath $secretRoot -PathType Container)) {
    throw "The deployment secret directory does not exist; generate the full secret set first."
}
$action = if ($RotateEdgeCertificate) {
    "Rotate only the local edge TLS certificate"
}
else {
    "Generate deployment secrets and local TLS certificates"
}
if (-not $PSCmdlet.ShouldProcess($secretRoot, $action)) {
    return
}

if ((Test-Path -LiteralPath $secretRoot) -and -not $RotateEdgeCertificate) {
    $resolvedExisting = [IO.Path]::GetFullPath($secretRoot)
    if (-not $resolvedExisting.StartsWith(
        $opsRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) +
            [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Refusing to replace a secret directory outside ops."
    }
    Remove-Item -LiteralPath $resolvedExisting -Recurse -Force
}
if (-not $RotateEdgeCertificate) {
    New-Item -ItemType Directory -Path $secretRoot | Out-Null
    Set-PrivatePathAcl -LiteralPath $secretRoot -Directory
}

$secretNames = @(
    "mysql_root_password",
    "mysql_app_password",
    "mysql_migrator_password",
    "mysql_backup_password",
    "session_secret"
)
if (-not $RotateEdgeCertificate) {
    foreach ($name in $secretNames) {
        $path = Join-Path $secretRoot $name
        [IO.File]::WriteAllText($path, (New-RandomSecret), [Text.UTF8Encoding]::new($false))
        Set-PrivatePathAcl -LiteralPath $path
    }
}

$docker = Get-Command docker -ErrorAction Stop
$certificateScript = @'
set -eu
apk add --no-cache openssl >/dev/null
cd /work
GENERATE_MYSQL_CERTIFICATES
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 90 \
  -subj "/CN=HOST_NAME" \
  -addext "subjectAltName=DNS:HOST_NAME,DNS:localhost,DNS:nginx,DNS:verification-nginx,IP:127.0.0.1" \
  -keyout tls_private_key.pem -out tls_certificate.pem
chmod 600 tls_private_key.pem
chmod 644 tls_certificate.pem
'@
$mysqlCertificateScript = @'
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 3650 \
  -subj "/CN=CLSEN MySQL Internal CA" \
  -keyout mysql_ca_private_key.pem -out mysql_ca_certificate.pem
openssl req -new -newkey rsa:3072 -sha256 -nodes \
  -subj "/CN=mysql" -addext "subjectAltName=DNS:mysql" \
  -keyout mysql_server_private_key.pem -out mysql_server.csr
openssl x509 -req -sha256 -days 825 \
  -in mysql_server.csr -CA mysql_ca_certificate.pem \
  -CAkey mysql_ca_private_key.pem -CAcreateserial \
  -copy_extensions copy -out mysql_server_certificate.pem
rm -f mysql_server.csr mysql_ca_certificate.srl
chmod 600 mysql_ca_private_key.pem mysql_server_private_key.pem
chmod 644 mysql_ca_certificate.pem mysql_server_certificate.pem
'@
$certificateScript = $certificateScript.Replace(
    "GENERATE_MYSQL_CERTIFICATES",
    $(if ($RotateEdgeCertificate) { "" } else { $mysqlCertificateScript })
).Replace("HOST_NAME", $HostName)
# Keep the checked-in PowerShell line ending independent from the POSIX shell payload.
$certificateScript = $certificateScript.Replace("`r`n", "`n").Replace("`r", "`n")

& $docker.Source run --rm `
    --mount "type=bind,source=$secretRoot,target=/work" `
    alpine:3.22 sh -ec $certificateScript
if ($LASTEXITCODE -ne 0) {
    throw "TLS certificate generation failed with exit code $LASTEXITCODE."
}

Get-ChildItem -LiteralPath $secretRoot -File | ForEach-Object {
    Set-PrivatePathAcl -LiteralPath $_.FullName
}

if ($RotateEdgeCertificate) {
    Write-Host "The local edge verification certificate was rotated in $secretRoot."
}
else {
    Write-Host "Deployment secrets and local verification certificates were created in $secretRoot."
}
Write-Warning "The edge certificate is self-signed and valid for 90 days. Replace it with a trusted server certificate before shared deployment."
