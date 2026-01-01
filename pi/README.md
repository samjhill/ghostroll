# GhostRoll Raspberry Pi Image (pi-gen) + Text-File Configuration

Goal: produce a **complete Raspberry Pi OS image** with GhostRoll installed and a **one-file config** you can drop onto the boot partition.

This setup:

- Installs GhostRoll on the Pi
- Enables a `systemd` service to run `ghostroll watch` on boot
- Reads config from a text file on the boot partition: `ghostroll.env`
- Continuously writes `~/ghostroll/status.json` + `~/ghostroll/status.png` for your e-ink loop

## What you’ll need (build machine)

- A Linux machine (recommended) or a Linux VM (pi-gen runs best on Linux)
- `git`
- `pi-gen` prerequisites (see pi-gen docs)

## Build the image with pi-gen (recommended)

1) Clone pi-gen:

- `https://github.com/RPi-Distro/pi-gen`

2) Copy GhostRoll’s pi-gen stage into pi-gen:

Copy this repo’s `pi/pigen/stage-ghostroll/` into pi-gen as:

- `pi-gen/stage-ghostroll/`

3) Enable the stage:

In pi-gen, add `stage-ghostroll` to your build order (either by renaming stage numbers or by using pi-gen’s config mechanisms).

4) Build:

Follow pi-gen’s normal build instructions. The result is a `.img` you can write to microSD.

## Configure via text file on boot partition

After writing the `.img` to microSD, mount the **boot** partition on your computer and add:

- `ghostroll.env` (see `pi/ghostroll.env.example`)

On first boot, GhostRoll copies it to `/etc/ghostroll.env` and the `ghostroll-watch` service uses it.

## AWS credentials on the Pi

GhostRoll uses the AWS CLI; you need AWS creds on the Pi:

- Recommended: `aws configure` on the Pi once (then `aws sts get-caller-identity`)
- Alternative (less secure): place `aws-credentials` and `aws-config` on boot partition and let firstboot copy them.
  - Files:
    - `aws-credentials` → `~/.aws/credentials`
    - `aws-config` → `~/.aws/config`

## Services

- `ghostroll-firstboot.service`: one-time import of boot config file(s)
- `ghostroll-watch.service`: runs `ghostroll watch` at boot

## E‑ink display

This repo writes `~/ghostroll/status.png`. Your e‑ink driver daemon can refresh from that path.
Hardware integration differs per display; keep it separate from GhostRoll.


