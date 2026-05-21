#!/usr/bin/env bash
# Stop GhostRoll and disable all boot-time systemd units (watch, e-ink, WiFi setup, update timer, automount).
# Usage: sudo ./pi/scripts/disable-boot-services.sh
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
KILL_SCRIPT="${REPO_DIR}/scripts/kill-ghostroll.sh"

TIMERS=(
  ghostroll-update.timer
)
SERVICES=(
  ghostroll-watch.service
  ghostroll-eink.service
  ghostroll-wifi-setup.service
  ghostroll-update.service
  ghostroll-firstboot.service
)
AUTOMOUNTS=(
  'mnt-auto\x2dimport.automount'
)

echo "Stopping GhostRoll processes..."
if [[ -x "${KILL_SCRIPT}" ]]; then
  FORCE=1 "${KILL_SCRIPT}" || true
else
  pkill -TERM -f 'ghostroll\.cli:main|/ghostroll( |$)| -m ghostroll ' 2>/dev/null || true
  sleep 1
  pkill -KILL -f 'ghostroll\.cli:main|/ghostroll( |$)| -m ghostroll ' 2>/dev/null || true
fi

for t in "${TIMERS[@]}"; do
  systemctl stop "${t}" 2>/dev/null || true
  systemctl disable "${t}" 2>/dev/null || true
done

for u in "${SERVICES[@]}"; do
  systemctl stop "${u}" 2>/dev/null || true
  systemctl disable "${u}" 2>/dev/null || true
done

for a in "${AUTOMOUNTS[@]}"; do
  systemctl stop "${a}" 2>/dev/null || true
  systemctl disable "${a}" 2>/dev/null || true
done

systemctl daemon-reload

echo ""
echo "GhostRoll boot autostart disabled."
echo "Units stopped and disabled: ${TIMERS[*]} ${SERVICES[*]} ${AUTOMOUNTS[*]}"
echo ""
echo "To start manually: ghostroll watch"
echo "To re-enable boot: sudo ./pi/scripts/install-services.sh --enable-boot"
