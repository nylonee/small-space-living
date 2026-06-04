#!/bin/bash
# Deploy to Cloudflare Pages via git
# Run this after creating the GitHub repo and setting up Cloudflare Pages

set -e

SITE_DIR="/home/nihal/content-site"
REPO_DIR="/home/nihal/content-site-repo"

# Clone or pull
if [ -d "$REPO_DIR/.git" ]; then
  cd "$REPO_DIR"
  git pull origin main
else
  cd /home/nihal
  echo "First, create the GitHub repo, then run:"
  echo "  git clone <your-repo-url> $REPO_DIR"
  echo "Then re-run this script."
  exit 1
fi

# Copy generated site into repo
rsync -a --delete "$SITE_DIR/public/" "$REPO_DIR/"

# Commit and push
cd "$REPO_DIR"
git add -A
git commit -m "Auto-deploy: $(date +'%Y-%m-%d %H:%M')"
git push origin main

echo "✓ Deployed to Cloudflare Pages"
