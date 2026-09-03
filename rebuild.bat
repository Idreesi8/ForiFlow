@echo off
setlocal
cd /d "%~dp0"
title ForiFlow rebuild
echo Rebuilding ForiFlow images, then starting...
echo Use this only after code changes. Everyday start is start.bat.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Rebuild %*
set EXITCODE=%ERRORLEVEL%
echo.
if not %EXITCODE%==0 (
  echo ForiFlow rebuild/start did not finish. Read the messages above.
)
pause
exit /b %EXITCODE%
