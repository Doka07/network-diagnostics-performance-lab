param(
    [Parameter(Mandatory=$true)]
    [string]$OutputDirectory
)

# Manual read-only discovery; only private artifact files are written.
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $OutputDirectory) {
    if ((Get-Item -LiteralPath $OutputDirectory).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Output directory must not be a reparse point.'
    }
    if (@(Get-ChildItem -LiteralPath $OutputDirectory -Force).Count -gt 0) {
        throw 'Output directory must be empty.'
    }
} else {
    New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
}

$queries = [ordered]@{
    os = { Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber }
    adapters = { Get-NetAdapter | Select-Object Name,Status,LinkSpeed,InterfaceDescription,InterfaceIndex }
    addresses = { Get-NetIPAddress -AddressFamily IPv4 }
    routes = { Get-NetRoute -AddressFamily IPv4 }
    tcp_global = { netsh int tcp show global }
    rss = { Get-NetAdapterRss }
    adapter_properties = { Get-NetAdapterAdvancedProperty -Name 'Ethernet 4' }
    adapter_statistics = { Get-NetAdapterStatistics -Name 'Ethernet 4' }
    clock = { w32tm /query /status }
    python = { python --version }
    iperf3 = { Get-Command iperf3 -ErrorAction Stop | Select-Object Source,Version }
}
$results = [ordered]@{}
foreach ($name in $queries.Keys) {
    try {
        $value = & $queries[$name]
        $results[$name] = @{ status='ok'; value=$value }
    } catch {
        $results[$name] = @{ status='unavailable'; reason=$_.Exception.Message }
    }
}
$record = [ordered]@{
    schema_version = 'inventory-1.0'
    host_id = 'windows-receiver'
    captured_at_utc = [DateTime]::UtcNow.ToString('o')
    commands = $results
    physical_topology = 'requires operator confirmation'
}
$path = Join-Path $OutputDirectory 'environment.json'
$record | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $path -Encoding UTF8
$digest = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
"$digest  environment.json" | Set-Content -LiteralPath (Join-Path $OutputDirectory 'SHA256SUMS')
Write-Output "Private inventory saved: $path"
