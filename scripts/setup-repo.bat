@echo off
setlocal
cd /d "%~dp0\.."

if not exist ".git" (
  git init
  git branch -M main
  echo Initialised a new git repository on main.
) else (
  echo Git repository already present.
)

git add .
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "feat: Production-ready ForiFlow with docs, LinkedIn content, and screenshot automation"
) else (
  echo Nothing new to commit.
)

echo.
echo Push to GitHub: git remote add origin https://github.com/Idreesi8/foriflow.git ^&^& git push -u origin main
echo If origin already exists: git push -u origin main
endlocal
