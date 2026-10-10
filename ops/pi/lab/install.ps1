param([Parameter(Mandatory=$true)][string]$Root, [string]$Distribution='MyinkPiLab', [string]$Rootfs, [string]$Sha256, [switch]$VerifyOnly)
$ErrorActionPreference='Stop'
$receipt=@{schema_version=1;status='blocked';root=$Root;distribution=$Distribution}
try {
    $absolute=[System.IO.Path]::GetFullPath($Root)
    if ($absolute.TrimEnd('\') -ne 'E:\tools\myink-pi' -or $Root -match '(?:^|[\\/])\.\.(?:[\\/]|$)' -or $Distribution -ne 'MyinkPiLab') { throw 'explicit owned E root and distribution required' }
    $expected='bb415d824822c4b878125729af451a5d18fb13d1cf5cbed9a7393ad64ac6039e'
    $receipt.official_manifest='https://cdimage.ubuntu.com/ubuntu-wsl/noble/daily-live/current/SHA256SUMS'
    $receipt.official_filename='noble-wsl-amd64.wsl'
    if (!$Rootfs -or [System.IO.Path]::GetFullPath($Rootfs) -notlike 'E:\tools\myink-pi\cache\*') { throw 'rootfs must be in private E cache' }
    $item=Get-Item -LiteralPath $Rootfs
    if ($item.LinkType -or $item.PSIsContainer) { throw 'rootfs links rejected' }
    # Reviewed official Canonical manifest pin; the caller's SHA cannot bless a different image.
    $stream=[System.IO.File]::OpenRead($item.FullName)
    $hasher=[System.Security.Cryptography.SHA256]::Create()
    try { $actual=([System.BitConverter]::ToString($hasher.ComputeHash($stream))).Replace('-','').ToLowerInvariant() } finally { $stream.Dispose(); $hasher.Dispose() }
    if ($actual -ne $expected -or ($Sha256 -and $Sha256.ToLowerInvariant() -ne $expected)) { throw 'official rootfs integrity mismatch' }
    for ($cursor=$item.Directory; $cursor; $cursor=$cursor.Parent) {
        if ($cursor.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { throw 'rootfs ancestor links rejected' }
        if ($cursor.FullName -eq 'E:\tools\myink-pi\cache') { break }
    }
    $manifest=(Invoke-WebRequest -Uri $receipt.official_manifest -UseBasicParsing -TimeoutSec 60).Content
    $line=($manifest -split "`n" | Where-Object { $_ -match '^[0-9a-f]{64}\s+\*?noble-wsl-amd64\.wsl$' })
    if (!$line -or ($line -split '\s+')[0] -ne $expected) { throw 'official manifest pin mismatch' }
    $receipt.rootfs_sha256=$expected
    if ($VerifyOnly) { $receipt.status='done';$receipt | ConvertTo-Json -Compress;exit 0 }
    & $PSScriptRoot\preflight.ps1 -Root $absolute -Distribution $Distribution
    if ($LASTEXITCODE -ne 0) { throw 'new environment preflight failed' }
    $target=Join-Path $absolute 'runtime\wsl'
    if (Test-Path -LiteralPath $target) { throw 'installation path collision' }
    $receipt.lab_uuid=[guid]::NewGuid().ToString()
    New-Item -ItemType Directory -Path $target | Out-Null
    & wsl.exe --import $Distribution $target $Rootfs --version 2
    if ($LASTEXITCODE -ne 0) { throw 'import failed' }
    # Recheck ownership of precisely the distribution just imported, never accept arbitrary same-name state.
    $registry=Get-ChildItem HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss | ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object DistributionName -eq $Distribution
    if (!$registry -or $registry.BasePath -notlike "*$target*") { throw 'import ownership mismatch' }
    $bootstrap=Join-Path $absolute 'cache\bootstrap.sh'
    [System.IO.File]::WriteAllText($bootstrap, ([System.IO.File]::ReadAllText((Join-Path $PSScriptRoot 'bootstrap.sh')) -replace "`r`n","`n"), [System.Text.UTF8Encoding]::new($false))
    $native='/mnt/e/'+$bootstrap.Substring(3).Replace('\','/')
    $daemon=(& wsl.exe -d $Distribution -u root -- bash $native | Out-String)
    if ($LASTEXITCODE -ne 0) { throw 'private daemon bootstrap failed' }
    $receipt.daemon_bootstrap='done';$receipt.status='done'
    $receipt.next_action='review fresh daemon identity before runtime adoption'
    $receipt | ConvertTo-Json -Depth 5 -Compress
    $receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $absolute 'installation-receipt.json')
} catch {
    $receipt.reason=$_.Exception.Message
    $receipt | ConvertTo-Json -Compress
    # Do not destroy partial imports; identity/evidence remain for explicit reconciliation.
    if ($absolute -eq 'E:\tools\myink-pi' -and (Test-Path -LiteralPath $absolute)) { $receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $absolute 'installation-failure.json') }
    exit 1
}
