# Operator helper. Requires explicit owner authorization before remote execution.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('Start','Stop','Cleanup','Capture')][string]$Action,
    [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{32}$')][string]$Token,
    [Parameter(Mandatory)][string]$LocalAddress,
    [Parameter(Mandatory)][string]$PeerAddress,
    [Parameter(Mandatory)][string]$InterfaceAlias,
    [ValidateRange(1024,65535)][int]$Port = 5201
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
foreach ($address in @($LocalAddress, $PeerAddress)) {
    $parsed = [System.Net.IPAddress]::Parse($address)
    if ($parsed.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
        throw 'IPv4 required'
    }
}
if ($LocalAddress -eq $PeerAddress) { throw 'Distinct endpoints required' }
Import-Module NetSecurity -ErrorAction Stop
Import-Module NetTCPIP -ErrorAction Stop
$directory = Join-Path $env:TEMP "ndpl-receiver-$Token"
$ruleName = "DiagLab-Receiver-$Token"
$marker = "NDPL owner $Token"

function Read-Owner {
    if (!(Test-Path -LiteralPath $directory -PathType Container)) { throw 'Owner directory missing' }
    if ((Get-Item -LiteralPath $directory).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Reparse owner directory refused'
    }
    if ((Get-Item -LiteralPath "$directory\owner.json").Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Reparse owner file refused'
    }
    $owner = Get-Content -LiteralPath "$directory\owner.json" -Raw | ConvertFrom-Json
    if ($owner.token -ne $Token -or $owner.local_address -ne $LocalAddress -or
        $owner.peer_address -ne $PeerAddress -or $owner.interface -ne $InterfaceAlias -or
        $owner.port -ne $Port) { throw 'Owner parameters differ' }
    return $owner
}

function Cleanup-Owned {
    $owner = Read-Owner
    $issues = [System.Collections.Generic.List[string]]::new()
    $processGone = $false
    $ruleGone = $false
    $listenerGone = $false
    try {
        if (!$owner.pid -and $owner.launch_attempted) {
            throw 'Launch attempted without persisted process identity; cleanup unverified'
        }
        $process = if ($owner.pid) { Get-Process -Id $owner.pid -ErrorAction SilentlyContinue }
        if ($process) {
            if ([string]$process.StartTime.ToUniversalTime().Ticks -ne [string]$owner.start_ticks -or
                $process.Path -ne $owner.executable) { throw 'Process identity mismatch' }
            Stop-Process -Id $process.Id -Force
            [void]$process.WaitForExit(5000)
        }
        $processGone = !$owner.pid -or !(Get-Process -Id $owner.pid -ErrorAction SilentlyContinue)
    } catch { $issues.Add($_.Exception.Message) }
    try {
        $rule = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
        if ($rule) {
            $ports = $rule | Get-NetFirewallPortFilter
            $addresses = $rule | Get-NetFirewallAddressFilter
            $interfaces = $rule | Get-NetFirewallInterfaceFilter
            if ($rule.Description -ne $marker -or $rule.Direction -ne 'Inbound' -or
                $rule.Action -ne 'Allow' -or $ports.Protocol -ne 'TCP' -or
                $ports.LocalPort -ne "$Port" -or $addresses.LocalAddress -ne $LocalAddress -or
                $addresses.RemoteAddress -ne $PeerAddress -or
                $interfaces.InterfaceAlias -ne $InterfaceAlias) { throw 'Firewall identity mismatch' }
            $rule | Remove-NetFirewallRule
        }
        $ruleGone = !(Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue)
    } catch { $issues.Add($_.Exception.Message) }
    try {
        $listenerGone = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue).Count -eq 0
    } catch { $issues.Add($_.Exception.Message) }
    $status = [ordered]@{process_gone=$processGone; listener_gone=$listenerGone; rule_gone=$ruleGone}
    $status | ConvertTo-Json | Set-Content -LiteralPath "$directory\cleanup.json" -Encoding UTF8
    # Save diagnostics separately from the strict cleanup wire record (PowerShell 5 compatible).
    ConvertTo-Json -InputObject @($issues.ToArray()) | Set-Content -LiteralPath "$directory\cleanup-errors.json" -Encoding UTF8
    return $status
}

switch ($Action) {
    'Start' {
        if (Test-Path -LiteralPath $directory) { throw 'Receiver directory already exists' }
        if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) { throw 'Rule exists' }
        if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw 'Port occupied' }
        if (!(Get-NetIPAddress -InterfaceAlias $InterfaceAlias -AddressFamily IPv4 |
            Where-Object IPAddress -eq $LocalAddress)) { throw 'Interface address mismatch' }
        $executable = (Get-Command iperf3 -CommandType Application).Source
        $helperHash = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
        New-Item -ItemType Directory -Path $directory | Out-Null
        $owner = [ordered]@{token=$Token; local_address=$LocalAddress; peer_address=$PeerAddress;
            interface=$InterfaceAlias; port=$Port; executable=$executable; pid=$null; start_ticks=$null;
            launch_attempted=$false; helper_sha256=$helperHash}
        $owner | ConvertTo-Json | Set-Content -LiteralPath "$directory\owner.json" -Encoding UTF8
        $process = $null
        try {
            New-NetFirewallRule -Name $ruleName -DisplayName 'DiagLab temporary receiver' -Description $marker `
                -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -LocalAddress $LocalAddress `
                -RemoteAddress $PeerAddress -InterfaceAlias $InterfaceAlias -Profile Any | Out-Null
            # Persist uncertainty before launch: a failed identity write must never
            # leave pid=null interpreted as proof that no receiver was started.
            $owner.launch_attempted = $true
            $owner | ConvertTo-Json | Set-Content -LiteralPath "$directory\owner.json" -Encoding UTF8
            $process = Start-Process -FilePath $executable -ArgumentList @('-s','-B',$LocalAddress,
                '-p',"$Port",'--server-max-duration','35','-J') -PassThru `
                -RedirectStandardOutput "$directory\server.jsonl" -RedirectStandardError "$directory\server.stderr"
            $owner.pid = $process.Id
            $owner.start_ticks = [string]$process.StartTime.ToUniversalTime().Ticks
            $owner | ConvertTo-Json | Set-Content -LiteralPath "$directory\owner.json" -Encoding UTF8
            $deadline = (Get-Date).AddSeconds(240)
            $ready = $false
            while ((Get-Date) -lt $deadline -and !(Test-Path -LiteralPath "$directory\stop")) {
                $process.Refresh()
                if ($process.HasExited) { throw 'Receiver exited before stop' }
                if (!$ready) {
                    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                        Where-Object { $_.OwningProcess -eq $process.Id -and $_.LocalAddress -eq $LocalAddress }
                    if ($listener) {
                        'READY' | Set-Content -LiteralPath "$directory\ready" -Encoding ASCII
                        $ready = $true
                    }
                }
                Start-Sleep -Milliseconds 500
            }
        } finally {
            # Retain the original process object when persisted identity is incomplete.
            # Do not look up and terminate an arbitrary replacement PID here.
            if ($process) {
                try {
                    if (!$process.HasExited) {
                        $process.Kill()
                        [void]$process.WaitForExit(5000)
                    }
                } catch {
                    Write-Warning 'In-memory process cleanup failed; independent verification required'
                }
            }
            $status = Cleanup-Owned
            if (!$status.process_gone -or !$status.listener_gone -or !$status.rule_gone) {
                throw 'Receiver cleanup unverified; independent cleanup required'
            }
        }
    }
    'Stop' {
        $null = Read-Owner
        New-Item -ItemType File -Path "$directory\stop" -Force | Out-Null
    }
    'Cleanup' { Cleanup-Owned | ConvertTo-Json }
    'Capture' {
        $owner = Read-Owner
        if (!$owner.pid -and $owner.launch_attempted) {
            throw 'Cannot confirm receiver termination without persisted identity'
        }
        $candidate = if ($owner.pid) { Get-Process -Id $owner.pid -ErrorAction SilentlyContinue }
        if ($candidate -and $candidate.Path -eq $owner.executable) {
            # Same executable with different ticks is ambiguous, not proof that
            # the original receiver is gone. Do not hash possibly live logs.
            throw 'Refusing capture while receiver executable owns the recorded PID'
        }
        $files = @{}
        $entries = @()
        $missing = @()
        $totalBytes = 0
        foreach ($name in @('owner.json','server.jsonl','server.stderr','cleanup.json')) {
            $path = Join-Path $directory $name
            if (!(Test-Path -LiteralPath $path -PathType Leaf)) { $missing += $name; continue }
            if ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Reparse evidence refused'
            }
            $bytes = [IO.File]::ReadAllBytes($path)
            $totalBytes += $bytes.Length
            if ($totalBytes -gt 4194304) { throw 'Receiver evidence exceeds capture limit' }
            $sha = [Security.Cryptography.SHA256]::Create()
            try { $digest = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant() }
            finally { $sha.Dispose() }
            $files[$name] = [Convert]::ToBase64String($bytes)
            $entries += @{path=$name; size_bytes=$bytes.Length; sha256=$digest}
        }
        $manifest = @{files=@($entries)}
        $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$directory\evidence-manifest.json" -Encoding UTF8
        @{files=$files; manifest=$manifest; missing_files=@($missing)} | ConvertTo-Json -Depth 6 -Compress
    }
}
