@echo off
setlocal
rem Restore a backup into a SCRATCH database, compare it with the live one,
rem then drop the scratch copy. The live database is only read.
rem   verify-backup.bat                       (newest file in backups\)
rem   verify-backup.bat backups\file.dump
cd /d "%~dp0"
set FILE=%~1
if "%FILE%"=="" for /f "delims=" %%F in ('dir /b /o-d backups\*.dump 2^>nul') do if not defined FILE set FILE=backups\%%F
if "%FILE%"=="" (
    echo No backup found in backups\. Run backup.bat first.
    if not "%~2"=="--no-pause" pause
    exit /b 1
)
if not exist "%FILE%" (
    echo File not found: %FILE%
    if not "%~2"=="--no-pause" pause
    exit /b 1
)
set LOG=verify-backup-log.txt
for /f %%I in ('powershell -NoProfile -Command "[guid]::NewGuid().ToString('N')"') do set RUN_ID=%%I
if not defined RUN_ID exit /b 1
set "VDUMP=/tmp/foriflow-verify-%RUN_ID%.dump"
echo Verifying %FILE% > %LOG%
docker compose cp "%FILE%" db:%VDUMP% >> %LOG% 2>&1
if errorlevel 1 goto verify_failed
docker compose exec -T db sh -c "test -s '%VDUMP%' && pg_restore --list '%VDUMP%' > /dev/null" >> %LOG% 2>&1
if errorlevel 1 goto verify_failed
docker compose exec -T -e DUMP=%VDUMP% db sh -s < scripts\db\verify-restore.sh >> %LOG% 2>&1
set RC=%ERRORLEVEL%
docker compose exec -T db rm -f %VDUMP% >nul 2>&1
type %LOG%
if not "%RC%"=="0" (
    echo VERIFY FAILED. See %LOG%.
    if not "%~2"=="--no-pause" pause
    exit /b 1
)
echo Verify OK. Details in %LOG%.
if not "%~2"=="--no-pause" pause
exit /b 0

:verify_failed
docker compose exec -T db rm -f %VDUMP% >nul 2>&1
type %LOG%
echo VERIFY FAILED before scratch restore. The live database was not changed.
if not "%~2"=="--no-pause" pause
exit /b 1
