#!/bin/bash
# GhostRoll setup script - automated installation and initial configuration

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

VENV_NAME="${VENV_NAME:-.venv}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}GhostRoll Setup${NC}"
echo "================"
echo ""

# Check Python version (prefer 3.10+; macOS Xcode python is often 3.9)
echo -e "${BLUE}Checking Python version...${NC}"
PYTHON_CMD="${GHOSTROLL_PYTHON:-}"
if [ -z "$PYTHON_CMD" ]; then
    for cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$cand" &> /dev/null; then
            if "$cand" -c 'import sys; assert sys.version_info >= (3, 10)' 2>/dev/null; then
                PYTHON_CMD=$(command -v "$cand")
                break
            fi
        fi
    done
fi
if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}Error: Python 3.10+ not found (python3 is often 3.9 on macOS).${NC}"
    echo "  Install e.g. Homebrew Python, then re-run, or set GHOSTROLL_PYTHON=/path/to/python3.12"
    exit 1
fi

PYTHON_VERSION=$("$PYTHON_CMD" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "${GREEN}✓ Using $PYTHON_CMD (Python $PYTHON_VERSION)${NC}"
echo ""

# Create virtual environment
echo -e "${BLUE}Creating virtual environment...${NC}"
if [ -d "$VENV_NAME" ]; then
    echo -e "${YELLOW}Virtual environment '$VENV_NAME' already exists.${NC}"
    read -p "Remove and recreate? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$VENV_NAME"
        "$PYTHON_CMD" -m venv "$VENV_NAME"
        echo -e "${GREEN}✓ Virtual environment created${NC}"
    else
        echo -e "${YELLOW}Using existing virtual environment${NC}"
    fi
else
    "$PYTHON_CMD" -m venv "$VENV_NAME"
    echo -e "${GREEN}✓ Virtual environment created${NC}"
fi
echo ""

# Activate virtual environment
echo -e "${BLUE}Activating virtual environment...${NC}"
source "$VENV_NAME/bin/activate"
echo -e "${GREEN}✓ Virtual environment activated${NC}"
echo ""

# Upgrade pip
echo -e "${BLUE}Upgrading pip...${NC}"
pip install -U pip -q
echo -e "${GREEN}✓ pip upgraded${NC}"
echo ""

# Install GhostRoll
echo -e "${BLUE}Installing GhostRoll...${NC}"
pip install -e . -q
echo -e "${GREEN}✓ GhostRoll installed${NC}"
echo ""

# Check if ghostroll command works
if ! command -v ghostroll &> /dev/null; then
    echo -e "${RED}Error: ghostroll command not found after installation${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Setup complete!${NC}"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo ""
echo "1. Activate the virtual environment:"
echo -e "   ${GREEN}source $VENV_NAME/bin/activate${NC}"
echo ""
echo "2. Configure AWS credentials:"
echo -e "   ${GREEN}aws configure${NC}"
echo -e "   ${GREEN}aws sts get-caller-identity${NC}"
echo ""
echo "3. Run interactive setup (recommended):"
echo -e "   ${GREEN}ghostroll setup${NC}"
echo ""
echo "   Or run a quick health check:"
echo -e "   ${GREEN}ghostroll doctor${NC}"
echo ""
echo "4. Start watching for SD cards:"
echo -e "   ${GREEN}ghostroll watch${NC}"
echo ""

