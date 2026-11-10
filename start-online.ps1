[CmdletBinding()]
param([switch]$Stop)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'dashboard\scripts\windows-startup.ps1')
Invoke-SmartHarnessStartup -Online $true -Stopping $Stop
