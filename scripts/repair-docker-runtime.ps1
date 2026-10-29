<#
Recover only the known inaccessible dockerInference socket startup failure.
Docker Desktop must be fully stopped. Runtime folders are preserved, not deleted.
Preview with: .\scripts\repair-docker-runtime.ps1 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = 'Stop'

function Assert-DockerStopped {
    if (Get-Process -Name 'Docker Desktop','com.docker.backend' -ErrorAction SilentlyContinue) {
        throw 'Close Docker Desktop before repairing its runtime sockets.'
    }
}

Assert-DockerStopped
$localRoot = [IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd('\')
$dockerRoot = Join-Path $localRoot 'Docker'
$runRoot = Join-Path $dockerRoot 'run'
$socket = Join-Path $runRoot 'dockerInference'
foreach ($parent in @($localRoot, $dockerRoot)) {
    $item = Get-Item -LiteralPath $parent -Force
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing an unexpected parent path: $parent"
    }
}

$savedPreference = $ErrorActionPreference
try {
    # Windows PowerShell 5 can wrap a native stderr line in NativeCommandError.
    $ErrorActionPreference = 'Continue'
    $probe = (& fsutil reparsepoint query $socket 2>&1 | Out-String)
    $probeExit = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $savedPreference
}
if ($probeExit -eq 0 -or $probe -notmatch '1920') {
    throw 'The exact inaccessible-socket condition (Windows error 1920) was not confirmed. No folders changed.'
}
$logPath = Join-Path $dockerRoot 'log\host\com.docker.backend.exe.log'
$log = Get-Item -LiteralPath $logPath
$recentFailure = (Get-Content -LiteralPath $logPath -Tail 250 | Out-String)
if ($log.LastWriteTimeUtc -lt [DateTime]::UtcNow.AddHours(-24) -or
    $recentFailure -notmatch 'initializing Inference manager' -or
    $recentFailure -notmatch 'dockerInference.*cannot be accessed') {
    throw 'No recent matching Docker startup failure was found. No folders changed.'
}

$stamp = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('n').Substring(0,8)
$plan = @()
foreach ($path in @($runRoot, (Join-Path $localRoot 'docker-secrets-engine'))) {
    if (-not (Test-Path -LiteralPath $path)) { continue }
    $absolute = [IO.Path]::GetFullPath($path)
    $allowed = @([IO.Path]::GetFullPath($runRoot), [IO.Path]::GetFullPath((Join-Path $localRoot 'docker-secrets-engine')))
    if ($absolute -notin $allowed) { throw 'Runtime target escaped its exact allowed path.' }
    $folder = Get-Item -LiteralPath $absolute -Force
    if (-not $folder.PSIsContainer -or ($folder.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing unexpected runtime directory: $absolute"
    }
    $entries = @(Get-ChildItem -LiteralPath $absolute -Force)
    if ($entries | Where-Object { $_.PSIsContainer -or $_.Length -ne 0 -or -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) }) {
        throw "Runtime directory contains unexpected non-socket data: $absolute"
    }
    $saved = $absolute + '.stale-' + $stamp
    if (Test-Path -LiteralPath $saved) { throw 'The preservation path already exists.' }
    $plan += [pscustomobject]@{ Original=$absolute; PreservedAt=$saved; Recreated=$false; SocketCount=$entries.Count }
}
if (-not $plan.Count) { throw 'No confirmed runtime directories to recover.' }
if ($PSCmdlet.ShouldProcess(($plan.Original -join ', '), 'Preserve stale runtime directories under unique sibling names and recreate empty directories')) {
    $evidence = Join-Path (Split-Path -Parent $PSScriptRoot) "archive\docker-runtime-recovery\$stamp"
    New-Item -ItemType Directory -Path $evidence -Force | Out-Null
    $manifest = Join-Path $evidence 'runtime-folder-repair.json'
    $plan | ConvertTo-Json | Set-Content -LiteralPath $manifest
    foreach ($entry in $plan) {
        Assert-DockerStopped
        Rename-Item -LiteralPath $entry.Original -NewName (Split-Path -Leaf $entry.PreservedAt)
        New-Item -ItemType Directory -Path $entry.Original | Out-Null
        $entry.Recreated = $true
        $plan | ConvertTo-Json | Set-Content -LiteralPath $manifest
    }
    Write-Output "Recovered confirmed runtime socket directories. Evidence: $manifest"
    Write-Output 'Original runtime folders are preserved. Start Docker Desktop again.'
}
