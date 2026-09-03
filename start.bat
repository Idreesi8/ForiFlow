@echo off
setlocal
cd /d "%~dp0"
title ForiFlow
echo Starting ForiFlow (no image rebuild)...
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set EXITCODE=%ERRORLEVEL%
echo.
if not %EXITCODE%==0 (
  echo ForiFlow did not finish starting. Read the messages above.
)
pause
exit /b %EXITCODE%
