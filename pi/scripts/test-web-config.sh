#!/usr/bin/env bash
set -euo pipefail

# Quick test to verify web interface configuration is being read

echo "Testing web interface configuration..."
echo ""

# Test 1: Check environment file exists and has web settings
echo "1. Checking /etc/ghostroll.env:"
if [[ -f /etc/ghostroll.env ]]; then
    echo "   ✓ File exists"
    if grep -q "^GHOSTROLL_WEB_ENABLED" /etc/ghostroll.env; then
        grep "^GHOSTROLL_WEB_ENABLED" /etc/ghostroll.env
        grep "^GHOSTROLL_WEB_HOST" /etc/ghostroll.env || echo "   GHOSTROLL_WEB_HOST not set (will use default)"
        grep "^GHOSTROLL_WEB_PORT" /etc/ghostroll.env || echo "   GHOSTROLL_WEB_PORT not set (will use default)"
    else
        echo "   ⚠ GHOSTROLL_WEB_ENABLED not found in file"
    fi
else
    echo "   ✗ File does not exist"
fi
echo ""

# Test 2: Check if service can see environment variables
echo "2. Testing if Python can read environment variables:"
if command -v python3 >/dev/null 2>&1; then
    # Source the env file and test
    set -a
    source /etc/ghostroll.env 2>/dev/null || true
    set +a
    python3 -c "
import os
print(f\"   GHOSTROLL_WEB_ENABLED = {os.environ.get('GHOSTROLL_WEB_ENABLED', 'NOT SET')}\")
print(f\"   GHOSTROLL_WEB_HOST = {os.environ.get('GHOSTROLL_WEB_HOST', 'NOT SET (default: 127.0.0.1)')}\")
print(f\"   GHOSTROLL_WEB_PORT = {os.environ.get('GHOSTROLL_WEB_PORT', 'NOT SET (default: 8080)')}\")
" 2>/dev/null || echo "   ⚠ Could not test Python import"
else
    echo "   ⚠ python3 not found"
fi
echo ""

# Test 3: Check recent service logs (full, not filtered)
echo "3. Recent service startup logs (last 30 lines, looking for web interface messages):"
sudo journalctl -u ghostroll-watch.service -n 30 --no-pager 2>/dev/null | tail -30 || echo "   ⚠ Could not read logs"
echo ""

# Test 4: Check if service needs daemon-reload
echo "4. Systemd daemon status:"
if systemctl is-active ghostroll-watch.service >/dev/null 2>&1; then
    echo "   ✓ Service is running"
    echo "   To restart with latest config:"
    echo "     sudo systemctl daemon-reload"
    echo "     sudo systemctl restart ghostroll-watch.service"
else
    echo "   ⚠ Service is not running"
    echo "   Start with: sudo systemctl start ghostroll-watch.service"
fi
echo ""

echo "Next steps:"
echo "1. Pull latest code: git pull"
echo "2. Reload systemd: sudo systemctl daemon-reload"
echo "3. Restart service: sudo systemctl restart ghostroll-watch.service"
echo "4. Check full logs: sudo journalctl -u ghostroll-watch.service -n 100 --no-pager"
echo "   (Look for 'Web interface' or 'Starting web interface' messages)"

