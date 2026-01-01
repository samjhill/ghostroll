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

### If you build via Docker: enable binfmt/qemu (required for cross-arch builds)

If you see errors like:

- `armhf: not supported on this machine/kernel`
- `Ensure your OS has binfmt_misc support enabled and configured`

…you need to register QEMU/binfmt handlers on the build host.

On a Linux build host with Docker:

```bash
docker run --privileged --rm tonistiigi/binfmt --install arm,arm64
docker run --privileged --rm tonistiigi/binfmt --info
```

Then re-run `sudo ./build-docker.sh`.

On macOS:

- If you’re using **Docker Desktop**, pi-gen’s Docker build often **won’t** have the required kernel binfmt support. Use a Linux VM (or a Linux machine) as your pi-gen build host.
- If you’re using **Colima**, you *can* enable this inside the Colima VM:

```bash
# Ensure your shell is using Colima's docker context
docker context use colima

# IMPORTANT: don't run pi-gen with sudo on macOS+Colima.
# `sudo ./build-docker.sh` may use root's Docker context (often not "colima"),
# which means the binfmt registration you did as your user won't apply.
#
# Prefer:
#   ./build-docker.sh
#
# If you must use sudo, preserve env:
#   sudo -E ./build-docker.sh

# Make sure binfmt_misc is available in the Colima VM.
# Important: run commands via a shell (`sh -lc`) so conditionals/redirections work.
colima ssh -- sh -lc 'command -v modprobe >/dev/null 2>&1 && modprobe binfmt_misc >/dev/null 2>&1 || true'
colima ssh -- sh -lc 'mkdir -p /proc/sys/fs/binfmt_misc; [ -r /proc/sys/fs/binfmt_misc/status ] || mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc'

# Register QEMU handler (runs inside the Colima VM).
# For pi-gen, the critical one is "arm" (covers armhf). On Apple Silicon + Colima,
# arm64 is native, so qemu-aarch64 is often unnecessary.
docker run --privileged --rm tonistiigi/binfmt --install arm
docker run --privileged --rm tonistiigi/binfmt --info
```

Then re-run `./build-docker.sh`.

If it still fails, confirm `qemu-arm` shows up in the `--info` output above.

### Colima + Apple Silicon caveat: `setarch linux32` failures

If you get:

- `setarch: failed to set personality to linux32: Invalid argument`

That’s typically because your current Colima VM kernel/userspace doesn’t support the **linux32 personality** needed by parts of pi-gen.

**Workaround (recommended): run pi-gen in an x86_64 Linux environment**, e.g. an x86_64 Colima profile or a Linux VM:

```bash
# Create a separate Colima profile for pi-gen builds
colima stop || true
colima start --arch x86_64 --cpu 6 --memory 8 --disk 80 -p pigen
docker context use colima-pigen
```

Then run the binfmt setup and `./build-docker.sh` again.

You can verify armhf is registered by checking for `qemu-arm` entries:

```bash
colima ssh -- 'ls -1 /proc/sys/fs/binfmt_misc | head'
colima ssh -- 'ls -1 /proc/sys/fs/binfmt_misc | grep -E \"qemu|arm\" || true'
```

## Build the image with pi-gen (recommended)

1) Clone pi-gen:

- `https://github.com/RPi-Distro/pi-gen`

2) Add the pi-gen config:

- Copy `pi/pigen/config.example` to the root of your pi-gen checkout as `config`.
- Edit `FIRST_USER_PASS` (and optionally Wi‑Fi / locale / timezone).

3) Copy GhostRoll’s pi-gen stage into pi-gen:

Copy this repo’s `pi/pigen/stage-ghostroll/` into pi-gen as:

- `pi-gen/stage-ghostroll/`

4) Enable the stage:

In pi-gen, add `stage-ghostroll` to your build order (either by renaming stage numbers or by using pi-gen’s config mechanisms).

5) Build:

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


