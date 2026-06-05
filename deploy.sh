#!/bin/bash
# Deploy: commit generated site and push to GitHub
set -e

cd /home/nihal/content-site

# Ensure style.css is in the deploy directory
cp -n style.css docs/style.css 2>/dev/null || true

git add -A
if git diff --cached --quiet; then
  echo "Nothing to deploy — no changes."
  exit 0
fi

git commit -m "Auto-deploy: $(date +'%Y-%m-%d %H:%M UTC')"
git push origin main

echo "✓ Deployed to GitHub (main branch — GitHub Pages picks it up from /public)"
