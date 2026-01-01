#!/usr/bin/env bash
set -euo pipefail

echo "==> Ensuring docker context is 'colima'..."
docker context use colima >/dev/null

echo "==> Enabling binfmt_misc inside Colima VM..."
# NOTE: `colima ssh` runs the provided command without a shell unless you ask for one.
# We run everything via `sh -lc` so redirections/conditionals work.
#
# Also: Colima VM may not include `modprobe` (kmod). That's OK; mounting binfmt_misc
# still works when the kernel has it built-in. We treat modprobe as best-effort.
colima ssh -- sh -lc 'command -v modprobe >/dev/null 2>&1 && modprobe binfmt_misc >/dev/null 2>&1 || true'
colima ssh -- sh -lc 'mkdir -p /proc/sys/fs/binfmt_misc; [ -r /proc/sys/fs/binfmt_misc/status ] || mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc'

echo "==> Registering QEMU handler for arm (armhf)..."
# On Apple Silicon + Colima (arm64), you generally do NOT need qemu-aarch64 to build arm64;
# pi-gen primarily needs armhf (qemu-arm) for certain stages/tools.
docker run --privileged --rm tonistiigi/binfmt --install arm

echo "==> Note: skipping multiarch/qemu-user-static fallback (often amd64-only; fails on arm64 Colima)."

echo "==> binfmt status:"
colima ssh -- sh -lc 'cat /proc/sys/fs/binfmt_misc/status || true'

echo "==> binfmt entries (filtered):"
colima ssh -- sh -lc 'ls -1 /proc/sys/fs/binfmt_misc 2>/dev/null | grep -E "qemu|arm" || true'

echo ""
echo "Done. Now run pi-gen without sudo:"
echo "  ./build-docker.sh"


