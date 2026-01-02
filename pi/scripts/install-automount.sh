#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "This script must be run as root. Try: sudo $0" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

UNIT_MOUNT="${PI_DIR}/systemd/mnt-auto\\x2dimport.mount"
UNIT_AUTOMOUNT="${PI_DIR}/systemd/mnt-auto\\x2dimport.automount"

if [[ ! -f "${UNIT_MOUNT}" || ! -f "${UNIT_AUTOMOUNT}" ]]; then
  echo "Could not find unit files under: ${PI_DIR}/systemd" >&2
  echo "Expected:" >&2
  echo "  ${UNIT_MOUNT}" >&2
  echo "  ${UNIT_AUTOMOUNT}" >&2
  exit 2
fi

echo "Installing dependencies..."
if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  apt-get install -y exfatprogs
else
  echo "apt-get not found; please install exFAT support manually (exfatprogs)." >&2
fi

echo "Creating mountpoint..."
mkdir -p /mnt/auto-import

echo "Installing systemd units..."
install -m 0644 "${UNIT_MOUNT}" /etc/systemd/system/
install -m 0644 "${UNIT_AUTOMOUNT}" /etc/systemd/system/

echo "Enabling automount..."
systemctl daemon-reload
systemctl enable --now "mnt-auto\\x2dimport.automount"

echo ""
echo "Done."
echo "Next:"
echo "- Unplug/replug the SD reader, then run: ls /mnt/auto-import/DCIM"
echo "- If GhostRoll watch is running, it should detect the card once DCIM is mounted."


