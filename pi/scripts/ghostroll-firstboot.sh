#!/usr/bin/env bash
set -euo pipefail

# Raspberry Pi OS Bookworm commonly mounts boot at /boot/firmware.
# Older images often use /boot.
BOOT_DIR=""
for d in /boot/firmware /boot; do
  if [[ -d "$d" ]]; then
    BOOT_DIR="$d"
    break
  fi
done

if [[ -z "${BOOT_DIR}" ]]; then
  echo "ghostroll-firstboot: no boot mount found at /boot/firmware or /boot" >&2
  exit 0
fi

if [[ -f "${BOOT_DIR}/ghostroll.env" ]]; then
  install -m 0644 "${BOOT_DIR}/ghostroll.env" /etc/ghostroll.env
  echo "ghostroll-firstboot: installed /etc/ghostroll.env"
fi

# Optional: copy AWS credentials from boot partition (less secure; prefer aws configure on-device).
if [[ -f "${BOOT_DIR}/aws-credentials" ]]; then
  install -d -m 0700 /home/pi/.aws
  install -m 0600 "${BOOT_DIR}/aws-credentials" /home/pi/.aws/credentials
  chown -R pi:pi /home/pi/.aws
  echo "ghostroll-firstboot: installed /home/pi/.aws/credentials"
fi

if [[ -f "${BOOT_DIR}/aws-config" ]]; then
  install -d -m 0700 /home/pi/.aws
  install -m 0600 "${BOOT_DIR}/aws-config" /home/pi/.aws/config
  chown -R pi:pi /home/pi/.aws
  echo "ghostroll-firstboot: installed /home/pi/.aws/config"
fi




