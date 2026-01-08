#!/usr/bin/env bash
# Quick health check script to run ON the Pi (not via SSH)
# Copy this to the Pi and run: ./check-pi-health.sh

echo "=== Raspberry Pi Health Check ==="
echo ""

echo "1. System Uptime and Load:"
uptime
echo ""

echo "2. Memory Usage:"
free -h
echo ""

echo "3. CPU Temperature:"
vcgencmd measure_temp 2>/dev/null || echo "N/A (vcgencmd not available)"
echo ""

echo "4. Throttling Status:"
THROTTLED=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)
if [[ -n "$THROTTLED" ]]; then
    if [[ "$THROTTLED" == "0x0" ]]; then
        echo "   ✓ OK - No throttling detected"
    else
        echo "   ⚠ WARNING - Pi is being throttled: $THROTTLED"
        echo "   Possible causes:"
        echo "     - Under-voltage (check power supply)"
        echo "     - Over-temperature"
        echo "     - Throttling due to load"
    fi
else
    echo "   N/A (vcgencmd not available)"
fi
echo ""

echo "5. Disk Usage:"
df -h / | tail -1
echo ""

echo "6. SSH Service Status:"
systemctl status ssh --no-pager -l | head -15 || echo "   (Cannot check SSH service)"
echo ""

echo "7. Recent SSH Connections:"
journalctl -u ssh -n 10 --no-pager 2>/dev/null | tail -5 || echo "   (Cannot check SSH logs)"
echo ""

echo "8. Network Interfaces:"
ip addr show | grep -E "^[0-9]+:|inet " || ifconfig | grep -E "^[a-z]|inet "
echo ""

echo "9. GhostRoll Services:"
systemctl is-active ghostroll-watch.service 2>/dev/null && echo "   ✓ ghostroll-watch.service: active" || echo "   ✗ ghostroll-watch.service: inactive"
systemctl is-active ghostroll-eink.service 2>/dev/null && echo "   ✓ ghostroll-eink.service: active" || echo "   ✗ ghostroll-eink.service: inactive"
echo ""

echo "=== Recommendations ==="
echo ""
echo "If SSH is spotty:"
echo "  1. Restart SSH: sudo systemctl restart ssh"
echo "  2. Check if Pi is throttling (see #4 above)"
echo "  3. Check system load (see #1 above) - should be < 2.0"
echo "  4. Check memory (see #2 above) - should have free memory"
echo "  5. If on WiFi, try wired Ethernet"
echo "  6. Disable WiFi power management: sudo iwconfig wlan0 power off"
echo ""

