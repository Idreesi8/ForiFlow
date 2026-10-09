@echo off
setlocal
rem Back up the ForiFlow database to backups\foriflow-YYYYMMDD-HHMMSS.dump.
rem Read-only for the database. ForiFlow must be running (start.bat).
rem   backup.bat            (pauses at the end when double-clicked)
rem   backup.bat --no-pause (for other scripts)
cd /d "%~dp0"
if not exist backups mkdir backups
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set STAMP=%%T
set FILE=backups\foriflow-%STAMP%.dump
echo Backing up the ForiFlow database to %FILE% ...
docker compose exec -T db sh -c "pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -Fc" > "%FILE%"
if errorlevel 1 goto failed
for %%A in ("%FILE%") do if %%~zA LSS 1000 goto failed
rem Prove the file is a readable archive, inside the container.
docker compose cp "%FILE%" db:/tmp/foriflow-backup-check.dump >nul
if errorlevel 1 goto failed
docker compose exec -T db sh -c "pg_restore --list /tmp/foriflow-backup-check.dump > /dev/null; rc=$?; rm -f /tmp/foriflow-backup-check.dump; exit $rc"
if errorlevel 1 goto failed
echo Backup OK: %FILE%
echo It holds borrower data. Keep a copy off this laptop, encrypted, and test it with verify-backup.bat.
if not "%~1"=="--no-pause" pause
exit /b 0

:failed
echo BACKUP FAILED. Is ForiFlow running (start.bat)? The database was not changed.
if exist "%FILE%" del "%FILE%"
if not "%~1"=="--no-pause" pause
exit /b 1
