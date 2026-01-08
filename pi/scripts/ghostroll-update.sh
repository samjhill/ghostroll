#!/usr/bin/env bash
set -euo pipefail

# Environment (optional, via /etc/ghostroll.env):
# - GHOSTROLL_AUTO_UPDATE=1
# - GHOSTROLL_GIT_REMOTE=https://github.com/<owner>/<repo>.git
# - GHOSTROLL_GIT_BRANCH=main
# - GHOSTROLL_UPDATE_INTERVAL_MINUTES=10 (documented; timer controls cadence by default)
#
# For private repos, prefer a read-only deploy key and set:
# - GHOSTROLL_GIT_SSH_COMMAND='ssh -i /etc/ghostroll_deploy_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new'

# Load environment file if it exists (needed for web interface config)
if [[ -f /etc/ghostroll.env ]]; then
    set -a
    source /etc/ghostroll.env
    set +a
fi

AUTO="${GHOSTROLL_AUTO_UPDATE:-0}"
if [[ "$AUTO" != "1" ]]; then
  exit 0
fi

REPO_DIR="${GHOSTROLL_REPO_DIR:-/home/pi/ghostroll}"
REMOTE="${GHOSTROLL_GIT_REMOTE:-}"
BRANCH="${GHOSTROLL_GIT_BRANCH:-main}"

if [[ -z "$REMOTE" ]]; then
  echo "ghostroll-update: GHOSTROLL_GIT_REMOTE not set; skipping" >&2
  exit 0
fi

if [[ ! -d "$REPO_DIR" ]]; then
  echo "ghostroll-update: repo dir not found: $REPO_DIR" >&2
  exit 1
fi

cd "$REPO_DIR"

if [[ -n "${GHOSTROLL_GIT_SSH_COMMAND:-}" ]]; then
  export GIT_SSH_COMMAND="${GHOSTROLL_GIT_SSH_COMMAND}"
fi

# Ensure this directory is a git repo.
if [[ ! -d .git ]]; then
  git init -q
  git remote add origin "$REMOTE" 2>/dev/null || git remote set-url origin "$REMOTE"
fi

git remote set-url origin "$REMOTE"
git fetch -q origin "$BRANCH"

REMOTE_SHA="$(git rev-parse "origin/${BRANCH}")"
LOCAL_SHA="$(git rev-parse HEAD 2>/dev/null || echo '')"

if [[ "$REMOTE_SHA" == "$LOCAL_SHA" ]]; then
  exit 0
fi

echo "ghostroll-update: updating $LOCAL_SHA -> $REMOTE_SHA"

# Replace working tree with remote branch contents.
git reset -q --hard "origin/${BRANCH}"
git clean -q -fdx

# Ensure dependencies/entrypoints are up to date.
# Raspberry Pi OS Bookworm uses an "externally managed" system Python (PEP 668).
# Prefer a repo-local venv if present; otherwise fall back to system pip with
# --break-system-packages (acceptable for appliance images).
PY_BIN="python3"
PIP_ARGS=()
# Check for venv in /home/pi/ghostroll/.venv first (standard Raspberry Pi location)
if [[ -x "/home/pi/ghostroll/.venv/bin/python" ]]; then
  PY_BIN="/home/pi/ghostroll/.venv/bin/python"
elif [[ -x "${REPO_DIR}/.venv/bin/python" ]]; then
  PY_BIN="${REPO_DIR}/.venv/bin/python"
else
  PIP_ARGS+=(--break-system-packages)
fi

"${PY_BIN}" -m pip install -U pip "${PIP_ARGS[@]}" >/dev/null 2>&1
"${PY_BIN}" -m pip install -e "$REPO_DIR" "${PIP_ARGS[@]}" >/dev/null 2>&1

# Verify boto3 is installed (required dependency)
if ! "${PY_BIN}" -c "import boto3" 2>/dev/null; then
  echo "ghostroll-update: warning: boto3 not found, installing explicitly..." >&2
  "${PY_BIN}" -m pip install boto3>=1.34.0 "${PIP_ARGS[@]}" >/dev/null 2>&1 || {
    echo "ghostroll-update: error: failed to install boto3" >&2
    exit 1
  }
fi

echo "ghostroll-update: restarting services..."

# Check if web interface is enabled (web server runs as part of ghostroll-watch.service)
WEB_ENABLED="0"
WEB_HOST="${GHOSTROLL_WEB_HOST:-127.0.0.1}"
WEB_PORT="${GHOSTROLL_WEB_PORT:-8080}"
if [[ -f /etc/ghostroll.env ]] && grep -q "^GHOSTROLL_WEB_ENABLED=1" /etc/ghostroll.env; then
    WEB_ENABLED="1"
    echo "ghostroll-update: web interface enabled (http://${WEB_HOST}:${WEB_PORT})"
    echo "ghostroll-update: web server will restart with ghostroll-watch.service"
fi

# Restart all GhostRoll services (only if they're active/enabled)
# Note: The web server runs as part of ghostroll-watch.service, so restarting
# that service will automatically restart the web server.
SERVICES=(
    "ghostroll-watch.service"
    "ghostroll-eink.service"
)

for service in "${SERVICES[@]}"; do
    if systemctl is-enabled "$service" >/dev/null 2>&1 || systemctl is-active "$service" >/dev/null 2>&1; then
        echo "ghostroll-update: restarting $service..."
        if systemctl restart "$service"; then
            echo "ghostroll-update: $service restarted successfully"
        else
            echo "ghostroll-update: warning: failed to restart $service" >&2
        fi
    else
        echo "ghostroll-update: skipping $service (not active/enabled)"
    fi
done

# Verify web server is running if enabled
if [[ "$WEB_ENABLED" == "1" ]]; then
    # Give the service a moment to start
    sleep 1
    if systemctl is-active ghostroll-watch.service >/dev/null 2>&1; then
        echo "ghostroll-update: web server should be running at http://${WEB_HOST}:${WEB_PORT}/"
    else
        echo "ghostroll-update: warning: ghostroll-watch.service is not active (web server may not be running)" >&2
    fi
fi

echo "ghostroll-update: done"


