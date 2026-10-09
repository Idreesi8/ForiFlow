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
    pause
    exit /b 1
)
if not exist "%FILE%" (
    echo File not found: %FILE%
    pause
    exit /b 1
)
set LOG=verify-backup-log.txt
echo Verifying %FILE% > %LOG%
docker compose cp "%FILE%" db:/tmp/foriflow-restore.dump >> %LOG% 2>&1
docker compose exec -T -e DUMP=/tmp/foriflow-restore.dump db sh -s < scripts\db\verify-restore.sh >> %LOG% 2>&1
set RC=%ERRORLEVEL%
docker compose exec -T db rm -f /tmp/foriflow-restore.dump >nul 2>&1
type %LOG%
if not "%RC%"=="0" (
    echo VERIFY FAILED. See %LOG%.
    pause
    exit /b 1
)
echo Verify OK. Details in %LOG%.
pause
exit /b 0
