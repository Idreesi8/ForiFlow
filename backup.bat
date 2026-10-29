@echo off
setlocal
rem Back up the ForiFlow database to backups\foriflow-YYYYMMDD-HHMMSS.dump.
rem Read-only for the database. ForiFlow must be running (start.bat).
rem   backup.bat            (pauses at the end when double-clicked)
rem   backup.bat --no-pause (for other scripts)
cd /d "%~dp0"
if not exist backups mkdir backups
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set STAMP=%%T
for /f %%I in ('powershell -NoProfile -Command "[guid]::NewGuid().ToString('N')"') do set RUN_ID=%%I
if not defined RUN_ID exit /b 1
set FILE=backups\foriflow-%STAMP%-%RUN_ID%.dump
set CHECK=/tmp/foriflow-backup-check-%RUN_ID%.dump
if exist "%FILE%" exit /b 1
echo Backing up the ForiFlow database to %FILE% ...
docker compose exec -T db sh -c "pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -Fc" > "%FILE%"
if errorlevel 1 goto failed
for %%A in ("%FILE%") do if %%~zA LSS 1000 goto failed
rem Prove the file is a readable archive, inside the container.
docker compose cp "%FILE%" db:%CHECK% >nul
if errorlevel 1 goto failed
docker compose exec -T db sh -c "pg_restore --list '%CHECK%' > /dev/null; rc=$?; rm -f '%CHECK%'; exit $rc"
if errorlevel 1 goto failed
echo Backup OK: %FILE%
echo It holds borrower data. Keep a copy off this laptop, encrypted, and test it with verify-backup.bat.
if not "%~1"=="--no-pause" pause
exit /b 0

:failed
docker compose exec -T db rm -f %CHECK% >nul 2>&1
echo BACKUP FAILED. Is ForiFlow running (start.bat)? The database was not changed.
if exist "%FILE%" del "%FILE%"
if not "%~1"=="--no-pause" pause
exit /b 1
