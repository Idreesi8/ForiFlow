@echo off
echo ========================================
echo  ForiFlow Full Automation
echo ========================================
echo.
cd /d C:\Users\LENOVO\Desktop\foriflow
echo Step 1: Installing dependencies...
call npm install
set PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=300000
call npx playwright install chromium
echo.
echo Step 2: Running automation...
node scripts/full-automation.js
echo.
pause
