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

AUTO="${GHOSTROLL_AUTO_UPDATE:-0}"
if [[ "$AUTO" != "1" ]]; then
  exit 0
fi

REPO_DIR="${GHOSTROLL_REPO_DIR:-/usr/local/src/ghostroll}"
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
if [[ -x "${REPO_DIR}/.venv/bin/python" ]]; then
  PY_BIN="${REPO_DIR}/.venv/bin/python"
else
  PIP_ARGS+=(--break-system-packages)
fi

"${PY_BIN}" -m pip install -U pip "${PIP_ARGS[@]}" >/dev/null
"${PY_BIN}" -m pip install -e "$REPO_DIR" "${PIP_ARGS[@]}" >/dev/null

systemctl restart ghostroll-watch.service


