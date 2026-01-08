#!/usr/bin/env bash
# Diagnostic script to check why git commit hash isn't showing in web interface
# Run this ON the Pi: ./check-git-info.sh

set -euo pipefail

echo "=== Web Interface Git Info Diagnostic ==="
echo ""

# 1. Check current git commit
echo "1. Current Git Commit:"
cd ~/ghostroll 2>/dev/null || cd /home/pi/ghostroll 2>/dev/null || { echo "   ✗ Cannot find ghostroll directory"; exit 1; }
CURRENT_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "NOT_IN_GIT_REPO")
CURRENT_SHORT=$(git rev-parse --short HEAD 2>/dev/null || echo "N/A")
echo "   Commit: $CURRENT_SHORT ($CURRENT_COMMIT)"
echo "   Branch: $(git branch --show-current 2>/dev/null || echo 'N/A')"
echo ""

# 2. Check if we have the latest code with git info
echo "2. Checking for git info code in web.py:"
if grep -q "_cached_git_info" ghostroll/web.py 2>/dev/null; then
    echo "   ✓ Git info caching code is present"
else
    echo "   ✗ Git info caching code is missing"
    echo "   You need to pull the latest code: git pull"
fi
echo ""

# 3. Test git info function directly
echo "3. Testing git info function:"
python3 <<'PYTHON'
try:
    from ghostroll.web import _get_git_info
    commit_hash, repo_url = _get_git_info()
    if commit_hash:
        short_hash = commit_hash[:7]
        print(f"   ✓ Git info found:")
        print(f"     Commit: {short_hash}")
        print(f"     Repo: {repo_url or 'None'}")
    else:
        print("   ✗ Git info not found")
        print("     Possible causes:")
        print("     - Not in a git repository")
        print("     - Git is not installed")
        print("     - Repository directory not found")
except Exception as e:
    print(f"   ✗ Error testing git info: {e}")
PYTHON
echo ""

# 4. Check if git is installed
echo "4. Checking if git is installed:"
if command -v git >/dev/null 2>&1; then
    echo "   ✓ Git is installed: $(git --version)"
else
    echo "   ✗ Git is NOT installed"
    echo "   Install with: sudo apt-get install git"
fi
echo ""

# 5. Check if .git directory exists
echo "5. Checking for .git directory:"
if [[ -d ".git" ]]; then
    echo "   ✓ .git directory exists"
    echo "   Location: $(pwd)/.git"
else
    echo "   ✗ .git directory NOT found"
    echo "   Current directory: $(pwd)"
    echo "   Checking common locations..."
    for dir in /home/pi/ghostroll /usr/local/src/ghostroll "$(python3 -c 'import ghostroll.web; import os; print(os.path.dirname(os.path.dirname(ghostroll.web.__file__)))')"; do
        if [[ -d "$dir/.git" ]]; then
            echo "   ✓ Found .git at: $dir/.git"
        fi
    done
fi
echo ""

# 6. Check web server logs for git info
echo "6. Checking web server logs for git info messages:"
if systemctl is-active ghostroll-watch.service >/dev/null 2>&1; then
    echo "   Service is active, checking logs..."
    if sudo journalctl -u ghostroll-watch.service -n 100 --no-pager 2>/dev/null | grep -i "ghostroll-web.*git" >/dev/null; then
        echo "   ✓ Found git info messages in logs:"
        sudo journalctl -u ghostroll-watch.service -n 100 --no-pager 2>/dev/null | grep -i "ghostroll-web.*git" | tail -3
    else
        echo "   ⚠ No git info messages found in recent logs"
        echo "   The web server may not have the latest code, or git info failed silently"
    fi
else
    echo "   ⚠ ghostroll-watch.service is not active"
fi
echo ""

# 7. Check web interface response
echo "7. Testing web interface response:"
WEB_HOST="${GHOSTROLL_WEB_HOST:-127.0.0.1}"
WEB_PORT="${GHOSTROLL_WEB_PORT:-8081}"
if curl -s --max-time 5 "http://${WEB_HOST}:${WEB_PORT}/" >/dev/null 2>&1; then
    echo "   ✓ Web interface is responding"
    echo "   Checking for commit hash in HTML..."
    if curl -s --max-time 5 "http://${WEB_HOST}:${WEB_PORT}/" | grep -q "version-link\|<code>" 2>/dev/null; then
        echo "   ✓ Footer HTML structure found"
        COMMIT_IN_HTML=$(curl -s --max-time 5 "http://${WEB_HOST}:${WEB_PORT}/" | grep -oE 'class="version-link"[^>]*>.*<code>[^<]+</code>' | head -1 || echo "")
        if [[ -n "$COMMIT_IN_HTML" ]]; then
            echo "   ✓ Commit hash found in HTML!"
            echo "     $COMMIT_IN_HTML"
        else
            echo "   ✗ Commit hash NOT found in HTML"
            echo "   Check the footer manually at: http://${WEB_HOST}:${WEB_PORT}/"
        fi
    else
        echo "   ⚠ Could not parse HTML response"
    fi
else
    echo "   ✗ Web interface is not responding at http://${WEB_HOST}:${WEB_PORT}/"
fi
echo ""

# 8. Recommendations
echo "=== Recommendations ==="
echo ""
if [[ "$CURRENT_COMMIT" == "NOT_IN_GIT_REPO" ]]; then
    echo "❌ NOT in a git repository. To fix:"
    echo "   1. cd ~/ghostroll"
    echo "   2. git init"
    echo "   3. git remote add origin <your-repo-url>"
    echo "   4. git pull origin main"
elif ! grep -q "_cached_git_info" ghostroll/web.py 2>/dev/null; then
    echo "❌ Code is missing git info functionality. To fix:"
    echo "   1. cd ~/ghostroll"
    echo "   2. git pull"
    echo "   3. sudo pip install -e . --break-system-packages"
    echo "   4. sudo systemctl restart ghostroll-watch.service"
elif ! command -v git >/dev/null 2>&1; then
    echo "❌ Git is not installed. To fix:"
    echo "   sudo apt-get update && sudo apt-get install -y git"
else
    echo "✓ Code appears to be up to date. If commit hash still doesn't show:"
    echo "   1. Restart the service: sudo systemctl restart ghostroll-watch.service"
    echo "   2. Check logs: sudo journalctl -u ghostroll-watch.service -n 50 --no-pager | grep git"
    echo "   3. Verify git detection: python3 -c 'from ghostroll.web import _get_git_info; print(_get_git_info())'"
fi
echo ""

