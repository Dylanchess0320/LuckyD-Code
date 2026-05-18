#!/usr/bin/env bash
# LuckyD Code — one-click launcher for Linux
# Usage: ./"Install and Run - Linux.sh"           (CLI mode)
#        ./"Install and Run - Linux.sh" --web     (Web UI mode)
#
# For Mac, use: Install and Run - Mac.command (double-clickable Finder shortcut)

set -euo pipefail
cd "$(dirname "$0")"

# Colors
CY='\033[0;36m'; GR='\033[0;32m'; YL='\033[0;33m'; RD='\033[0;31m'; NC='\033[0m'

clear
echo ""
echo -e "${CY}  LuckyD Code v1.3.3${NC}"
echo "  AI coding assistant powered by DeepSeek API"
echo "  ─────────────────────────────────────────────"
echo ""

# Python check — find python3.10+ (prefer python3 over python)
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        MINOR=$("$cmd" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)
        MAJOR=$("$cmd" -c 'import sys; print(sys.version_info.major)' 2>/dev/null || echo 0)
        if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 10 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "  ${RD}[ERROR]${NC} Python 3.10+ not found."
    echo ""
    echo "  Install via your package manager:"
    echo "    Ubuntu/Debian:  sudo apt install python3 python3-venv python3-pip"
    echo "    Fedora:         sudo dnf install python3"
    echo "    Arch:           sudo pacman -S python"
    echo "  Or download from: https://www.python.org/downloads/"
    echo ""
    read -r -p "  Press Enter to close..."
    exit 1
fi

# Venv
if [ ! -f ".venv/bin/activate" ]; then
    echo "  [1/3] Creating virtual environment..."
    "$PYTHON" -m venv .venv
fi

source .venv/bin/activate

# Dependencies
NEEDS_INSTALL=0
if ! pip show rich &>/dev/null; then
    NEEDS_INSTALL=1
fi
# Also reinstall if pyproject.toml is newer than the last install marker
MARKER=".venv/.last_install"
if [ -f "pyproject.toml" ] && \
   { [ ! -f "$MARKER" ] || [ "pyproject.toml" -nt "$MARKER" ]; }; then
    NEEDS_INSTALL=1
fi

if [ "$NEEDS_INSTALL" -eq 1 ]; then
    echo "  [2/3] Installing dependencies (first run only, ~1 min)..."
    echo "        Upgrading pip..."
    python -m pip install --upgrade pip -q
    echo "        Installing packages..."
    pip install -e .
    if [ $? -ne 0 ]; then
        echo ""
        echo -e "  ${RD}[ERROR]${NC} Installation failed. See error above."
        echo "         Common fixes:"
        echo "         - Check your internet connection"
        echo "         - Make sure python3-venv is installed"
        echo "           (sudo apt install python3-venv on Debian/Ubuntu)"
        read -r -p "  Press Enter to close..."
        exit 1
    fi
    echo -e "  ${GR}[2/3] Done.${NC}"
    touch "$MARKER"
fi

# Dev dependencies (pytest-asyncio for test suite)
if ! pip show pytest-asyncio &>/dev/null; then
    pip install "pytest-asyncio>=0.21.0" -q
fi

# Optional extras — only install once (guarded to avoid hanging on every launch)
OPT_MARKER=".venv/.last_optional_install"
if [ ! -f "$OPT_MARKER" ]; then
    pip install -e ".[browser,rag,game]" -q 2>/dev/null || true
    touch "$OPT_MARKER"
fi
if pip show playwright &>/dev/null; then
    playwright install chromium --quiet 2>/dev/null || true
fi

# Desktop shortcut — create a .desktop file so users can launch from their app menu
DESKTOP_FILE="$HOME/.local/share/applications/luckyd-code.desktop"
if [ ! -f "$DESKTOP_FILE" ]; then
    mkdir -p "$HOME/.local/share/applications"
    # POSIX-compatible absolute path resolution (no realpath dependency)
    LAUNCHER_DIR="$(cd "$(dirname "$0")" && pwd)"
    LAUNCHER_PATH="$LAUNCHER_DIR/Install and Run - Linux.sh"
    cat > "$DESKTOP_FILE" << DESKTOP_EOF
[Desktop Entry]
Name=LuckyD Code
Comment=AI coding assistant powered by DeepSeek
Exec=bash "$LAUNCHER_PATH"
Path=$LAUNCHER_DIR
Type=Application
Terminal=true
Categories=Development;IDE;
Icon=terminal
DESKTOP_EOF
    # Also create a symlink on the Desktop for convenience
    DESKTOP_LINK="$HOME/Desktop/LuckyD Code.desktop"
    if [ -d "$HOME/Desktop" ] && [ ! -f "$DESKTOP_LINK" ]; then
        cp "$DESKTOP_FILE" "$DESKTOP_LINK" 2>/dev/null || true
    fi
    echo -e "  ${GR}Desktop shortcut added.${NC}"
fi

# .env setup
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
    else
        echo "DEEPSEEK_API_KEY=sk-your-key-here" > .env
    fi
    echo ""
    echo "  [3/3] No API key found. Get one free at:"
    echo "        https://platform.deepseek.com/api_keys"
    # Try to open the URL in the user's browser
    if command -v xdg-open &>/dev/null; then
        xdg-open "https://platform.deepseek.com/api_keys" 2>/dev/null || true
    fi
    echo ""
    read -r -p "  Paste your DeepSeek API key (starts with sk-): " API_KEY
    API_KEY="${API_KEY// /}"
    if [[ "$API_KEY" == sk-* ]]; then
        sed -i.bak "s|DEEPSEEK_API_KEY=.*|DEEPSEEK_API_KEY=$API_KEY|" .env && rm -f .env.bak
        echo -e "  ${GR}API key saved.${NC}"
    else
        echo -e "  ${YL}[WARN]${NC} Key not saved — edit .env manually."
    fi
    echo ""
fi

# API key check
KEY_OK=0
while IFS='=' read -r K V; do
    [[ "$K" == "DEEPSEEK_API_KEY" && -n "$V" && "$V" != *"your-key"* ]] && KEY_OK=1
done < .env 2>/dev/null || true

if [ "$KEY_OK" -eq 0 ]; then
    echo -e "  ${YL}[WARN]${NC} No API key detected in .env"
    echo "         Edit .env and set: DEEPSEEK_API_KEY=sk-xxxxxxxxxx"
    echo "         Get a key at: https://platform.deepseek.com/api_keys"
    read -r -p "  Press Enter to continue anyway..."
fi

# Launch — forward all CLI args (main.py handles --web, --port, --model, etc.
# Terminal resize is handled by Python's cli_utils.resize_terminal(), which
# respects user settings like auto_resize_terminal and terminal_columns/rows.)
clear
if [[ "${1:-}" == "--web" || "${1:-}" == "-w" ]]; then
    echo "  Starting Web UI at http://localhost:8000"
    echo "  Press Ctrl+C to stop."
    echo ""
fi
exec python main.py "$@"
