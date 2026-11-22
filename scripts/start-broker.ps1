param([string]$Mosquitto = 'C:\Program Files\Mosquitto\mosquitto.exe')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& $Mosquitto -c broker/mosquitto.conf -v
exit $LASTEXITCODE
