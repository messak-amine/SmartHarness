$ErrorActionPreference = 'Stop'
$dashboardRoot = Split-Path $PSScriptRoot -Parent
$toolsDirectory = Join-Path $dashboardRoot '.tools'
$archive = Join-Path $toolsDirectory 'npm.tgz'
New-Item -ItemType Directory -Force $toolsDirectory | Out-Null
Invoke-WebRequest -Uri 'https://registry.npmjs.org/npm/-/npm-12.2.1.tgz' -OutFile $archive
$expected = 'bKCmFRVT/BB+YPEYbZwQ1XUI3N5t4xKSpU1MxOjo7z3iWzKBJ0ZXRC1xFdEN+TC7N5TdywaBzf2dMXGJq/e2PQ=='
$sha = [Security.Cryptography.SHA512]::Create()
try { $actual = [Convert]::ToBase64String($sha.ComputeHash([IO.File]::ReadAllBytes($archive))) }
finally { $sha.Dispose() }
if ($actual -ne $expected) { throw 'Empreinte npm incorrecte : extraction annulée.' }
& tar -xzf $archive -C $toolsDirectory
if ($LASTEXITCODE -ne 0) { throw 'Échec de l’extraction npm.' }
Write-Host 'npm 12.2.1 préparé localement. Utiliser scripts/npm.ps1 ci.'
