@echo off
setlocal
cd /d "%~dp0"
title ForiFlow shortcut
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0create-shortcut.ps1"
set EXITCODE=%ERRORLEVEL%
echo.
if not %EXITCODE%==0 (
  echo Could not create the desktop shortcut. Read the messages above.
)
pause
exit /b %EXITCODE%
