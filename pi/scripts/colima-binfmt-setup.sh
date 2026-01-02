#!/usr/bin/env bash
set -euo pipefail

CTX_DEFAULT="colima"
CTX="${GHOSTROLL_COLIMA_DOCKER_CONTEXT:-$CTX_DEFAULT}"

CURRENT_CTX="$(docker context show 2>/dev/null || true)"
if [ -z "${GHOSTROLL_COLIMA_DOCKER_CONTEXT:-}" ] && [[ "$CURRENT_CTX" == colima* ]]; then
  CTX="$CURRENT_CTX"
fi

if ! docker context inspect "$CTX" >/dev/null 2>&1; then
  # Auto-detect a context created by Colima (commonly: colima, colima-default, colima-<profile>)
  CTX="$(docker context ls --format '{{.Name}}' 2>/dev/null | awk '/^colima/{print; exit}')"
fi

if [ -z "${CTX}" ] || ! docker context inspect "$CTX" >/dev/null 2>&1; then
  echo "ERROR: Could not find a Docker context for Colima." >&2
  echo "Run 'colima start' first, then retry." >&2
  echo "Or set GHOSTROLL_COLIMA_DOCKER_CONTEXT to your Colima docker context name." >&2
  echo "Available contexts:" >&2
  docker context ls || true
  exit 1
fi

echo "==> Using docker context: ${CTX}"
docker context use "$CTX" >/dev/null

# Determine colima profile name for `colima ssh` (profile names typically match suffix after "colima-").
PROFILE="${GHOSTROLL_COLIMA_PROFILE:-}"
if [ -z "$PROFILE" ]; then
  case "$CTX" in
    colima) PROFILE="default" ;;
    colima-*) PROFILE="${CTX#colima-}" ;;
    *) PROFILE="default" ;;
  esac
fi

colima_ssh() {
  # Run a command inside the Colima VM via a shell so conditionals/redirections work.
  local cmd="$1"
  if [ "$PROFILE" = "default" ]; then
    colima ssh -- sh -lc "$cmd"
  else
    colima -p "$PROFILE" ssh -- sh -lc "$cmd"
  fi
}

echo "==> Enabling binfmt_misc inside Colima VM..."
# NOTE: `colima ssh` runs the provided command without a shell unless you ask for one.
# We run everything via `sh -lc` so redirections/conditionals work.
#
# Also: Colima VM may not include `modprobe` (kmod). That's OK; mounting binfmt_misc
# still works when the kernel has it built-in. We treat modprobe as best-effort.
colima_ssh 'command -v modprobe >/dev/null 2>&1 && modprobe binfmt_misc >/dev/null 2>&1 || true'
colima_ssh 'mkdir -p /proc/sys/fs/binfmt_misc; [ -r /proc/sys/fs/binfmt_misc/status ] || mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc'

echo "==> Registering QEMU handler for arm (armhf)..."
# On Apple Silicon + Colima (arm64), you generally do NOT need qemu-aarch64 to build arm64;
# pi-gen primarily needs armhf (qemu-arm) for certain stages/tools.
docker run --privileged --rm tonistiigi/binfmt --install arm

echo "==> Note: skipping multiarch/qemu-user-static fallback (often amd64-only; fails on arm64 Colima)."

echo "==> binfmt status:"
colima_ssh 'cat /proc/sys/fs/binfmt_misc/status || true'

echo "==> binfmt entries (filtered):"
colima_ssh 'ls -1 /proc/sys/fs/binfmt_misc 2>/dev/null | grep -E "qemu|arm" || true'

echo ""
echo "Done. Now run pi-gen without sudo:"
echo "  ./build-docker.sh"


