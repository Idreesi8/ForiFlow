<# Runs tests against a private, disposable PostgreSQL cluster on loopback.
   The runtime lives in .local; no Windows service or existing database is used.
   Example: .\scripts\test-postgres.ps1 -PytestArgs @('-m','postgres','-q')
#>
[CmdletBinding()]
param(
    [string]$BinaryDirectory,
    [ValidateRange(1024, 65535)][int]$Port = 55432,
    [string[]]$PytestArgs = @('-q', '--tb=short')
)
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $BinaryDirectory) { $BinaryDirectory = Join-Path $repoRoot '.local\postgresql-16.15\pgsql\bin' }
$BinaryDirectory = [IO.Path]::GetFullPath($BinaryDirectory)
foreach ($toolName in @('initdb.exe', 'pg_ctl.exe', 'createdb.exe', 'pg_dump.exe', 'pg_restore.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path $BinaryDirectory $toolName))) {
        throw "PostgreSQL tools missing. Pass -BinaryDirectory with an official PostgreSQL bin directory."
    }
}
$runId = [guid]::NewGuid().ToString('N')
$runsRoot = Join-Path $repoRoot '.local\postgres-tests'
$runRoot = [IO.Path]::GetFullPath((Join-Path $runsRoot $runId))
$dataRoot = Join-Path $runRoot 'data'
$evidenceRoot = Join-Path $repoRoot ('archive\postgres-tests\' + $runId)
$passwordFile = Join-Path $runRoot 'init-password.txt'
$serverLog = Join-Path $runRoot 'server.log'
$databaseName = 'foriflow_test_' + $runId
$names = @('PATH', 'PGPASSWORD', 'PGHOST', 'PGPORT', 'PGUSER', 'FORIFLOW_TEST_POSTGRES_URL')
$saved = @{}
foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$started = $false
$startAttempted = $false
$stopped = $false
$result = 1
New-Item -ItemType Directory -Path $runRoot, $evidenceRoot | Out-Null
try {
    $env:PATH = $BinaryDirectory + ';' + (Join-Path $env:ProgramFiles 'Git\usr\bin') + ';' + $env:PATH
    $randomBytes = New-Object byte[] 32
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($randomBytes) } finally { $random.Dispose() }
    $testPassword = [BitConverter]::ToString($randomBytes).Replace('-', '')
    [IO.File]::WriteAllText($passwordFile, $testPassword, (New-Object Text.UTF8Encoding($false)))
    & (Join-Path $BinaryDirectory 'initdb.exe') -D $dataRoot -U foriflow_test_admin --auth=scram-sha-256 --pwfile=$passwordFile --locale=C --encoding=UTF8 *> (Join-Path $evidenceRoot 'initdb.log')
    if ($LASTEXITCODE -ne 0) { throw "Private PostgreSQL initialization failed. See $evidenceRoot" }
    Remove-Item -LiteralPath $passwordFile
    $startArgs = @('-D', ('"' + $dataRoot + '"'), '-l', ('"' + $serverLog + '"'), '-w', 'start', '-o', ('"-h 127.0.0.1 -p ' + $Port + '"'))
    $startAttempted = $true
    $launcher = Start-Process -FilePath (Join-Path $BinaryDirectory 'pg_ctl.exe') -ArgumentList $startArgs -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $evidenceRoot 'start.log') -RedirectStandardError (Join-Path $evidenceRoot 'start-errors.log')
    # -Wait waits for descendant processes too, including the database server.
    # Wait only for pg_ctl itself; its -w flag checks server readiness.
    if (-not $launcher.WaitForExit(65000)) {
        $launcher.Kill()
        $launcher.WaitForExit()
        throw 'Private PostgreSQL startup timed out.'
    }
    $launcher.WaitForExit()
    if ($launcher.ExitCode -ne 0) { throw "Private PostgreSQL startup failed. See $evidenceRoot" }
    $started = $true
    $env:PGPASSWORD = $testPassword
    $env:PGHOST = '127.0.0.1'
    $env:PGPORT = [string]$Port
    $env:PGUSER = 'foriflow_test_admin'
    & (Join-Path $BinaryDirectory 'createdb.exe') $databaseName
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the private test database.' }
    $env:FORIFLOW_TEST_POSTGRES_URL = 'postgresql+psycopg2://foriflow_test_admin:' + $testPassword + '@127.0.0.1:' + $Port + '/' + $databaseName
    Write-Host "Running tests on a new private PostgreSQL cluster, port $Port."
    Push-Location (Join-Path $repoRoot 'backend')
    try {
        & python -u -m pytest @PytestArgs 2>&1 | Tee-Object -FilePath (Join-Path $evidenceRoot 'pytest.log')
        $result = $LASTEXITCODE
    } finally { Pop-Location }
} finally {
    if ($startAttempted) {
        & (Join-Path $BinaryDirectory 'pg_ctl.exe') -D $dataRoot -w stop -m fast *> (Join-Path $evidenceRoot 'stop.log')
        $stopped = $LASTEXITCODE -eq 0
        if (-not $stopped) {
            & (Join-Path $BinaryDirectory 'pg_ctl.exe') -D $dataRoot status *> (Join-Path $evidenceRoot 'final-status.log')
            $stopped = $LASTEXITCODE -eq 3
        }
        if (-not $stopped) { Write-Warning 'The private server did not stop; its test data was retained.'; $result = 1 }
    }
    if (Test-Path -LiteralPath $serverLog) { Copy-Item -LiteralPath $serverLog -Destination (Join-Path $evidenceRoot 'server.log') }
    if (Test-Path -LiteralPath $passwordFile) { Remove-Item -LiteralPath $passwordFile }
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
    # Delete only this invocation's generated data after a successful shutdown.
    $resolvedRun = [IO.Path]::GetFullPath($runRoot)
    if (($stopped -or -not $startAttempted) -and $resolvedRun -eq (Join-Path $runsRoot $runId) -and $resolvedRun.StartsWith($repoRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $resolvedRun -Recurse
    }
    Write-Host "Verification logs: $evidenceRoot"
}
exit $result
