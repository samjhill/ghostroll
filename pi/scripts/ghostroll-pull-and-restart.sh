#!/usr/bin/env bash
set -euo pipefail

# Pull latest GhostRoll code from GitHub and restart all GhostRoll services.
#
# Usage:
#   sudo ./ghostroll-pull-and-restart.sh
#
# Environment (optional, via /etc/ghostroll.env or command line):
#   - GHOSTROLL_REPO_DIR (default: /usr/local/src/ghostroll)
#   - GHOSTROLL_GIT_REMOTE (default: tries to detect from current repo)
#   - GHOSTROLL_GIT_BRANCH (default: main)
#   - GHOSTROLL_GIT_SSH_COMMAND (for private repos with deploy keys)

# Load environment file if it exists
if [[ -f /etc/ghostroll.env ]]; then
    set -a
    source /etc/ghostroll.env
    set +a
fi

REPO_DIR="${GHOSTROLL_REPO_DIR:-/usr/local/src/ghostroll}"
REMOTE="${GHOSTROLL_GIT_REMOTE:-}"
BRANCH="${GHOSTROLL_GIT_BRANCH:-main}"

# If REMOTE not set, try to detect from current repo (if script is run from repo)
if [[ -z "$REMOTE" ]] && [[ -d "${REPO_DIR}/.git" ]]; then
    REMOTE="$(cd "$REPO_DIR" && git remote get-url origin 2>/dev/null || echo '')"
fi

if [[ -z "$REMOTE" ]]; then
    echo "Error: GHOSTROLL_GIT_REMOTE not set and could not detect from repo" >&2
    echo "Set GHOSTROLL_GIT_REMOTE in /etc/ghostroll.env or as an environment variable" >&2
    exit 1
fi

if [[ ! -d "$REPO_DIR" ]]; then
    echo "Error: repo directory not found: $REPO_DIR" >&2
    exit 1
fi

echo "GhostRoll: Pulling latest from $REMOTE (branch: $BRANCH)..."

cd "$REPO_DIR"

# Use SSH command if provided (for private repos)
if [[ -n "${GHOSTROLL_GIT_SSH_COMMAND:-}" ]]; then
    export GIT_SSH_COMMAND="${GHOSTROLL_GIT_SSH_COMMAND}"
fi

# Ensure this directory is a git repo
if [[ ! -d .git ]]; then
    echo "Initializing git repo in $REPO_DIR..."
    git init -q
    git remote add origin "$REMOTE" 2>/dev/null || git remote set-url origin "$REMOTE"
fi

# Fetch latest
git remote set-url origin "$REMOTE"
echo "Fetching from $REMOTE..."
git fetch -q origin "$BRANCH"

REMOTE_SHA="$(git rev-parse "origin/${BRANCH}")"
LOCAL_SHA="$(git rev-parse HEAD 2>/dev/null || echo '')"

if [[ "$REMOTE_SHA" == "$LOCAL_SHA" ]]; then
    echo "Already up to date at $LOCAL_SHA"
else
    echo "Updating: $LOCAL_SHA -> $REMOTE_SHA"
    git reset -q --hard "origin/${BRANCH}"
    git clean -q -fdx
fi

# Ensure dependencies/entrypoints are up to date
echo "Updating Python dependencies..."
PY_BIN="python3"
PIP_ARGS=()
if [[ -x "${REPO_DIR}/.venv/bin/python" ]]; then
    PY_BIN="${REPO_DIR}/.venv/bin/python"
    echo "Using venv: $PY_BIN"
else
    PIP_ARGS+=(--break-system-packages)
    echo "Using system Python (with --break-system-packages)"
fi

"${PY_BIN}" -m pip install -U pip "${PIP_ARGS[@]}" >/dev/null 2>&1
"${PY_BIN}" -m pip install -e "$REPO_DIR" "${PIP_ARGS[@]}" >/dev/null 2>&1

echo "Restarting GhostRoll services..."

# Restart all GhostRoll services (only if they're active/enabled)
SERVICES=(
    "ghostroll-watch.service"
    "ghostroll-eink.service"
)

for service in "${SERVICES[@]}"; do
    if systemctl is-enabled "$service" >/dev/null 2>&1 || systemctl is-active "$service" >/dev/null 2>&1; then
        echo "  Restarting $service..."
        systemctl restart "$service" || echo "    Warning: Failed to restart $service" >&2
    else
        echo "  Skipping $service (not active/enabled)"
    fi
done

echo "Done! GhostRoll services restarted."

