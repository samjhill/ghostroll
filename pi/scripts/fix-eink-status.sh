#!/usr/bin/env bash
# Helper script to diagnose and fix e-ink display issues on Pi

set -euo pipefail

echo "=== E-ink Display Diagnostics ==="
echo ""

# Check if status.png exists
STATUS_PNG="${GHOSTROLL_STATUS_IMAGE_PATH:-/home/pi/ghostroll/status.png}"
if [[ ! -f "${STATUS_PNG}" ]]; then
    echo "❌ ERROR: ${STATUS_PNG} does not exist"
    echo "   GhostRoll may not be running or status image generation is disabled"
    exit 1
fi

echo "✓ status.png exists: ${STATUS_PNG}"
echo ""

# Check image size
IMAGE_SIZE=$(file "${STATUS_PNG}" | grep -oE '[0-9]+ x [0-9]+' || echo "unknown")
echo "Image size: ${IMAGE_SIZE}"

# Check config
CONFIG_FILE="/etc/ghostroll.env"
if [[ -f "${CONFIG_FILE}" ]]; then
    IMAGE_SIZE_CONFIG=$(grep "^GHOSTROLL_STATUS_IMAGE_SIZE=" "${CONFIG_FILE}" | cut -d= -f2 || echo "not set")
    echo "Config GHOSTROLL_STATUS_IMAGE_SIZE: ${IMAGE_SIZE_CONFIG:-not set}"
    
    if [[ "${IMAGE_SIZE_CONFIG}" != "250x122" ]]; then
        echo ""
        echo "⚠️  WARNING: Status image size is not set to 250x122"
        echo "   This means text positioning won't be optimized for e-ink display"
        echo ""
        echo "   To fix, add to ${CONFIG_FILE}:"
        echo "   GHOSTROLL_STATUS_IMAGE_SIZE=250x122"
        echo ""
        echo "   Then restart: sudo systemctl restart ghostroll-watch.service"
    fi
else
    echo "⚠️  Config file not found: ${CONFIG_FILE}"
fi

echo ""
echo "=== Service Status ==="
systemctl is-active ghostroll-eink.service >/dev/null 2>&1 && echo "✓ ghostroll-eink.service is active" || echo "❌ ghostroll-eink.service is not active"
systemctl is-active ghostroll-watch.service >/dev/null 2>&1 && echo "✓ ghostroll-watch.service is active" || echo "❌ ghostroll-watch.service is not active"

echo ""
echo "=== Recent Logs ==="
echo "ghostroll-eink.service logs (last 20 lines):"
journalctl -u ghostroll-eink.service -n 20 --no-pager | tail -20 || echo "No logs found"

echo ""
echo "=== Next Steps ==="
echo "1. Check pixel statistics in logs above"
echo "2. If image size is not 250x122, update config and restart ghostroll-watch"
echo "3. If pixel stats show 0% black, status.png needs to be regenerated"
echo "4. View full logs: sudo journalctl -u ghostroll-eink.service -f"

