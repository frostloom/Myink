param([Parameter(Mandatory=$true)][string]$Root, [string]$Distribution='MyinkPiLab', [switch]$AdoptPrepared)
$ErrorActionPreference='Stop'
$receipt=@{schema_version=1; status='blocked'; root=$Root; distribution=$Distribution}
try {
    $absolute=[System.IO.Path]::GetFullPath($Root)
    if ($absolute -notmatch '^E:\\' -or $Root -match '(?:^|[\\/])\.\.(?:[\\/]|$)') { throw 'E drive required' }
    $receipt.root=$absolute
    $receipt.host_free_bytes=(Get-PSDrive E).Free
    if ($receipt.host_free_bytes -lt (5GB + 2GB)) { throw 'peak plus 5GiB required' }
    $memory=Get-CimInstance Win32_OperatingSystem
    $receipt.host_available_bytes=[int64]$memory.FreePhysicalMemory * 1024
    $receipt.wsl_version=(& wsl.exe --version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'WSL unavailable' }
    $distributions=(& wsl.exe --list --quiet | Out-String) -replace "`0",''
    $receipt.existing_distribution=$distributions.Split("`n").Trim() -contains $Distribution
    if ($receipt.existing_distribution -and -not $AdoptPrepared) { throw 'distribution collision' }
    if ($AdoptPrepared) {
        if ($Distribution -ne 'MyinkPiLab' -or $absolute.TrimEnd('\') -ne 'E:\tools\myink-pi') { throw 'unknown preparation' }
        $registry=Get-ChildItem HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss | ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object DistributionName -eq $Distribution
        if (!$registry -or $registry.BasePath -notlike '*E:\tools\myink-pi\runtime\wsl*') { throw 'physical VHD path mismatch' }
        $receipt.vhd_path=$registry.BasePath
        $prepared=Get-Content -LiteralPath (Join-Path $absolute 'evidence\lab-daemon-initial.json') -Raw | ConvertFrom-Json
        $info=(& wsl.exe -d $Distribution -u root -- docker --host unix:///var/run/docker.sock info --format '{{json .}}' | Out-String) | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or $prepared.ID -ne '364e8400-3844-47e2-b86d-8b626332f61c' -or $info.ID -ne $prepared.ID -or $info.CgroupVersion -ne '2' -or $info.CgroupDriver -ne 'systemd' -or $info.ServerVersion -ne $prepared.ServerVersion) { throw 'private daemon mismatch' }
        $receipt.daemon_id=$info.ID
        $receipt.docker_version=$info.ServerVersion
        $receipt.kernel=(& wsl.exe -d $Distribution -- uname -r | Out-String).Trim()
        $receipt.guest_free_bytes=[int64]((& wsl.exe -d $Distribution -- df --output=avail -B1 /opt | Select-Object -Last 1).Trim())
        if ($receipt.guest_free_bytes -lt (5GB + 2GB)) { throw 'guest peak plus 5GiB required' }
    }
    $receipt.status='done'
    $receipt | ConvertTo-Json -Depth 8 -Compress
    exit 0
} catch {
    $receipt.reason=$_.Exception.Message
    $receipt | ConvertTo-Json -Depth 8 -Compress
    exit 1
}
