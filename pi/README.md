## GhostRoll Raspberry Pi Image (pi-gen) + “drop a config file on boot”

This guide gets you to a **flash-and-go** Raspberry Pi image:

- GhostRoll is already installed
- `ghostroll watch` starts automatically on boot (systemd)
- You configure it by dropping **one text file** onto the boot partition: `ghostroll.env`
- The Pi continuously writes `status.json` + `status.png` (great for an e‑ink display loop)

If you only want “run GhostRoll on a Pi”, you can skip all this and do a manual install on Raspberry Pi OS.
Note: on Bookworm, system Python is “externally managed” (PEP 668), so the manual path typically uses a **venv**.
This guide is for the *appliance* experience.

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

### Defaults (no config file required)

The image also ships with a baked-in `/etc/ghostroll.env` (`pi/ghostroll.env.default` in this repo), so the device boots and runs even if you don’t copy a config file onto the boot partition.

If you *do* place `ghostroll.env` on the boot partition, it will override the baked-in defaults.

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

On boot (once networking is up), the status display also shows the current **SSH target**:

- `SSH: pi@<ip> (<hostname>)`

## Waveshare 2.13" e‑ink HAT V4 (auto display)

This repo includes a built-in systemd service that can drive the **Waveshare 2.13" e‑ink HAT V4** directly from `status.png`.

To enable it:

1) In your boot partition `ghostroll.env`, set:

- `GHOSTROLL_EINK_ENABLE=1`

2) Reboot (or start the service manually):

```bash
sudo systemctl enable --now ghostroll-eink.service
sudo systemctl status ghostroll-eink.service --no-pager
```

It will refresh the panel when `status.png` changes (default poll interval: 5s).

## Auto-mount SD card on Lite (recommended)

On Raspberry Pi OS Lite, USB storage devices often **do not auto-mount**.
GhostRoll watch mode only detects **mounted** volumes (it looks for `DCIM/` under mount roots like `/mnt`).

This repo includes a systemd automount for an SD card labeled `auto-import`:

- mounts to: `/mnt/auto-import`
- device path: `/dev/disk/by-label/auto-import`

If you installed manually (not via pi-gen image), enable it:

```bash
cd /home/pi/ghostroll
sudo ./pi/scripts/install-automount.sh
```

## Manual install on Raspberry Pi OS Lite (testing path)

This is the fastest way to validate hardware + SD ingest + S3 uploads **while pi-gen is still building**.

### 1) Install dependencies

```bash
sudo apt-get update
sudo apt-get install -y git python3-full python3-venv python3-pip awscli rsync
```

If your SD card is **exFAT** (common):

```bash
sudo apt-get install -y exfatprogs
```

### 2) Clone + install GhostRoll into a venv (Bookworm)

```bash
cd /home/pi
git clone https://github.com/samjhill/ghostroll.git
cd /home/pi/ghostroll
python3 -m venv .venv
/home/pi/ghostroll/.venv/bin/python -m pip install -U pip setuptools wheel
/home/pi/ghostroll/.venv/bin/python -m pip install -e .
```

### 3) Install default config (optional)

```bash
sudo cp /home/pi/ghostroll/pi/ghostroll.env.default /etc/ghostroll.env
sudo chmod 0644 /etc/ghostroll.env
```

### 4) Enable SD auto-mount (Lite)

```bash
cd /home/pi/ghostroll
sudo ./pi/scripts/install-automount.sh
```

### 5) Start GhostRoll at boot (systemd)

Use the helper so `ExecStart` points at the right binary:

- pi-gen image: `/usr/local/bin/ghostroll`
- manual venv: `/home/pi/ghostroll/.venv/bin/ghostroll`

```bash
cd /home/pi/ghostroll
sudo ./pi/scripts/install-services.sh
sudo journalctl -u ghostroll-watch.service -f
```

### 6) Check progress

```bash
sudo journalctl -u ghostroll-watch.service -f
cat /home/pi/ghostroll/status.json
ls -lh /home/pi/ghostroll/status.png
```

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
