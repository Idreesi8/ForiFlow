<#
    One-command start for the ForiFlow demo stack on native Windows PowerShell.
    Identical behaviour to start.sh, for laptops without Git Bash.

        .\start.ps1              build if needed and start in the background
        .\start.ps1 -NoBuild     skip the image build

    If PowerShell blocks the script, either run
        powershell -ExecutionPolicy Bypass -File .\start.ps1
    or unblock it once with
        Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#>
[CmdletBinding()]
param([switch]$NoBuild)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$frontendUrl = "http://localhost:3000"
$backendUrl = "http://localhost:8000"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker was not found on PATH. Install Docker Desktop for Windows, then reopen this terminal."
    exit 1
}

# Compose v2 ships as a "docker compose" subcommand; v1 as its own binary.
docker compose version *> $null
if ($LASTEXITCODE -eq 0) {
    $composeArgs = @("compose")
} elseif (Get-Command docker-compose -ErrorAction SilentlyContinue) {
    $composeArgs = $null
} else {
    Write-Error "Docker Compose was not found. Update Docker Desktop to a version that includes Compose v2."
    exit 1
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    if ($null -ne $composeArgs) { & docker ($composeArgs + $Arguments) } else { & docker-compose $Arguments }
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Error "The Docker daemon is not responding. Start Docker Desktop, wait for the whale icon to settle, and run this again."
    exit 1
}

Write-Host "Starting ForiFlow (first build downloads ~1.5 GB of Python wheels)..."
if ($NoBuild) { Invoke-Compose up -d } else { Invoke-Compose up -d --build }
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker compose up failed. Inspect the output above."
    exit 1
}

# The backend loads the trained ensemble, scaler and SHAP explainer before it
# serves anything, so announcing the URL immediately would be premature.
Write-Host -NoNewline "Waiting for the scoring engine to load"
$ready = $false
foreach ($attempt in 1..60) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$backendUrl/health" -TimeoutSec 3
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch {
        # Not up yet; keep polling.
    }
    Write-Host -NoNewline "."
    Start-Sleep -Seconds 3
}
Write-Host ""

if (-not $ready) {
    Write-Warning "The backend did not report healthy in time. Check the logs with: docker compose logs backend"
    exit 1
}

Write-Host ""
Write-Host "ForiFlow is running at $frontendUrl" -ForegroundColor Green
Write-Host "  API docs:  $backendUrl/docs"
Write-Host "  Logs:      docker compose logs -f"
Write-Host "  Stop:      docker compose down"
