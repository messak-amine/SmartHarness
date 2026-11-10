# Wrapper local : aucune installation globale et aucun changement du PATH permanent.
$ErrorActionPreference = 'Stop'
$dashboardRoot = Split-Path $PSScriptRoot -Parent
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCommand) { $nodeExecutable = $nodeCommand.Source }
else {
    $nodeExecutable = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    if (-not (Test-Path -LiteralPath $nodeExecutable)) { throw 'Node.js 24 est requis. Installer Node.js 24 puis rouvrir PowerShell.' }
}
$localNpm = Join-Path $dashboardRoot '.tools/package/bin/npm-cli.js'
if (-not (Test-Path -LiteralPath $localNpm)) { throw 'Exécuter scripts/bootstrap-npm.ps1 une fois, ou utiliser votre npm habituel.' }
# Les scripts npm doivent également trouver node dans leurs sous-processus.
$previousPath = $env:PATH
try {
    $env:PATH = (Split-Path $nodeExecutable -Parent) + [IO.Path]::PathSeparator + $previousPath
    Push-Location $dashboardRoot
    try { & $nodeExecutable $localNpm @args; $npmExitCode = $LASTEXITCODE }
    finally { Pop-Location }
} finally { $env:PATH = $previousPath }
exit $npmExitCode
