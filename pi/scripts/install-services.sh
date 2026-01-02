#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "This script must be run as root. Try: sudo $0" >&2
  exit 2
fi

# Repo dir (default assumes you're running from /home/pi/ghostroll)
REPO_DIR="${GHOSTROLL_REPO_DIR:-/home/pi/ghostroll}"

WATCH_UNIT_SRC="${REPO_DIR}/pi/systemd/ghostroll-watch.service"
WATCH_UNIT_DST="/etc/systemd/system/ghostroll-watch.service"

ENV_SRC_DEFAULT="${REPO_DIR}/pi/ghostroll.env.default"
ENV_DST="/etc/ghostroll.env"

if [[ ! -f "${WATCH_UNIT_SRC}" ]]; then
  echo "Missing: ${WATCH_UNIT_SRC}" >&2
  echo "Set GHOSTROLL_REPO_DIR=/path/to/ghostroll and rerun." >&2
  exit 2
fi

if [[ ! -f "${ENV_DST}" ]]; then
  if [[ -f "${ENV_SRC_DEFAULT}" ]]; then
    install -m 0644 "${ENV_SRC_DEFAULT}" "${ENV_DST}"
    echo "Installed ${ENV_DST} from ${ENV_SRC_DEFAULT}"
  else
    echo "Warning: ${ENV_DST} does not exist and default env file not found at ${ENV_SRC_DEFAULT}" >&2
  fi
fi

echo "Installing systemd unit: ghostroll-watch.service"
install -m 0644 "${WATCH_UNIT_SRC}" "${WATCH_UNIT_DST}"

# Pick the right GhostRoll executable:
# - pi-gen image installs /usr/local/bin/ghostroll (system-wide)
# - manual install on Bookworm Lite typically uses a venv under the repo
GHOSTROLL_BIN=""
if [[ -x "/usr/local/bin/ghostroll" ]]; then
  GHOSTROLL_BIN="/usr/local/bin/ghostroll"
elif [[ -x "${REPO_DIR}/.venv/bin/ghostroll" ]]; then
  GHOSTROLL_BIN="${REPO_DIR}/.venv/bin/ghostroll"
else
  echo "Could not find GhostRoll executable at:" >&2
  echo "  /usr/local/bin/ghostroll" >&2
  echo "  ${REPO_DIR}/.venv/bin/ghostroll" >&2
  echo "" >&2
  echo "If you're doing a manual install, create a venv and install first:" >&2
  echo "  cd ${REPO_DIR} && python3 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 2
fi

echo "Configuring ExecStart to use: ${GHOSTROLL_BIN}"
sed -i "s|^ExecStart=.*|ExecStart=${GHOSTROLL_BIN} watch|" "${WATCH_UNIT_DST}"

systemctl daemon-reload
systemctl enable --now ghostroll-watch.service

echo ""
echo "Done."
echo "Check logs:"
echo "  sudo journalctl -u ghostroll-watch.service -f"


