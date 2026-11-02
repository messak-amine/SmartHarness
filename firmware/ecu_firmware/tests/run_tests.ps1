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
Write-Host "All native tests passed."
