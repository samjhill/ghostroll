#!/usr/bin/env bash
# Test the complete GhostRoll software stack with the latest S3 session
# Run this on the Pi or locally with AWS credentials configured

set -euo pipefail

echo "🧪 Testing GhostRoll software stack with latest S3 session"
echo "=" * 60

# Load config from environment or defaults
BUCKET="${GHOSTROLL_S3_BUCKET:-photo-ingest-project}"
BASE_DIR="${GHOSTROLL_BASE_DIR:-$HOME/ghostroll}"

echo "📊 Configuration:"
echo "  S3 Bucket: $BUCKET"
echo "  Base dir: $BASE_DIR"
echo ""

# Find latest session from S3
echo "🔍 Finding latest session in S3..."
LATEST_SESSION=$(aws s3 ls s3://$BUCKET/sessions/ | grep "PRE" | awk '{print $2}' | sed 's|/$||' | sort -r | head -1)

if [ -z "$LATEST_SESSION" ]; then
    echo "❌ No sessions found in S3"
    exit 1
fi

echo "✅ Latest session: $LATEST_SESSION"
echo ""

# Check session contents in S3
echo "📁 Session contents in S3:"
aws s3 ls s3://$BUCKET/sessions/$LATEST_SESSION/ --recursive | head -20
echo ""

# Check if session exists locally
SESSION_DIR="$BASE_DIR/$LATEST_SESSION"
echo "📂 Local session directory: $SESSION_DIR"

if [ -d "$SESSION_DIR" ]; then
    echo "✅ Session exists locally"
    echo "   Files:"
    find "$SESSION_DIR" -type f | head -10
    if [ $(find "$SESSION_DIR" -type f | wc -l) -gt 10 ]; then
        echo "   ... and more"
    fi
else
    echo "⚠️  Session not found locally (may need to download from S3)"
fi

echo ""

# Test web interface (if running)
echo "🌐 Testing web interface..."
WEB_PORT="${GHOSTROLL_WEB_PORT:-8081}"
WEB_HOST="${GHOSTROLL_WEB_HOST:-127.0.0.1}"

# Check if web interface is responding
if curl -s --max-time 2 "http://$WEB_HOST:$WEB_PORT/" >/dev/null 2>&1; then
    echo "✅ Web interface is responding on http://$WEB_HOST:$WEB_PORT/"
    
    # Test key endpoints
    echo "   Testing endpoints:"
    
    ENDPOINTS=(
        "/"
        "/status.json"
        "/sessions"
        "/sessions/$LATEST_SESSION/index.html"
    )
    
    for endpoint in "${ENDPOINTS[@]}"; do
        URL="http://$WEB_HOST:$WEB_PORT$endpoint"
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$URL" 2>/dev/null || echo "000")
        if [ "$HTTP_CODE" = "200" ]; then
            echo "     ✓ $endpoint -> HTTP $HTTP_CODE"
        else
            echo "     ✗ $endpoint -> HTTP $HTTP_CODE"
        fi
    done
    
    echo ""
    echo "   🌐 Web interface URL: http://$WEB_HOST:$WEB_PORT/"
    echo "   📊 Latest session: $LATEST_SESSION"
    echo "   🔗 Session gallery: http://$WEB_HOST:$WEB_PORT/sessions/$LATEST_SESSION/"
else
    echo "⚠️  Web interface not responding on http://$WEB_HOST:$WEB_PORT/"
    echo "   (This is OK if the web interface is disabled or not running)"
fi

echo ""

# Test S3 gallery access
echo "☁️  Testing S3 gallery access..."
GALLERY_URL=$(aws s3 presign "s3://$BUCKET/sessions/$LATEST_SESSION/index.html" --expires-in 300 2>/dev/null || echo "")

if [ -n "$GALLERY_URL" ]; then
    echo "✅ Gallery URL generated (5 min expiry):"
    echo "   $GALLERY_URL"
    echo ""
    
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$GALLERY_URL" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        echo "✅ Gallery is accessible via S3 (HTTP $HTTP_CODE)"
    else
        echo "⚠️  Gallery returned HTTP $HTTP_CODE"
    fi
else
    echo "⚠️  Could not generate gallery URL"
fi

echo ""
echo "✅ Complete software stack test finished!"
echo ""
echo "Summary:"
echo "  Latest session: $LATEST_SESSION"
echo "  Local directory: $SESSION_DIR"
echo "  Web interface: http://$WEB_HOST:$WEB_PORT/"
echo "  S3 bucket: s3://$BUCKET/sessions/$LATEST_SESSION/"
