#!/usr/bin/env bash
set -euo pipefail

# Diagnostic and fix script for ghostroll service
# Run: sudo ./pi/scripts/fix-ghostroll-service.sh

REPO_DIR="${1:-/home/pi/ghostroll}"

echo "=== GhostRoll Service Diagnostic & Fix ==="
echo ""

# Check if repo exists
if [[ ! -d "$REPO_DIR" ]]; then
    echo "Error: GhostRoll repo not found at $REPO_DIR" >&2
    echo "Usage: sudo $0 [REPO_DIR]" >&2
    exit 1
fi

cd "$REPO_DIR"

# Check current service status
echo "1. Checking current service status..."
if systemctl is-active ghostroll-watch.service >/dev/null 2>&1; then
    echo "   Service is currently running"
elif systemctl is-failed ghostroll-watch.service >/dev/null 2>&1; then
    echo "   Service is in failed state"
else
    echo "   Service is not running"
fi

# Check where ghostroll is installed
echo ""
echo "2. Checking ghostroll installation..."
GHOSTROLL_PATH=""
INSTALL_METHOD=""

if [ -x "/home/pi/ghostroll/.venv/bin/ghostroll" ]; then
    GHOSTROLL_PATH="/home/pi/ghostroll/.venv/bin/ghostroll"
    INSTALL_METHOD="venv"
    echo "   Found: $GHOSTROLL_PATH (venv)"
elif [ -x "/usr/local/bin/ghostroll" ]; then
    GHOSTROLL_PATH="/usr/local/bin/ghostroll"
    INSTALL_METHOD="system"
    echo "   Found: $GHOSTROLL_PATH (system-wide)"
else
    echo "   Not found. Will install..."
fi

# Install if missing
if [[ -z "$GHOSTROLL_PATH" ]]; then
    echo ""
    echo "3. Installing ghostroll..."
    
    # Check if venv exists
    if [ -x "/home/pi/ghostroll/.venv/bin/python" ]; then
        echo "   Using venv installation..."
        /home/pi/ghostroll/.venv/bin/pip install -U pip >/dev/null 2>&1 || true
        /home/pi/ghostroll/.venv/bin/pip install -e "$REPO_DIR" 2>&1 | grep -v "Requirement already satisfied" || true
        if [ -x "/home/pi/ghostroll/.venv/bin/ghostroll" ]; then
            GHOSTROLL_PATH="/home/pi/ghostroll/.venv/bin/ghostroll"
            INSTALL_METHOD="venv"
            echo "   ✓ Installed to venv"
        else
            echo "   ✗ Venv installation failed"
        fi
    else
        echo "   Using system-wide installation..."
        python3 -m pip install -U pip --break-system-packages >/dev/null 2>&1 || true
        python3 -m pip install -e "$REPO_DIR" --break-system-packages 2>&1 | grep -v "Requirement already satisfied" || true
        if [ -x "/usr/local/bin/ghostroll" ]; then
            GHOSTROLL_PATH="/usr/local/bin/ghostroll"
            INSTALL_METHOD="system"
            echo "   ✓ Installed system-wide"
        else
            echo "   ✗ System-wide installation failed"
        fi
    fi
fi

# Verify installation
if [[ -z "$GHOSTROLL_PATH" ]] || [[ ! -x "$GHOSTROLL_PATH" ]]; then
    echo ""
    echo "Error: ghostroll is not installed or not executable" >&2
    echo "Tried to install but failed. Check the errors above." >&2
    exit 1
fi

# Test the command
echo ""
echo "4. Testing ghostroll command..."
if "$GHOSTROLL_PATH" --help >/dev/null 2>&1; then
    echo "   ✓ Command works"
else
    echo "   ✗ Command test failed"
    exit 1
fi

# Update service file
echo ""
echo "5. Updating service file..."
SERVICE_FILE="/etc/systemd/system/ghostroll-watch.service"
if [[ "$INSTALL_METHOD" == "venv" ]]; then
    # For venv, we need to use the full path
    sed -i "s|ExecStart=.*|ExecStart=$GHOSTROLL_PATH watch|" "$SERVICE_FILE" 2>/dev/null || {
        # If sed fails, create a new service file
        cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=GhostRoll watch (SD ingest pipeline)
After=ghostroll-wifi-setup.service network-online.target ghostroll-firstboot.service
Wants=ghostroll-wifi-setup.service network-online.target

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/home/pi
EnvironmentFile=-/etc/ghostroll.env
ExecStart=$GHOSTROLL_PATH watch
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
    }
    echo "   Updated to use: $GHOSTROLL_PATH"
else
    # System-wide should already be correct, but verify
    if ! grep -q "ExecStart=$GHOSTROLL_PATH" "$SERVICE_FILE" 2>/dev/null; then
        sed -i "s|ExecStart=.*|ExecStart=$GHOSTROLL_PATH watch|" "$SERVICE_FILE" 2>/dev/null || true
        echo "   Updated to use: $GHOSTROLL_PATH"
    else
        echo "   Already configured correctly"
    fi
fi

# Reload and restart
echo ""
echo "6. Reloading systemd and restarting service..."
systemctl daemon-reload
systemctl restart ghostroll-watch.service

# Wait a moment and check status
sleep 2

echo ""
echo "7. Service status:"
systemctl status ghostroll-watch.service --no-pager -l || true

echo ""
echo "=== Done ==="
echo ""
echo "To view logs: sudo journalctl -u ghostroll-watch.service -f"
