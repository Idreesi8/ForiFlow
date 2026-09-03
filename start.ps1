<#
    Everyday start for the ForiFlow stack on this Windows laptop.

        .\start.ps1              start existing images (no rebuild)
        .\start.ps1 -Rebuild     rebuild images, then start

    Double-click start.bat, or the desktop ForiFlow shortcut from
    create-shortcut.bat, so this runs without an ExecutionPolicy prompt.
    After code changes, double-click rebuild.bat (or pass -Rebuild).

    Compose arguments are always passed as an array. A bare "-d" after a
    PowerShell function call is eaten by the parser, so "up -d" becomes
    "up" and the script hangs attached to container logs.
#>
[CmdletBinding()]
param(
    [switch]$Rebuild,
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$frontendUrl = "http://127.0.0.1:3000"
$backendUrl = "http://127.0.0.1:8000"
$timeoutSeconds = 240
$requiredServices = @("db", "backend", "frontend")

# Per-user Docker Desktop is often missing from PATH in a fresh window.
$dockerBin = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin"
if (Test-Path -LiteralPath $dockerBin) {
    $env:PATH = "$dockerBin;$env:PATH"
}

function Write-Step {
    param([string]$Message, [string]$Color = "White")
    Write-Host $Message -ForegroundColor $Color
}

function Invoke-Compose {
    param([Parameter(Mandatory = $true)][string[]]$ComposeArgs)
    & docker compose @ComposeArgs
    return $LASTEXITCODE
}

function Test-DockerEngine {
    $dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $dockerCmd) {
        return $false
    }
    # Full "docker info" enumerates plugins and can exceed 20s on this laptop.
    # Server version is enough to know the engine is up.
    $id = [guid]::NewGuid().ToString("n")
    $outFile = Join-Path $env:TEMP "foriflow-docker-$id.out"
    $errFile = Join-Path $env:TEMP "foriflow-docker-$id.err"
    try {
        $proc = Start-Process -FilePath $dockerCmd.Source `
            -ArgumentList @('version', '-f', '{{.Server.Version}}') `
            -NoNewWindow -PassThru -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        if (-not $proc.WaitForExit(45000)) {
            try { $proc.Kill() } catch { }
            return $false
        }
        # WaitForExit(timeout) can leave ExitCode unset; the version string is the signal.
        $ver = ((Get-Content -LiteralPath $outFile -ErrorAction SilentlyContinue | Out-String).Trim())
        return -not [string]::IsNullOrWhiteSpace($ver)
    } finally {
        Remove-Item -LiteralPath $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-ServiceHealth {
    $raw = & docker compose ps --format json 2>$null
    $map = @{}
    foreach ($line in @($raw)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try {
            $item = $line | ConvertFrom-Json
        } catch {
            continue
        }
        if ($item.Service) {
            $map[$item.Service] = [string]$item.Health
        }
    }
    return $map
}

if ($NoBuild -and $Rebuild) {
    Write-Step "-NoBuild and -Rebuild cannot be used together." "Red"
    exit 1
}

Write-Step "=== ForiFlow start ===" "Cyan"
Write-Step "[1/6] Checking Docker Desktop..."

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Step "Docker was not found on PATH." "Red"
    Write-Step "Install Docker Desktop, start it, wait for the whale icon to settle, then run this again."
    exit 1
}

docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Step "Docker Compose was not found." "Red"
    Write-Step "Update Docker Desktop to a version that includes Compose v2, then run this again."
    exit 1
}

if (-not (Test-DockerEngine)) {
    Write-Step "Docker Desktop is not running (or the engine is still starting)." "Red"
    Write-Step "Start Docker Desktop, wait for the whale icon to settle, then double-click start.bat again."
    exit 1
}

Write-Step "Docker engine is up." "Green"

if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot ".env"))) {
    Write-Step "No .env file in the repo root." "Red"
    Write-Step "Copy .env.example to .env and fill POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, and JWT_SECRET_KEY."
    exit 1
}

if ($Rebuild) {
    Write-Step "[2/6] Rebuilding images, then starting (docker compose up -d --build)..."
    $upArgs = @("up", "-d", "--build")
} else {
    Write-Step "[2/6] Starting existing images (docker compose up -d, no rebuild)..."
    $upArgs = @("up", "-d")
}

$upExit = Invoke-Compose $upArgs
if ($upExit -ne 0) {
    Write-Step "docker compose up failed. Inspect the output above." "Red"
    exit 1
}

Write-Step "[3/6] Waiting for db, backend, and frontend to report healthy..."
Write-Step "(Backend start_period is 120s while the ensemble loads. Polling compose health, not a fixed sleep.)"

$deadline = (Get-Date).AddSeconds($timeoutSeconds)
$healthy = $false
while ((Get-Date) -lt $deadline) {
    $health = Get-ServiceHealth
    $parts = foreach ($name in $requiredServices) {
        $state = $health[$name]
        if ([string]::IsNullOrWhiteSpace($state)) { $state = "missing" }
        "${name}=$state"
    }
    Write-Host ("  " + ($parts -join "  "))
    $allHealthy = $true
    foreach ($name in $requiredServices) {
        if ($health[$name] -ne "healthy") { $allHealthy = $false }
    }
    if ($allHealthy) {
        $healthy = $true
        break
    }
    Start-Sleep -Seconds 5
}

if (-not $healthy) {
    $health = Get-ServiceHealth
    Write-Step "Timed out after ${timeoutSeconds}s waiting for all services to become healthy." "Red"
    foreach ($name in $requiredServices) {
        $state = $health[$name]
        if ([string]::IsNullOrWhiteSpace($state)) { $state = "missing" }
        Write-Host "  $name : $state"
    }
    Write-Step "Check logs with: docker compose logs"
    exit 1
}

Write-Step "All three services are healthy." "Green"

Write-Step "[4/6] Checking whether an officer user already exists..."
$userCount = $null
try {
    $countOutput = & docker compose exec -T backend python -c "from sqlalchemy import select, func; from models.database import SessionLocal, User; db = SessionLocal(); print(db.scalar(select(func.count()).select_from(User))); db.close()"
    if ($LASTEXITCODE -eq 0) {
        $match = @(
            $countOutput |
                ForEach-Object { "$_".Trim() } |
                Where-Object { $_ -match '^\d+$' }
        ) | Select-Object -Last 1
        if ($null -ne $match) { $userCount = [int]$match }
    }
} catch {
    $userCount = $null
}

if ($userCount -gt 0) {
    Write-Step "Found $userCount officer user(s). You can log in at the dashboard." "Green"
} else {
    Write-Step "No admin user found - run: docker compose exec backend python -m scripts.seed_admin" "Yellow"
    Write-Step "Set FORIFLOW_ADMIN_PASSWORD in .env first. Seeding is not run automatically."
}

Write-Step "[5/6] Opening $frontendUrl in the default browser..."
try {
    Start-Process $frontendUrl
} catch {
    Write-Step "Could not open the browser automatically. Open $frontendUrl yourself." "Yellow"
}

Write-Step "[6/6] Ready." "Green"
Write-Host ""
Write-Host "Dashboard : $frontendUrl"
Write-Host "API       : $backendUrl"
Write-Host "API docs  : $backendUrl/docs"
Write-Host "Stop      : docker compose down"
Write-Host ""
Write-Host "Postgres, the API, and the dashboard are bound to 127.0.0.1 only."
Write-Host "They are not reachable from other machines on the network."
Write-Host ""
