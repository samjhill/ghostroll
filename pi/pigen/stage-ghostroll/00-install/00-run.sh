#!/bin/bash -e

# This script runs inside pi-gen during image creation.

install -d /usr/local/src/ghostroll

# Copy the GhostRoll repo contents from pi-gen build context into the image.
# In your pi-gen tree, place this stage directory under pi-gen/, and ensure
# the GhostRoll repo is available in the build context you’re using.
#
# Common approach:
# - build pi-gen from a workspace that already has this repo checked out,
#   and copy files into the stage's files/ directory beforehand.
if [ -d "${STAGE_DIR}/files/ghostroll-repo" ]; then
  cp -a "${STAGE_DIR}/files/ghostroll-repo/." /usr/local/src/ghostroll/
else
  echo "stage-ghostroll: missing ${STAGE_DIR}/files/ghostroll-repo (you must provide repo files to bake into the image)" >&2
  exit 1
fi

apt-get update
apt-get install -y --no-install-recommends \
  git \
  python3 python3-venv python3-pip \
  python3-rpi.gpio python3-spidev \
  dnsmasq-base iptables \
  exfatprogs \
  awscli \
  ca-certificates

python3 -m pip install -U pip
# Raspberry Pi OS Bookworm uses an "externally managed" system Python (PEP 668).
# For the appliance image, allow pip to install system-wide.
python3 -m pip install --break-system-packages -e /usr/local/src/ghostroll
# Waveshare e-ink Python driver (used by optional ghostroll-eink service)
# Try pip first, fallback to GitHub repo if that fails
python3 -m pip install --break-system-packages waveshare-epd || {
  echo "pip install failed, installing from GitHub repo..."
  TEMP_DIR=$(mktemp -d)
  git clone --depth 1 https://github.com/waveshareteam/e-Paper.git "${TEMP_DIR}" || true
  if [[ -d "${TEMP_DIR}/RaspberryPi_JetsonNano/python/lib" ]]; then
    PYTHON_VERSION=$(python3 --version | grep -oP '\d+\.\d+' | head -1)
    SITE_PACKAGES="/usr/local/lib/python${PYTHON_VERSION}/site-packages"
    if [[ -d "${SITE_PACKAGES}" ]]; then
      cp -r "${TEMP_DIR}/RaspberryPi_JetsonNano/python/lib"/* "${SITE_PACKAGES}/" || true
    fi
  fi
  rm -rf "${TEMP_DIR}" || true
}

# Install firstboot helper + systemd services
install -m 0755 /usr/local/src/ghostroll/pi/scripts/ghostroll-firstboot.sh /usr/local/sbin/ghostroll-firstboot.sh
install -m 0755 /usr/local/src/ghostroll/pi/scripts/ghostroll-update.sh /usr/local/sbin/ghostroll-update.sh
install -m 0755 /usr/local/src/ghostroll/pi/scripts/ghostroll-eink-waveshare213v4.py /usr/local/sbin/ghostroll-eink-waveshare213v4.py
install -m 0755 /usr/local/src/ghostroll/pi/scripts/ghostroll-wifi-setup.py /usr/local/sbin/ghostroll-wifi-setup.py
install -m 0644 /usr/local/src/ghostroll/pi/systemd/ghostroll-firstboot.service /etc/systemd/system/ghostroll-firstboot.service
install -m 0644 /usr/local/src/ghostroll/pi/systemd/ghostroll-watch.service /etc/systemd/system/ghostroll-watch.service
install -m 0644 /usr/local/src/ghostroll/pi/systemd/ghostroll-update.service /etc/systemd/system/ghostroll-update.service
install -m 0644 /usr/local/src/ghostroll/pi/systemd/ghostroll-update.timer /etc/systemd/system/ghostroll-update.timer
install -m 0644 /usr/local/src/ghostroll/pi/systemd/ghostroll-eink.service /etc/systemd/system/ghostroll-eink.service
install -m 0644 /usr/local/src/ghostroll/pi/systemd/ghostroll-wifi-setup.service /etc/systemd/system/ghostroll-wifi-setup.service
install -m 0644 /usr/local/src/ghostroll/pi/systemd/mnt-auto\\x2dimport.mount /etc/systemd/system/mnt-auto\\x2dimport.mount
install -m 0644 /usr/local/src/ghostroll/pi/systemd/mnt-auto\\x2dimport.automount /etc/systemd/system/mnt-auto\\x2dimport.automount

# Default env baked into the image (can be overridden by boot-partition ghostroll.env)
install -m 0644 /usr/local/src/ghostroll/pi/ghostroll.env.default /etc/ghostroll.env

systemctl enable ghostroll-firstboot.service
systemctl enable ghostroll-watch.service
systemctl enable ghostroll-update.timer
systemctl enable ghostroll-eink.service
systemctl enable ghostroll-wifi-setup.service
systemctl enable mnt-auto\\x2dimport.automount


