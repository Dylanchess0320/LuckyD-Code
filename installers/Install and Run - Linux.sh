#!/usr/bin/env bash
# LuckyD Code — one-click launcher for Linux
# Usage: ./"Install and Run - Linux.sh"           (shows mode menu)
#        ./"Install and Run - Linux.sh" --web     (Web UI mode)
#        ./"Install and Run - Linux.sh" --both    (Web UI + CLI)
#
# For Mac, use: Install and Run - Mac.command (double-clickable Finder shortcut)

set -euo pipefail
cd "$(dirname "$0")"

# Colors
CY='\033[0;36m'; GR='\033[0;32m'; YL='\033[0;33m'; RD='\033[0;31m'; NC='\033[0m'

clear
echo ""
echo -e "${CY}  LuckyD Code v1.3.4${NC}"
echo "  AI coding assistant powered by DeepSeek API"
echo "  ─────────────────────────────────────────────"
echo ""

# ── Pre-flight checks ─────────────────────────────────────────────────────
echo "  Checking prerequisites..."
echo ""

# Python check — find python3.10+
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
    echo -e "  ${RD}[X]${NC} Python 3.10+ not found"
    echo ""
    echo "  Install via your package manager:"
    echo "    Ubuntu/Debian:  sudo apt install python3 python3-venv python3-pip"
    echo "    Fedora:         sudo dnf install python3"
    echo "    Arch:           sudo pacman -S python"
    echo "  Or: https://www.python.org/downloads/"
    echo ""
    read -r -p "  Press Enter to close..."
    exit 1
fi
echo -e "  ${GR}[OK]${NC} $("$PYTHON" --version 2>&1)"

# pip
if "$PYTHON" -m pip --version &>/dev/null; then
    echo -e "  ${GR}[OK]${NC} pip"
else
    echo -e "  ${YL}[!!]${NC} pip missing — install: sudo apt install python3-pip"
fi

# Git (optional)
if command -v git &>/dev/null; then
    echo -e "  ${GR}[OK]${NC} Git"
else
    echo "  [--] Git not found (optional)"
fi

echo ""

# ── Mode selection ─────────────────────────────────────────────────────────
LAUNCH_CLI=0
LAUNCH_WEB=0

for arg in "$@"; do
    case "$arg" in
        --web|-w) LAUNCH_WEB=1 ;;
        --both)   LAUNCH_CLI=1; LAUNCH_WEB=1 ;;
    esac
done

if [ "$LAUNCH_CLI" -eq 0 ] && [ "$LAUNCH_WEB" -eq 0 ]; then
    echo "  Which mode would you like?"
    echo ""
    echo "    [1]  Terminal CLI   (recommended)"
    echo "    [2]  Web UI         (browser at localhost:8000)"
    echo "    [3]  Both"
    echo ""
    read -r -p "  Your choice [1]: " CHOICE
    CHOICE="${CHOICE:-1}"
    case "$CHOICE" in
        2) LAUNCH_WEB=1 ;;
        3) LAUNCH_CLI=1; LAUNCH_WEB=1 ;;
        *) LAUNCH_CLI=1 ;;
    esac
    echo ""
fi

# ── Venv ──────────────────────────────────────────────────────────────────
if [ ! -f ".venv/bin/activate" ]; then
    echo "  [1/3] Creating virtual environment..."
    "$PYTHON" -m venv .venv
fi

source .venv/bin/activate

# ── Dependencies ──────────────────────────────────────────────────────────
NEEDS_INSTALL=0
if ! pip show rich &>/dev/null; then
    NEEDS_INSTALL=1
fi
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
        echo -e "  ${RD}[X]${NC} Installation failed. See error above."
        echo ""
        echo "       Common fixes:"
        echo "       - Check your internet connection"
        echo "       - sudo apt install python3-venv  (Debian/Ubuntu)"
        echo "       - Open an issue: https://github.com/luckydcode/luckyd-code/issues"
        read -r -p "  Press Enter to close..."
        exit 1
    fi
    echo -e "  ${GR}[2/3] Done.${NC}"
    touch "$MARKER"
fi

if ! pip show pytest-asyncio &>/dev/null; then
    pip install "pytest-asyncio>=0.21.0" -q
fi

OPT_MARKER=".venv/.last_optional_install"
if [ ! -f "$OPT_MARKER" ]; then
    pip install -e ".[browser,rag,game]" -q 2>/dev/null || true
    touch "$OPT_MARKER"
fi
if pip show playwright &>/dev/null; then
    playwright install chromium --quiet 2>/dev/null || true
fi

# ── .env setup ────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    [ -f ".env.example" ] && cp .env.example .env || echo "DEEPSEEK_API_KEY=sk-your-key-here" > .env
    echo ""
    echo "  [3/3] No API key found. Get one free at:"
    echo "        https://platform.deepseek.com/api_keys"
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
        echo -e "  ${YL}[!]${NC} Key not saved — edit .env manually."
    fi
    echo ""
fi

KEY_OK=0
while IFS='=' read -r K V; do
    [[ "$K" == "DEEPSEEK_API_KEY" && -n "$V" && "$V" != *"your-key"* ]] && KEY_OK=1
done < .env 2>/dev/null || true

if [ "$KEY_OK" -eq 0 ]; then
    echo -e "  ${YL}[!]${NC} No API key detected in .env"
    echo "      Edit .env and set: DEEPSEEK_API_KEY=sk-xxxxxxxxxx"
    echo "      Get a key at: https://platform.deepseek.com/api_keys"
    read -r -p "  Press Enter to continue anyway..."
fi

# ── Desktop shortcut (created once) ───────────────────────────────────────
DESKTOP_FILE="$HOME/.local/share/applications/luckyd-code.desktop"
if [ ! -f "$DESKTOP_FILE" ]; then
    mkdir -p "$HOME/.local/share/applications"
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
    DESKTOP_LINK="$HOME/Desktop/LuckyD Code.desktop"
    if [ -d "$HOME/Desktop" ] && [ ! -f "$DESKTOP_LINK" ]; then
        cp "$DESKTOP_FILE" "$DESKTOP_LINK" 2>/dev/null || true
    fi
    echo -e "  ${GR}Desktop shortcut added.${NC}"
fi

# ── Success card (first install only) ─────────────────────────────────────
if [ "$NEEDS_INSTALL" -eq 1 ]; then
    echo ""
    echo "  ╭──────────────────────────────────────────────╮"
    echo "  │  ✅  LuckyD Code v1.3.4 installed!           │"
    echo "  │                                               │"
    echo "  │  Run this script to launch                   │"
    echo "  │  Pass --web for browser mode next time       │"
    echo "  │  Pass --both for Web UI + CLI together       │"
    echo "  │                                               │"
    echo "  │  Tip: type /help inside the CLI              │"
    echo "  ╰──────────────────────────────────────────────╯"
    echo ""
    sleep 3
fi

# ── Launch ─────────────────────────────────────────────────────────────────
clear

# Helper: launch web UI (port check, readiness poll, browser open)
launch_web() {
    local PORT="${1:-8000}"
    local URL="http://localhost:$PORT"

    echo "  Starting Web UI at $URL"
    echo "  Press Ctrl+C to stop."
    echo ""

    python main.py --web --port "$PORT" &
    SERVER_PID=$!

    SERVER_READY=0
    for i in $(seq 1 30); do
        sleep 0.5
        if kill -0 "$SERVER_PID" 2>/dev/null; then
            if curl -s -o /dev/null -w "%{http_code}" "$URL" 2>/dev/null | grep -q "200\|302"; then
                SERVER_READY=1
                break
            fi
        else
            echo ""
            echo -e "  ${RD}[X]${NC} Server failed to start. Check the output above."
            return 1
        fi
    done

    if [ "$SERVER_READY" -eq 1 ]; then
        echo -e "  ${GR}Server ready. Opening browser...${NC}"
    else
        echo -e "  ${YL}[!]${NC} Opening browser (server may still be starting)."
    fi

    if command -v xdg-open &>/dev/null; then
        xdg-open "$URL/?v=$RANDOM" 2>/dev/null || true
    elif command -v open &>/dev/null; then
        open "$URL/?v=$RANDOM" 2>/dev/null || true
    fi

    echo ""
    echo "  Server running. Press Ctrl+C to stop."

    cleanup() {
        echo ""; echo "  Stopping server..."
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
        echo "  Web UI stopped."
    }
    trap cleanup EXIT INT TERM
    wait "$SERVER_PID" 2>/dev/null || true
}

if [ "$LAUNCH_CLI" -eq 1 ] && [ "$LAUNCH_WEB" -eq 1 ]; then
    # Both: web in background, CLI in foreground
    python main.py --web &
    WEB_PID=$!
    sleep 2
    if command -v xdg-open &>/dev/null; then
        xdg-open "http://localhost:8000/?v=$RANDOM" 2>/dev/null || true
    fi
    echo "  Web UI started. Running CLI..."
    echo ""
    python main.py || true
    echo ""; echo "  Stopping Web UI..."
    kill "$WEB_PID" 2>/dev/null || true
    wait "$WEB_PID" 2>/dev/null || true
elif [ "$LAUNCH_WEB" -eq 1 ]; then
    launch_web 8000
else
    exec python main.py
fi
