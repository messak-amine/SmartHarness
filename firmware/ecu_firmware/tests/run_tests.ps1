# Run from PowerShell with GCC on PATH. No changes to Git or sdkconfig.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$src = Join-Path $root 'main'
$out = Join-Path $env:TEMP 'sh_m1_tests'
New-Item -ItemType Directory -Path $out -Force | Out-Null
$tests = @(
    @{ Name='sensor_sim'; Sources=@('sensor_sim.c') },
    @{ Name='fault_detector'; Sources=@('fault_detector.c') },
    @{ Name='ecu_events'; Sources=@('ecu_events.c') }
)
foreach ($test in $tests) {
    $name = $test.Name
    $exe = Join-Path $out ("test_$name.exe")
    $sources = @((Join-Path $PSScriptRoot ("test_$name.c")))
    foreach ($s in $test.Sources) { $sources += (Join-Path $src $s) }
    & gcc -std=c11 -Wall -Wextra -Werror -I $src @sources -o $exe
    if ($LASTEXITCODE -ne 0) { throw "Compile failed: $name" }
    & $exe
    if ($LASTEXITCODE -ne 0) { throw "Test failed: $name" }
}


# Cross-component CAN v1 compatibility (application -> shared codec).
$canInc = Join-Path $root '../components/smartharness_can/include'
$canSrc = Join-Path $root '../components/smartharness_can/smartharness_can.c'
$integratedExe = Join-Path $out 'test_ecu_can_adapter.exe'
& gcc -std=c11 -Wall -Wextra -Werror -I $src -I $canInc `
    (Join-Path $PSScriptRoot 'test_ecu_can_adapter.c') `
    (Join-Path $src 'sensor_sim.c') `
    (Join-Path $src 'fault_detector.c') `
    (Join-Path $src 'ecu_events.c') `
    (Join-Path $src 'ecu_can_adapter.c') `
    $canSrc -o $integratedExe
if ($LASTEXITCODE -ne 0) { throw 'Compile failed: ECU/CAN integration' }
& $integratedExe
if ($LASTEXITCODE -ne 0) { throw 'Test failed: ECU/CAN integration' }
Write-Host 'All ECU and ECU/CAN integration tests passed.'
