<#
    Creates a desktop shortcut that double-click starts ForiFlow.

    Target: start.bat in this repo (ExecutionPolicy Bypass, then start.ps1).
#>
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$dockerBin = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin"
if (Test-Path -LiteralPath $dockerBin) {
    $env:PATH = "$dockerBin;$env:PATH"
}

$startBat = Join-Path $PSScriptRoot "start.bat"
if (-not (Test-Path -LiteralPath $startBat)) {
    Write-Host "start.bat was not found next to this script." -ForegroundColor Red
    exit 1
}

$desktop = [Environment]::GetFolderPath("Desktop")
$linkPath = Join-Path $desktop "ForiFlow.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($linkPath)
$shortcut.TargetPath = $startBat
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.WindowStyle = 1
$shortcut.Description = "Start ForiFlow and open http://127.0.0.1:3000"
$iconCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\Docker Desktop.exe"),
    (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe")
)
foreach ($icon in $iconCandidates) {
    if (Test-Path -LiteralPath $icon) {
        $shortcut.IconLocation = $icon
        break
    }
}
$shortcut.Save()

Write-Host "Desktop shortcut created:" -ForegroundColor Green
Write-Host "  $linkPath"
Write-Host "  Target: $startBat"
Write-Host "  Start in: $PSScriptRoot"
Write-Host ""
Write-Host "Double-click ForiFlow on the desktop. Keep Docker Desktop running (whale icon settled)."
