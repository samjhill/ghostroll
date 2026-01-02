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

# Check Python version
echo -e "${BLUE}Checking Python version...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 not found. Please install Python 3.10 or later.${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    echo -e "${RED}Error: Python 3.10 or later required. Found Python $PYTHON_VERSION${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Python $PYTHON_VERSION found${NC}"
echo ""

# Create virtual environment
echo -e "${BLUE}Creating virtual environment...${NC}"
if [ -d "$VENV_NAME" ]; then
    echo -e "${YELLOW}Virtual environment '$VENV_NAME' already exists.${NC}"
    read -p "Remove and recreate? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$VENV_NAME"
        python3 -m venv "$VENV_NAME"
        echo -e "${GREEN}✓ Virtual environment created${NC}"
    else
        echo -e "${YELLOW}Using existing virtual environment${NC}"
    fi
else
    python3 -m venv "$VENV_NAME"
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

