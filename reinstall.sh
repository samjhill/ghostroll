#!/usr/bin/env bash
# Non-interactive reinstall: stop GhostRoll, remove .venv, recreate, pip install -e.
#
# Usage (from repo root):
#   ./reinstall.sh
#
# Environment:
#   VENV_NAME          Virtualenv directory (default: .venv)
#   GHOSTROLL_PYTHON   Path to python3.10+ (default: first suitable on PATH)
#   SKIP_KILL=1        Do not try to stop running ghostroll processes
#   SKIP_DEV=1         Install without dev extras (no pytest in venv)
#
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

VENV_NAME="${VENV_NAME:-.venv}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${BLUE}GhostRoll reinstall${NC}"
echo "===================="
echo ""

if [[ "${SKIP_KILL:-0}" != "1" ]] && [[ -x "$SCRIPT_DIR/scripts/kill-ghostroll.sh" ]]; then
  echo -e "${BLUE}Stopping any running GhostRoll processes…${NC}"
  "$SCRIPT_DIR/scripts/kill-ghostroll.sh" || true
  echo ""
fi

echo -e "${BLUE}Checking Python (3.10+)…${NC}"
PYTHON_CMD="${GHOSTROLL_PYTHON:-}"
if [[ -z "$PYTHON_CMD" ]]; then
  for cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" &> /dev/null; then
      if "$cand" -c 'import sys; assert sys.version_info >= (3, 10)' 2>/dev/null; then
        PYTHON_CMD=$(command -v "$cand")
        break
      fi
    fi
  done
fi
if [[ -z "$PYTHON_CMD" ]]; then
  echo -e "${RED}Error: Python 3.10+ not found.${NC} Install Homebrew Python or set GHOSTROLL_PYTHON=/path/to/python3.12"
  exit 1
fi
PYTHON_VERSION=$("$PYTHON_CMD" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "${GREEN}✓ Using ${PYTHON_CMD} (Python ${PYTHON_VERSION})${NC}"
echo ""

if [[ -d "$VENV_NAME" ]]; then
  echo -e "${YELLOW}Removing existing ${VENV_NAME}…${NC}"
  rm -rf "$VENV_NAME"
fi

echo -e "${BLUE}Creating virtual environment ${VENV_NAME}…${NC}"
"$PYTHON_CMD" -m venv "$VENV_NAME"
# shellcheck source=/dev/null
source "$VENV_NAME/bin/activate"

echo -e "${BLUE}Upgrading pip…${NC}"
pip install -U pip -q
echo -e "${GREEN}✓ pip ready${NC}"
echo ""

if [[ "${SKIP_DEV:-0}" == "1" ]]; then
  echo -e "${BLUE}Installing GhostRoll (editable, no dev extras)…${NC}"
  pip install -e . -q
else
  echo -e "${BLUE}Installing GhostRoll (editable + dev, for pytest)…${NC}"
  pip install -e ".[dev]" -q
fi

if ! command -v ghostroll &> /dev/null; then
  echo -e "${RED}Error: ghostroll command not found after install${NC}"
  exit 1
fi

echo ""
echo -e "${GREEN}✓ Reinstall complete.${NC}"
echo ""
echo "Activate and run:"
echo -e "  ${GREEN}source ${VENV_NAME}/bin/activate${NC}"
echo -e "  ${GREEN}ghostroll doctor${NC}"
echo -e "  ${GREEN}ghostroll watch${NC}"
echo ""
