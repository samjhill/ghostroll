#!/usr/bin/env bash
# Diagnostic script to check SSH and network connectivity issues on Raspberry Pi
# Usage: ./diagnose-ssh-issues.sh [PI_IP] [USERNAME]
# Default: PI_IP=192.168.2.35, USERNAME=pi

PI_IP="${1:-192.168.2.35}"
PI_USER="${2:-pi}"

echo "=== SSH and Network Connectivity Diagnostics ==="
echo "Target: ${PI_USER}@${PI_IP}"
echo ""

# Check if we can ping the Pi
echo "1. Testing network connectivity (ping - 10 packets)..."
PING_RESULT=$(ping -c 10 -W 2 ${PI_IP} 2>&1 | tail -3)
if echo "$PING_RESULT" | grep -q "packet loss"; then
    echo "$PING_RESULT" | head -1
    LOSS=$(echo "$PING_RESULT" | grep "packet loss" | grep -oE "[0-9]+%" || echo "0%")
    if [[ "$LOSS" == "0%" ]]; then
        echo "   ✓ Pi is reachable (no packet loss)"
    else
        echo "   ⚠ Pi has ${LOSS} packet loss - network may be spotty"
    fi
    RTT=$(echo "$PING_RESULT" | grep "round-trip" || echo "")
    if [[ -n "$RTT" ]]; then
        echo "   $RTT"
        MAX_RTT=$(echo "$RTT" | grep -oE "max = [0-9.]+" | cut -d' ' -f3)
        if [[ -n "$MAX_RTT" ]] && (( $(echo "$MAX_RTT > 100" | bc -l 2>/dev/null || echo 0) )); then
            echo "   ⚠ High latency detected (max: ${MAX_RTT}ms) - Pi may be slow/overloaded"
        fi
    fi
else
    echo "   ✗ Pi is NOT reachable on network"
    echo "   Check: Is Pi powered on? Is it on the same network?"
fi
echo ""

# Check SSH port
echo "2. Testing SSH port (22)..."
if command -v nc >/dev/null 2>&1; then
    if timeout 3 nc -z -w2 ${PI_IP} 22 2>/dev/null; then
        echo "   ✓ SSH port is open and responding"
    else
        echo "   ✗ SSH port is not accessible or slow to respond"
        echo "   Check: Is SSH enabled? Is port 22 blocked by firewall?"
    fi
elif timeout 3 bash -c "echo >/dev/tcp/${PI_IP}/22" 2>/dev/null 2>&1; then
    echo "   ✓ SSH port is open"
else
    echo "   ✗ SSH port is not accessible"
    echo "   Check: Is SSH enabled? Is port 22 blocked by firewall?"
fi
echo ""

# Try SSH connection with extended timeout and keepalive
echo "3. Attempting SSH connection (with keepalive)..."
SSH_CMD="ssh -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=no"
if $SSH_CMD ${PI_USER}@${PI_IP} "echo 'Connection successful'" 2>/dev/null; then
    echo "   ✓ SSH connection successful"
    
    # Get system info
    echo ""
    echo "4. System information from Pi:"
    $SSH_CMD ${PI_USER}@${PI_IP} <<'EOF'
    echo "   Uptime: $(uptime -p 2>/dev/null || uptime)"
    echo "   Load average: $(uptime | awk -F'load average:' '{print $2}' || echo 'N/A')"
    echo "   Memory: $(free -h | grep Mem | awk '{print $3 "/" $2 " used"}' || echo 'N/A')"
    echo "   CPU temperature: $(vcgencmd measure_temp 2>/dev/null | cut -d= -f2 || echo 'N/A')"
    THROTTLED=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2 || echo "N/A")
    if [[ "$THROTTLED" != "N/A" ]] && [[ "$THROTTLED" != "0x0" ]]; then
        echo "   ⚠ THROTTLED: $THROTTLED (Pi is being throttled - check power/temperature)"
    else
        echo "   ✓ Throttled status: $THROTTLED (OK)"
    fi
    echo ""
    echo "   SSH service status:"
    sudo systemctl status ssh --no-pager -l | head -15 || echo "   (Cannot check SSH service status)"
    echo ""
    echo "   Recent SSH connections:"
    sudo journalctl -u ssh -n 10 --no-pager 2>/dev/null | tail -5 || echo "   (Cannot check SSH logs)"
EOF
else
    echo "   ✗ SSH connection failed or timed out"
    echo ""
    echo "   Possible causes:"
    echo "   - Pi is overloaded (check: uptime, free -h)"
    echo "   - Pi is throttling (check: vcgencmd get_throttled)"
    echo "   - Network connectivity issues"
    echo "   - SSH service not responding (check: sudo systemctl status ssh)"
    echo "   - Firewall blocking connections"
fi
echo ""

# Network diagnostics
echo "5. Local network diagnostics:"
if command -v arp >/dev/null 2>&1; then
    echo "   Checking ARP table for Pi MAC address..."
    ARP_ENTRY=$(arp -n ${PI_IP} 2>/dev/null || echo "")
    if [[ -n "$ARP_ENTRY" ]]; then
        echo "   $ARP_ENTRY"
    else
        echo "   ⚠ Pi not found in ARP table - may be on different subnet or sleeping"
    fi
fi

echo ""
echo "=== Recommendations ==="
echo ""
echo "If SSH is spotty, try these on the Pi (if you have physical access):"
echo ""
echo "1. Check system health:"
echo "   uptime"
echo "   free -h"
echo "   vcgencmd measure_temp"
echo "   vcgencmd get_throttled  # Should be 0x0"
echo ""
echo "2. Check SSH service:"
echo "   sudo systemctl status ssh"
echo "   sudo journalctl -u ssh -n 50"
echo "   sudo systemctl restart ssh"
echo ""
echo "3. Check network:"
echo "   ip addr show"
echo "   ping -c 5 8.8.8.8  # Test internet connectivity"
echo ""
echo "4. If Pi is throttling:"
echo "   - Check power supply (use official Pi power adapter, 5V/3A+)"
echo "   - Check temperature (add heatsinks/fan if needed)"
echo "   - Reduce CPU load if possible"
echo ""
echo "5. Network fixes:"
echo "   - Use wired Ethernet instead of WiFi if possible"
echo "   - Disable WiFi power management: sudo iwconfig wlan0 power off"
echo "   - Check router settings for device isolation"
echo ""

