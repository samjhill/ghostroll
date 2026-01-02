#!/usr/bin/env bash
set -euo pipefail

# Quick deployment script for faster iteration
# Usage: ./quick-deploy.sh [pi-hostname-or-ip]
#
# This script:
# 1. Syncs code changes to the Pi via rsync
# 2. Restarts the ghostroll-watch service
#
# Much faster than git pull for local development!

PI_HOST="${1:-raspberrypi}"
REPO_DIR="${GHOSTROLL_REPO_DIR:-/usr/local/src/ghostroll}"

echo "Quick deploying to ${PI_HOST}..."
echo "Repo dir: ${REPO_DIR}"

# Sync code (exclude venv, git, etc.)
rsync -avz --delete \
  --exclude='venv/' \
  --exclude='.git/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache/' \
  --exclude='ghostroll.egg-info/' \
  --exclude='*.db' \
  --exclude='*.log' \
  ./ "${PI_HOST}:${REPO_DIR}/"

echo "Code synced. Restarting service..."

# Restart the service
ssh "${PI_HOST}" "sudo systemctl restart ghostroll-watch.service"

echo "Done! Check logs with: ssh ${PI_HOST} 'sudo journalctl -u ghostroll-watch.service -f'"

