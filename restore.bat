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
    pause
    exit /b 1
)
if not exist "%FILE%" (
    echo File not found: %FILE%
    pause
    exit /b 1
)
echo This REPLACES the live ForiFlow database with %FILE%.
echo Everything recorded after that backup was taken will be gone from the live database.
set /p ANSWER=Type RESTORE to continue, anything else to cancel: 
if not "%ANSWER%"=="RESTORE" (
    echo Cancelled. Nothing was changed.
    pause
    exit /b 1
)
echo Step 1 of 4: safety backup of the current database...
call backup.bat --no-pause
if errorlevel 1 (
    echo The safety backup failed, so nothing was restored.
    pause
    exit /b 1
)
echo Step 2 of 4: stopping the API and dashboard...
docker compose stop backend frontend
echo Step 3 of 4: restoring...
docker compose cp "%FILE%" db:/tmp/foriflow-restore.dump
docker compose exec -T -e DUMP=/tmp/foriflow-restore.dump -e CONFIRM=RESTORE db sh -s < scripts\db\restore.sh
set RC=%ERRORLEVEL%
docker compose exec -T db rm -f /tmp/foriflow-restore.dump >nul 2>&1
echo Step 4 of 4: starting ForiFlow again...
docker compose up -d backend frontend
if not "%RC%"=="0" (
    echo RESTORE FAILED. The safety backup in backups\ holds the database as it was.
    pause
    exit /b 1
)
echo Restore done. Wait for the dashboard, then sign in and check recent applications.
pause
exit /b 0
