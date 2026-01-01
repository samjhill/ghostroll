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
  python3 python3-venv python3-pip \
  awscli \
  ca-certificates

python3 -m pip install -U pip
python3 -m pip install -e /usr/local/src/ghostroll

# Install firstboot helper + systemd services
install -m 0755 /usr/local/src/ghostroll/pi/scripts/ghostroll-firstboot.sh /usr/local/sbin/ghostroll-firstboot.sh
install -m 0644 /usr/local/src/ghostroll/pi/systemd/ghostroll-firstboot.service /etc/systemd/system/ghostroll-firstboot.service
install -m 0644 /usr/local/src/ghostroll/pi/systemd/ghostroll-watch.service /etc/systemd/system/ghostroll-watch.service

systemctl enable ghostroll-firstboot.service
systemctl enable ghostroll-watch.service


