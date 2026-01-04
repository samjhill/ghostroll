#!/usr/bin/env bash
# Test the e-ink processing script locally on macOS
# This processes status.png and saves the result without needing hardware

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATUS_PNG="${1:-${HOME}/ghostroll/status.png}"
OUTPUT_PNG="${2:-${HOME}/ghostroll/status-eink-processed.png}"

if [[ ! -f "${STATUS_PNG}" ]]; then
    echo "Error: status.png not found at ${STATUS_PNG}" >&2
    echo "Usage: $0 [status.png path] [output.png path]" >&2
    exit 1
fi

echo "Processing ${STATUS_PNG} -> ${OUTPUT_PNG}"
echo ""

# Try to use venv if it exists
PYTHON="python3"
if [[ -d "${SCRIPT_DIR}/.venv" ]]; then
    echo "Using virtual environment: .venv"
    PYTHON="${SCRIPT_DIR}/.venv/bin/python"
elif [[ -d "${SCRIPT_DIR}/venv" ]]; then
    echo "Using virtual environment: venv"
    PYTHON="${SCRIPT_DIR}/venv/bin/python"
else
    echo "No virtual environment found. Checking if Pillow is installed..."
    if ! "${PYTHON}" -c "import PIL" 2>/dev/null; then
        echo "Error: Pillow is not installed." >&2
        echo "Please install it:" >&2
        echo "  python3 -m venv .venv" >&2
        echo "  source .venv/bin/activate" >&2
        echo "  pip install Pillow" >&2
        exit 1
    fi
fi

# Set up environment for test mode
export GHOSTROLL_EINK_TEST_MODE=1
export GHOSTROLL_EINK_ENABLE=1  # Enable even in test mode
export GHOSTROLL_STATUS_IMAGE_PATH="${STATUS_PNG}"
export GHOSTROLL_EINK_TEST_OUTPUT="${OUTPUT_PNG}"
export GHOSTROLL_EINK_WIDTH=250
export GHOSTROLL_EINK_HEIGHT=122
export GHOSTROLL_EINK_REFRESH_SECONDS=1

# Run the script (it will process once and exit in test mode)
"${PYTHON}" "${SCRIPT_DIR}/pi/scripts/ghostroll-eink-waveshare213v4.py"

echo ""
echo "Processed image saved to: ${OUTPUT_PNG}"
echo "Open it with: open ${OUTPUT_PNG}"

