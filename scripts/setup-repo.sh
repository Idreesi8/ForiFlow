#!/usr/bin/env bash
# Bootstrap git metadata for a fresh ForiFlow checkout.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .git ]; then
  git init
  git branch -M main
  echo "Initialised a new git repository on main."
else
  echo "Git repository already present ($(git rev-parse --abbrev-ref HEAD))."
fi

git add .
# Honour .gitignore — .cursorrules.txt and model pickles stay out.

if git diff --cached --quiet; then
  echo "Nothing new to commit."
else
  git commit -m "feat: Production-ready ForiFlow with docs, LinkedIn content, and screenshot automation"
fi

echo
echo "Push to GitHub: git remote add origin https://github.com/Idreesi8/foriflow.git && git push -u origin main"
echo "If origin already exists: git push -u origin main"
