#!/usr/bin/env bash
set -euo pipefail

# Diagnostic script to check why the web interface isn't running

echo "GhostRoll Web Interface Diagnostic"
echo "=================================="
echo ""

# Load environment if available
if [[ -f /etc/ghostroll.env ]]; then
    set -a
    source /etc/ghostroll.env
    set +a
    echo "✓ Loaded /etc/ghostroll.env"
else
    echo "⚠ /etc/ghostroll.env not found"
fi
echo ""

# Check environment variables
echo "Environment Variables:"
echo "  GHOSTROLL_WEB_ENABLED=${GHOSTROLL_WEB_ENABLED:-not set}"
echo "  GHOSTROLL_WEB_HOST=${GHOSTROLL_WEB_HOST:-not set (default: 127.0.0.1)}"
echo "  GHOSTROLL_WEB_PORT=${GHOSTROLL_WEB_PORT:-not set (default: 8080)}"
echo ""

# Determine expected values
WEB_ENABLED="${GHOSTROLL_WEB_ENABLED:-true}"
WEB_HOST="${GHOSTROLL_WEB_HOST:-127.0.0.1}"
WEB_PORT="${GHOSTROLL_WEB_PORT:-8080}"

# On Pi, default port should be 8081 to avoid WiFi portal conflict
if [[ -z "${GHOSTROLL_WEB_PORT:-}" ]]; then
    if [[ -f /etc/ghostroll.env ]] && grep -q "GHOSTROLL_WIFI_PORTAL_PORT=8080" /etc/ghostroll.env 2>/dev/null; then
        echo "⚠ WiFi portal uses port 8080 - web interface should use 8081"
        echo "   Recommendation: Set GHOSTROLL_WEB_PORT=8081 in /etc/ghostroll.env"
        WEB_PORT=8081
    fi
fi

echo "Expected Configuration:"
if [[ "$WEB_ENABLED" == "1" ]] || [[ "$WEB_ENABLED" == "true" ]]; then
    echo "  ✓ Web interface should be ENABLED"
    echo "  Host: $WEB_HOST"
    echo "  Port: $WEB_PORT"
    if [[ "$WEB_HOST" == "127.0.0.1" ]]; then
        echo "  ⚠ Host is 127.0.0.1 (localhost only) - not accessible from network"
        echo "     Recommendation: Set GHOSTROLL_WEB_HOST=0.0.0.0 for network access"
    fi
else
    echo "  ✗ Web interface is DISABLED"
    echo "     Set GHOSTROLL_WEB_ENABLED=1 to enable"
fi
echo ""

# Check if service is running
echo "Service Status:"
if systemctl is-active ghostroll-watch.service >/dev/null 2>&1; then
    echo "  ✓ ghostroll-watch.service is RUNNING"
else
    echo "  ✗ ghostroll-watch.service is NOT RUNNING"
    echo "     Start with: sudo systemctl start ghostroll-watch.service"
fi
echo ""

# Check if port is in use
echo "Port Status:"
if command -v netstat >/dev/null 2>&1; then
    if netstat -tuln 2>/dev/null | grep -q ":$WEB_PORT "; then
        echo "  ✓ Port $WEB_PORT is in use (likely the web server)"
    else
        echo "  ✗ Port $WEB_PORT is NOT in use"
    fi
elif command -v ss >/dev/null 2>&1; then
    if ss -tuln 2>/dev/null | grep -q ":$WEB_PORT "; then
        echo "  ✓ Port $WEB_PORT is in use (likely the web server)"
    else
        echo "  ✗ Port $WEB_PORT is NOT in use"
    fi
else
    echo "  ? Cannot check port status (netstat/ss not available)"
fi
echo ""

# Check service logs
echo "Recent Service Logs (last 20 lines):"
echo "  Looking for 'Web interface enabled' or 'Failed to start web server'..."
journalctl -u ghostroll-watch.service -n 20 --no-pager 2>/dev/null | grep -i "web\|port\|808" || echo "  (No relevant logs found)"
echo ""

# Check if status.json exists
STATUS_PATH="${GHOSTROLL_STATUS_PATH:-/home/pi/ghostroll/status.json}"
if [[ -f "$STATUS_PATH" ]]; then
    echo "✓ Status file exists: $STATUS_PATH"
    if command -v curl >/dev/null 2>&1; then
        echo ""
        echo "Testing web interface:"
        if curl -s -o /dev/null -w "%{http_code}" "http://$WEB_HOST:$WEB_PORT/status.json" 2>/dev/null | grep -q "200"; then
            echo "  ✓ Web interface is RESPONDING at http://$WEB_HOST:$WEB_PORT/"
            echo "  ✓ You can access it at: http://$(hostname -I | awk '{print $1}'):$WEB_PORT/"
        else
            echo "  ✗ Web interface is NOT responding at http://$WEB_HOST:$WEB_PORT/"
        fi
    fi
else
    echo "⚠ Status file not found: $STATUS_PATH"
fi
echo ""

# Summary and recommendations
echo "Recommendations:"
echo "  1. Ensure /etc/ghostroll.env contains:"
echo "     GHOSTROLL_WEB_ENABLED=1"
if [[ "$WEB_HOST" == "127.0.0.1" ]]; then
    echo "     GHOSTROLL_WEB_HOST=0.0.0.0  (for network access)"
fi
if [[ "$WEB_PORT" == "8080" ]] && [[ -f /etc/ghostroll.env ]] && grep -q "GHOSTROLL_WIFI_PORTAL_PORT=8080" /etc/ghostroll.env 2>/dev/null; then
    echo "     GHOSTROLL_WEB_PORT=8081  (to avoid WiFi portal conflict)"
fi
echo ""
echo "  2. Restart the service:"
echo "     sudo systemctl restart ghostroll-watch.service"
echo ""
echo "  3. Check logs:"
echo "     sudo journalctl -u ghostroll-watch.service -f"
echo ""
echo "  4. Access the web interface:"
if [[ "$WEB_HOST" == "0.0.0.0" ]]; then
    PI_IP=$(hostname -I | awk '{print $1}' 2>/dev/null || echo "<pi-ip>")
    echo "     http://$PI_IP:$WEB_PORT/"
else
    echo "     http://$WEB_HOST:$WEB_PORT/ (localhost only)"
    echo "     For network access, set GHOSTROLL_WEB_HOST=0.0.0.0"
fi
echo ""

