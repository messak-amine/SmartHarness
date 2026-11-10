# Windows PowerShell 5.1 and PowerShell 7. Shared by both launchers.
$dashboardDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtimeDir = Join-Path $dashboardDir '.runtime\launcher'
$proxyJs = Join-Path $PSScriptRoot 'dashboard-proxy.js'
$redJs = Join-Path $PSScriptRoot 'start.js'
$localUrl = 'http://127.0.0.1:1880/dashboard/monitoring'
$proxyUrl = 'http://127.0.0.1:1881'
$tunnelArgs = $null
$mailFile = Join-Path $dashboardDir 'access.local.txt'
if (Test-Path -LiteralPath $mailFile -PathType Leaf) {
    $mail = ([IO.File]::ReadAllText($mailFile)).Trim()
    if ($mail -cmatch '\A[A-Za-z0-9][A-Za-z0-9._+-]*@gmail\.com\z') {
        $tunnelArgs = "tunnel --url http://127.0.0.1:1881 --allowed-mail $mail --allowed-mail *@edu.uiz.ac.ma"
    }
}

function Find-Program($name, $paths) {
    $cmd = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { return $cmd.Source }
    foreach ($path in $paths) { if ($path -and (Test-Path -LiteralPath $path -PathType Leaf)) { return $path } }
    throw "$name introuvable. Installer le programme ou ajouter son dossier au PATH."
}

function Get-PortOwner([int]$port, $expectedName) {
    # IPGlobalProperties avoids treating a CIM permission error as a free port.
    $bound = [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() |
        Where-Object Port -eq $port
    if (!$bound) { return }
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop)
    $owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners.Count -ne 1 -or @($listeners | Where-Object { $_.LocalAddress -notin '::1','127.0.0.1' }).Count) {
        throw "Port $port : ecoute inattendue. Verifier le processus et son adresse."
    }
    $owner = Get-Process -Id $owners[0]
    if ($owner.ProcessName -ne $expectedName) { throw "Port $port utilise par $($owner.ProcessName)." }
    return $owner
}

function Get-ArgumentsOf($process) {
    $info = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
    if (!$info.CommandLine) { throw "Impossible de verifier la commande du PID $($process.Id)." }
    return ($info.CommandLine.Trim() -replace '^(?:"[^"]+"|\S+)\s*','').Trim()
}

function Start-Owned($role, $exe, $arguments, $environment = @{}) {
    $saved = @{}
    try {
        foreach ($key in $environment.Keys) {
            $saved[$key] = [Environment]::GetEnvironmentVariable($key,'Process')
            [Environment]::SetEnvironmentVariable($key,$environment[$key],'Process')
        }
        $child = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $dashboardDir -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $runtimeDir "$role.out.log") -RedirectStandardError (Join-Path $runtimeDir "$role.err.log")
        try {
            $record = @{ pid=$child.Id; start=$child.StartTime.ToUniversalTime().Ticks.ToString(); exe=$exe; arguments=$arguments }
            $record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimeDir "$role.json") -Encoding UTF8
        } catch { if (!$child.HasExited) { $child.Kill() }; throw }
        return $child
    } finally {
        foreach ($key in $saved.Keys) { [Environment]::SetEnvironmentVariable($key,$saved[$key],'Process') }
    }
}

function Stop-Owned($role) {
    $file = Join-Path $runtimeDir "$role.json"
    if (!(Test-Path -LiteralPath $file)) { return }
    $record = Get-Content -Raw -LiteralPath $file | ConvertFrom-Json
    $child = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
    if ($child -and $child.StartTime.ToUniversalTime().Ticks.ToString() -eq $record.start) {
        if ($child.Path -ne $record.exe -or (Get-ArgumentsOf $child) -ne $record.arguments) { throw "Identite du processus $role non confirmee." }
        $child.Kill()
        if (!$child.WaitForExit(5000)) { throw "Arret de $role en attente." }
        Write-Host "$role arrete."
    }
    Remove-Item -LiteralPath $file
}

function Wait-Ready($label, [scriptblock]$probe, $child = $null) {
    $deadline = [datetime]::UtcNow.AddSeconds(45)
    $reason = ''
    do {
        if ($child -and $child.HasExited) { throw "$label arrete. Voir les journaux dans $runtimeDir." }
        try { $value = & $probe; if ($value) { return $value } } catch { $reason = $_.Exception.Message }
        Start-Sleep -Milliseconds 350
    } while ([datetime]::UtcNow -lt $deadline)
    throw "$label indisponible. $reason Voir $runtimeDir."
}

function Start-LocalStack {
    $broker = Get-PortOwner 1883 mosquitto
    if (!$broker) {
        $exe = Find-Program mosquitto.exe @("$env:ProgramFiles\Mosquitto\mosquitto.exe")
        $broker = Start-Owned broker $exe ('-c "' + (Join-Path $dashboardDir 'mosquitto.conf') + '"')
        try { Wait-Ready 'Mosquitto' { (Get-PortOwner 1883 mosquitto).Id -eq $broker.Id } $broker | Out-Null }
        catch { Stop-Owned broker; throw }
    }
    $red = Get-PortOwner 1880 node
    $newRed = !$red
    if ($newRed) {
        $red = Start-Owned red $nodeExe ('"' + $redJs + '"') @{
            PORT='1880'; MQTT_PORT='1883'; MQTT_HOST='127.0.0.1'; SH_DB_PATH=(Join-Path $dashboardDir 'data\events.sqlite'); SH_RUNTIME_DIR=(Join-Path $dashboardDir '.runtime')
        }
    }
    try {
        Wait-Ready 'Node-RED / SQLite / MQTT' {
            $s = Invoke-RestMethod -Uri 'http://127.0.0.1:1880/api/snapshot' -TimeoutSec 3
            $s.ready -and $s.database -eq 'ready' -and $s.mqtt -eq 'connected' -and @($s.circuits).Count -eq 4
        } $red | Out-Null
        $response = Invoke-WebRequest -UseBasicParsing -Uri $localUrl -TimeoutSec 5
        if ($response.StatusCode -ne 200 -or $response.Content -notmatch 'FlowFuse Dashboard') { throw 'Page Dashboard inattendue.' }
    } catch { if ($newRed) { Stop-Owned red }; throw }
}

function Get-TailscaleName {
    $ts = Get-Command tailscale.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
    if (!$ts) { $ts = "$env:ProgramFiles\Tailscale\tailscale.exe" }
    if (Test-Path -LiteralPath $ts) {
        $status = & $ts status --json
        if ($status) {
            $dns = ($status | ConvertFrom-Json).Self.DNSName
            if ($dns) { return $dns.TrimEnd('.') }
        }
    }
    return ''
}

function Start-Proxy($externalName) {
    $proxy = Start-Owned proxy $nodeExe ('"' + $proxyJs + '"') @{ SH_ACCESS_HOSTNAME=$externalName; SH_TAILSCALE_DNS=$tsName }
    Wait-Ready 'Proxy' { (Get-PortOwner 1881 node).Id -eq $proxy.Id } $proxy | Out-Null
}

function Test-Viewer($externalName) {
    & $nodeExe (Join-Path $PSScriptRoot 'check-viewer.js') ([string]$externalName + '|'+ [string]$tsName)
    return ($LASTEXITCODE -eq 0)
}

function Get-Tunnel {
    $candidates = @(Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'")
    $matching = @()
    foreach ($candidate in $candidates) {
        if (!$candidate.CommandLine) { throw 'Tunnel existant non identifiable.' }
        $argsText = ($candidate.CommandLine.Trim() -replace '^(?:"[^"]+"|\S+)\s*','').Trim()
        if ($argsText -ceq $tunnelArgs) { $matching += $candidate }
        elseif ($argsText -match '(?i)(?:localhost|127\.0\.0\.1|\[::1\]):1881\b') {
            throw 'Un tunnel vers 1881 utilise une autre configuration. Verifier ou fermer son terminal.'
        }
    }
    if ($matching.Count -gt 1) { throw 'Plusieurs tunnels vers le proxy. Fermer les doublons.' }
    if ($matching.Count) { return Get-Process -Id $matching[0].ProcessId }
}

function Get-TunnelName($tunnel, [switch]$RequireReady) {
    Wait-Ready 'Nom du tunnel' {
        $ports = Get-NetTCPConnection -State Listen -OwningProcess $tunnel.Id -ErrorAction SilentlyContinue |
            Where-Object LocalAddress -eq '127.0.0.1'
        foreach ($port in $ports) {
            $info = Invoke-RestMethod -TimeoutSec 2 -Uri ("http://127.0.0.1:" + $port.LocalPort + '/quicktunnel')
            if ($info.hostname -cmatch '^[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com$') {
                if ($RequireReady) {
                    $health = Invoke-RestMethod -TimeoutSec 2 -Uri ("http://127.0.0.1:" + $port.LocalPort + '/ready')
                    if ($health.readyConnections -lt 1) { continue }
                }
                return $info.hostname
            }
        }
    } $tunnel
}

# A stale Quick Tunnel can keep its local metrics server after its DNS entry expires.
function Test-ExpiredTunnel($tunnel, $name) {
    $ports = Get-NetTCPConnection -State Listen -OwningProcess $tunnel.Id | Where-Object LocalAddress -eq '127.0.0.1'
    foreach ($port in $ports) {
        $base = 'http://127.0.0.1:' + $port.LocalPort
        $who = Invoke-RestMethod "$base/quicktunnel" -TimeoutSec 2
        if ($who.hostname -ne $name) { continue }
        $health = & curl.exe -s --max-time 3 "$base/ready"
        if ($LASTEXITCODE -ne 0) { return $false }
        $health = $health | ConvertFrom-Json
        if ($health.status -ne 503 -or $health.readyConnections -ne 0) { return $false }
        # Require functional DNS and a missing name, not a timeout.
        $null = [Net.Dns]::GetHostAddresses('login.trycloudflare.com')
        try { $null = [Net.Dns]::GetHostAddresses($name); return $false }
        catch { return ($_.Exception.GetBaseException().SocketErrorCode -eq 'HostNotFound') }
    }
    return $false
}

function Invoke-SmartHarnessStartup([bool]$Online, [bool]$Stopping) {
    $null = [IO.Directory]::CreateDirectory($runtimeDir)
    # Both entry points serialize port checks, replacement and stop operations.
    $lock = [IO.File]::Open((Join-Path $runtimeDir 'startup.lock'),'OpenOrCreate','ReadWrite','None')
    $newTunnel = $false
    $changingProxy = $false
    try {
        if ($Stopping) {
            if ($Online) {
                Stop-Owned tunnel
                if (Get-Tunnel) { Write-Host 'Tunnel lance manuellement : Ctrl+C dans son terminal pour fermer le partage.' }
            }
            else {
                if (Get-Tunnel) { throw 'Arreter le tunnel avant les services locaux.' }
                foreach ($role in 'proxy','red','broker') { Stop-Owned $role }
            }
            return
        }
        if ($Online -and !$tunnelArgs) { throw 'Configurer une adresse Gmail exacte dans dashboard/access.local.txt.' }
        $nodeExe = Find-Program node.exe @()
        $tsName = Get-TailscaleName
        Start-LocalStack
        $proxy = Get-PortOwner 1881 node
        if ($proxy -and (Get-ArgumentsOf $proxy).Trim('"') -ne $proxyJs) {
            # A relative invocation can be reused after the checks, never stopped automatically.
            if ((Get-ArgumentsOf $proxy) -notmatch '^(?:\.\\)?scripts[/\\]dashboard-proxy\.js$') { throw 'Proxy inconnu sur 1881.' }
        }
        if (!$proxy) {
            $changingProxy = $true
            Start-Proxy ''
            $proxy = Get-PortOwner 1881 node
        }
        if (!(Test-Viewer '')) { throw 'Verification du proxy local impossible.' }
        $changingProxy = $false
        if (!$Online) { Write-Host "Dashboard local : $localUrl"; return }

        $tunnel = Get-Tunnel
        if ($tunnel) {
            $oldName = Get-TunnelName $tunnel
            if (Test-ExpiredTunnel $tunnel $oldName) {
                Start-Sleep -Seconds 3
                if (Test-ExpiredTunnel $tunnel $oldName) {
                    Write-Host "Tunnel expire ($oldName). Renouvellement du tunnel SmartHarness."
                    $tunnel.Kill()
                    if (!$tunnel.WaitForExit(5000)) { throw 'Ancien tunnel encore actif.' }
                    $tunnel = $null
                }
            }
        }
        if (!$tunnel) {
            $cf = Find-Program cloudflared.exe @("${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe","$env:ProgramFiles\cloudflared\cloudflared.exe")
            if ((& $cf tunnel --help | Out-String) -notmatch '--allowed-mail\s') { throw 'Version de cloudflared sans --allowed-mail.' }
            $tunnel = Start-Owned tunnel $cf $tunnelArgs
            $newTunnel = $true
        }
        $externalName = Get-TunnelName $tunnel -RequireReady
        # Confirm the edge login before authorizing its exact Host at the proxy.
        Wait-Ready 'Authentification Cloudflare' {
            $redirect = & curl.exe -s --max-time 5 -o NUL -w '%{http_code} %{redirect_url}' "https://$externalName/dashboard/monitoring"
            $redirect -cmatch '^30[12378] https://login\.trycloudflare\.com/authorize(?:\?|$)'
        } $tunnel | Out-Null
        $code = & curl.exe --noproxy '*' -sS --max-time 5 -o NUL -w '%{http_code}' -H "Host: $externalName" "$proxyUrl/dashboard/monitoring"
        if ($code -eq '403') {
            if ((Get-ArgumentsOf $proxy).Trim('"') -ne $proxyJs) { throw 'Relancer le proxy manuel avec son chemin absolu avant remplacement.' }
            $changingProxy = $true
            $proxy.Kill()
            if (!$proxy.WaitForExit(5000)) { throw 'Ancien proxy encore actif.' }
            Start-Proxy $externalName
        }
        if (!(Test-Viewer $externalName)) { throw 'Verification finale du proxy impossible.' }
        $changingProxy = $false
        Write-Host "Dashboard en ligne : https://$externalName/dashboard/monitoring"
    } catch {
        if ($newTunnel) { Stop-Owned tunnel }
        if ($changingProxy) {
            Stop-Owned proxy
            if (!(Get-PortOwner 1881 node)) { Start-Proxy '' }
        }
        throw
    } finally { $lock.Dispose() }
}
