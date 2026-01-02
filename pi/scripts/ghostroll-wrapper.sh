#!/usr/bin/env bash
set -euo pipefail

# Simple wrapper that tries venv first, then system-wide install

# Try venv first (common on Bookworm manual installs)
if [ -x "/home/pi/ghostroll/.venv/bin/ghostroll" ]; then
    exec "/home/pi/ghostroll/.venv/bin/ghostroll" "$@"
fi

# Try system-wide install (appliance image)
if [ -x "/usr/local/bin/ghostroll" ]; then
    exec "/usr/local/bin/ghostroll" "$@"
fi

echo "Error: ghostroll command not found." >&2
echo "  Tried: /home/pi/ghostroll/.venv/bin/ghostroll" >&2
echo "  Tried: /usr/local/bin/ghostroll" >&2
exit 1
