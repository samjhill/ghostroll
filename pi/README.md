## GhostRoll Raspberry Pi Image (pi-gen) + “drop a config file on boot”

This guide gets you to a **flash-and-go** Raspberry Pi image:

- GhostRoll is already installed
- `ghostroll watch` starts automatically on boot (systemd)
- You configure it by dropping **one text file** onto the boot partition: `ghostroll.env`
- The Pi continuously writes `status.json` + `status.png` (great for an e‑ink display loop)

If you only want “run GhostRoll on a Pi”, you can skip all this and just `pip install -e .` on the Pi. This guide is for the *appliance* experience.

## What you build

We ship a pi-gen stage in this repo:

- `pi/pigen/stage-ghostroll/` (installs GhostRoll + services)
- `pi/pigen/config.example` (a pi-gen config you can copy and edit)

On first boot, the image will:

- copy `/boot/firmware/ghostroll.env` (or `/boot/ghostroll.env`) → `/etc/ghostroll.env`
- start `ghostroll watch` using that env file

## Build the image (recommended path)

pi-gen: `https://github.com/RPi-Distro/pi-gen`

### 1) Prepare pi-gen

In your pi-gen checkout:

1. Copy config:
   - Copy `pi/pigen/config.example` → `pi-gen/config`
   - Edit `FIRST_USER_PASS` (and optionally locale/timezone/Wi‑Fi)
2. Copy the stage:
   - Copy this repo’s `pi/pigen/stage-ghostroll/` → `pi-gen/stage-ghostroll/`

Make sure pi-gen’s branch matches your chosen release:

- For Raspberry Pi OS Bookworm: `git checkout bookworm`

### 2) Build

Run pi-gen normally (Docker or native). The result lands in `deploy/` as an image (often `.img` and/or `.zip`).

## macOS + Colima (practical notes)

On Apple Silicon, the most reliable setup is:

- an **x86_64 Colima profile** for pi-gen
- binfmt registered inside that profile

### Create/use an x86_64 Colima profile

```bash
colima stop || true
colima start --arch x86_64 --cpu 6 --memory 8 --disk 80 -p pigen
docker context ls
docker context use colima-pigen
```

### Register binfmt/QEMU for armhf

Run the helper from this repo:

```bash
GHOSTROLL_COLIMA_PROFILE=pigen ./pi/scripts/colima-binfmt-setup.sh
```

Then build pi-gen **without sudo**:

```bash
./build-docker.sh
```

Why “no sudo”: it’s easy to accidentally run against a different Docker context as root.

## Configure the flashed SD card (one file)

After you flash the resulting image to a microSD card, mount the **boot** partition on your laptop and add:

- `ghostroll.env` (copy from `pi/ghostroll.env.example`)

On first boot, it is copied to `/etc/ghostroll.env` and used by the service.

## AWS credentials on the Pi

GhostRoll uses the AWS CLI (`aws s3 cp` + `aws s3 presign`). You have two options:

- **Recommended**: boot the Pi once, SSH in, run `aws configure`, verify with `aws sts get-caller-identity`.
- **Less secure**: put `aws-credentials` and `aws-config` on the boot partition and let firstboot copy them:
  - `aws-credentials` → `/home/pi/.aws/credentials`
  - `aws-config` → `/home/pi/.aws/config`

## Automatic updates from GitHub (optional)

You can have the Pi periodically pull the latest code from your Git remote and restart GhostRoll.

How it works:

- A `systemd` timer runs every ~10 minutes (`ghostroll-update.timer`)
- If `GHOSTROLL_AUTO_UPDATE=1`, it does: `git fetch` → `git reset --hard origin/<branch>` → `pip install -e .` → restart `ghostroll-watch`

To enable:

1) In your boot partition `ghostroll.env`:

- set `GHOSTROLL_AUTO_UPDATE=1`
- set `GHOSTROLL_GIT_REMOTE=...`
- set `GHOSTROLL_GIT_BRANCH=main`

2) Reboot (or start the timer manually):

```bash
sudo systemctl enable --now ghostroll-update.timer
sudo systemctl list-timers | grep ghostroll-update || true
```

Private repos:

- easiest is to keep the repo public, or publish releases
- otherwise use a **read-only deploy key** or token (don’t hardcode secrets into the image)

## Services and status outputs

Installed services:

- `ghostroll-firstboot.service`: imports `ghostroll.env` (and optional AWS files) from the boot partition once
- `ghostroll-watch.service`: runs `ghostroll watch` at boot

Status outputs (for e‑ink):

- `/home/pi/ghostroll/status.json`
- `/home/pi/ghostroll/status.png`

Your e‑ink daemon can just refresh from `status.png` on a timer.

## Troubleshooting (the common ones)

### “RELEASE does not match the intended option for this branch”

Your pi-gen branch and `RELEASE=...` don’t match.

Fix (Bookworm example):

```bash
cd /path/to/pi-gen
git fetch --all
git checkout bookworm
git pull
```

### `setarch: failed to set personality to linux32`

This is common on Apple Silicon when building inside an arm64 VM/kernel. Use the **x86_64 Colima profile** approach above.

### `E: Invalid Release signature`

Usually one of:

- pi-gen branch/release mismatch (see above)
- time skew inside the VM
- stale pi-gen checkout

Try:

```bash
rm -rf work/ deploy/
```

and rerun the build after confirming your VM time is sane.
