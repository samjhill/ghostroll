#!/usr/bin/env bash
set -euo pipefail

# Install Waveshare e-Paper library for Raspberry Pi
# This script installs from the GitHub repo since pip package may not work on Bookworm

if [[ "${EUID}" -ne 0 ]]; then
  echo "This script must be run as root. Try: sudo $0" >&2
  exit 2
fi

REPO_URL="https://github.com/waveshareteam/e-Paper.git"
TEMP_DIR="/tmp/waveshare-epaper-install"
LIB_SOURCE="${TEMP_DIR}/RaspberryPi_JetsonNano/python/lib"

echo "Installing Waveshare e-Paper library..."

# Clean up any existing temp directory
rm -rf "${TEMP_DIR}"

# Clone the repository
echo "Cloning Waveshare e-Paper repository..."
git clone --depth 1 "${REPO_URL}" "${TEMP_DIR}" || {
  echo "Failed to clone repository. Check internet connection." >&2
  exit 1
}

# Find Python site-packages directory
PYTHON_VERSION=$(python3 --version | grep -oP '\d+\.\d+' | head -1)
SITE_PACKAGES=""

# Try to find site-packages in common locations
for path in \
  "/usr/local/lib/python${PYTHON_VERSION}/site-packages" \
  "/usr/lib/python${PYTHON_VERSION}/site-packages" \
  "$(python3 -c 'import site; print(site.getsitepackages()[0])' 2>/dev/null || echo '')"; do
  if [[ -n "${path}" && -d "${path}" ]]; then
    SITE_PACKAGES="${path}"
    break
  fi
done

if [[ -z "${SITE_PACKAGES}" ]]; then
  echo "Could not find Python site-packages directory." >&2
  echo "Python version: ${PYTHON_VERSION}" >&2
  exit 1
fi

echo "Installing to: ${SITE_PACKAGES}"

# Copy library files
if [[ ! -d "${LIB_SOURCE}" ]]; then
  echo "Library source directory not found: ${LIB_SOURCE}" >&2
  exit 1
fi

echo "Copying library files..."
cp -r "${LIB_SOURCE}"/* "${SITE_PACKAGES}/" || {
  echo "Failed to copy library files." >&2
  exit 1
}

# Clean up
rm -rf "${TEMP_DIR}"

echo ""
echo "Waveshare e-Paper library installed successfully!"
echo ""
echo "To verify, try:"
echo "  python3 -c 'from waveshare_epd import epd2in13_V4; print(\"OK\")'"
echo ""

