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

# Clone the repository with sparse checkout to only get what we need
echo "Cloning Waveshare e-Paper repository (Raspberry Pi Python lib only)..."
mkdir -p "${TEMP_DIR}"
(
  cd "${TEMP_DIR}"
  git init -q
  git remote add origin "${REPO_URL}"
  git config core.sparseCheckout true
  # Use sparse checkout to only get the Python lib directory
  mkdir -p .git/info
  echo "RaspberryPi_JetsonNano/python/lib/*" > .git/info/sparse-checkout
  # Try different branch names (master or main)
  if ! git pull --depth 1 origin master 2>/dev/null; then
    if ! git pull --depth 1 origin main 2>/dev/null; then
      echo "Sparse checkout failed, trying full shallow clone..." >&2
      cd /
      rm -rf "${TEMP_DIR}"
      # Fallback: full shallow clone but we'll only use what we need
      git clone --depth 1 "${REPO_URL}" "${TEMP_DIR}" || {
        echo "Failed to clone repository. Check internet connection and disk space." >&2
        exit 1
      }
    fi
  fi
)

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

