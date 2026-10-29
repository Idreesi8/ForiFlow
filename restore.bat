@echo off
setlocal
rem DESTRUCTIVE: replace the live ForiFlow database with a backup.
rem It first takes a safety backup of the current database, asks you to type
rem RESTORE, stops the API and dashboard, restores, and starts them again.
rem   restore.bat backups\foriflow-YYYYMMDD-HHMMSS.dump
cd /d "%~dp0"
set FILE=%~1
if "%FILE%"=="" (
    echo Usage: restore.bat backups\file.dump
    echo Tip: run verify-backup.bat on the file first.
    if not "%~2"=="--no-pause" pause
    exit /b 1
)
if not exist "%FILE%" (
    echo File not found: %FILE%
    if not "%~2"=="--no-pause" pause
    exit /b 1
)
echo This REPLACES the live ForiFlow database with %FILE%.
echo Everything recorded after that backup was taken will be gone from the live database.
set /p ANSWER=Type RESTORE to continue, anything else to cancel: 
if not "%ANSWER%"=="RESTORE" (
    echo Cancelled. Nothing was changed.
    if not "%~2"=="--no-pause" pause
    exit /b 1
)
echo Step 1 of 4: safety backup of the current database...
call backup.bat --no-pause
if errorlevel 1 (
    echo The safety backup failed, so nothing was restored.
    if not "%~2"=="--no-pause" pause
    exit /b 1
)
echo Step 2 of 4: stopping the API and dashboard...
docker compose stop backend frontend
if errorlevel 1 goto abort_unchanged
for /f %%I in ('powershell -NoProfile -Command "[guid]::NewGuid().ToString('N')"') do set RUN_ID=%%I
if not defined RUN_ID goto abort_unchanged
set "DUMP=/tmp/foriflow-restore-%RUN_ID%.dump"
set "RUNNING_LIST=%TEMP%\foriflow-running-%RUN_ID%.txt"
docker compose ps -q --status running backend frontend > "%RUNNING_LIST%"
if errorlevel 1 goto abort_unchanged
for %%A in ("%RUNNING_LIST%") do if %%~zA GTR 0 goto abort_unchanged
del "%RUNNING_LIST%" >nul 2>&1
echo Step 3 of 4: restoring...
docker compose cp "%FILE%" db:%DUMP%
if errorlevel 1 goto abort_unchanged
docker compose exec -T db sh -c "test -s '%DUMP%' && pg_restore --list '%DUMP%' > /dev/null"
if errorlevel 1 goto abort_unchanged
docker compose exec -T -e DUMP=%DUMP% -e CONFIRM=RESTORE db sh -s < scripts\db\restore.sh
set RC=%ERRORLEVEL%
docker compose exec -T db rm -f %DUMP% >nul 2>&1
if "%RC%"=="3" goto abort_unchanged
if not "%RC%"=="0" goto restore_partial
echo Step 4 of 4: starting ForiFlow again...
docker compose up -d backend frontend
if errorlevel 1 (
    echo The database was restored, but ForiFlow could not restart. Check docker compose logs.
    if not "%~2"=="--no-pause" pause
    exit /b 1
)
echo Restore done. Wait for the dashboard, then sign in and check recent applications.
if not "%~2"=="--no-pause" pause
exit /b 0

:abort_unchanged
if defined DUMP docker compose exec -T db rm -f %DUMP% >nul 2>&1
if defined RUNNING_LIST if exist "%RUNNING_LIST%" del "%RUNNING_LIST%" >nul 2>&1
echo RESTORE NOT STARTED. A prerequisite failed; the database was not replaced.
docker compose up -d backend frontend
if not "%~2"=="--no-pause" pause
exit /b 1

:restore_partial
echo RESTORE INCOMPLETE. The database may be empty or partly restored.
echo The API and dashboard were left stopped. Recover using the safety backup in backups\.
if not "%~2"=="--no-pause" pause
exit /b 1
