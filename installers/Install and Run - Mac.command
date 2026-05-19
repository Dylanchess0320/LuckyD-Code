#!/usr/bin/env bash
# LuckyD Code — double-click launcher for Mac (Finder)
# This file opens in Terminal automatically on Mac when double-clicked.
# For Linux, use: Install and Run - Linux.sh

set -euo pipefail

# ── Self-healing: fix exec permissions lost after git clone ──────────────
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for f in "$PROJECT_DIR"/*.command; do
    [ -f "$f" ] && [ ! -x "$f" ] && chmod +x "$f" 2>/dev/null || true
done
cd "$PROJECT_DIR"

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

# Python check (with Homebrew paths for Apple Silicon + Intel)
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
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
    ARCH="$(uname -m)"
    if [ "$ARCH" = "arm64" ]; then
        echo "      Apple Silicon detected — install via Homebrew:"
        echo "        brew install python@3.12"
    else
        echo "      Intel Mac detected — install via Homebrew:"
        echo "        brew install python@3.12"
    fi
    echo ""
    echo "      No Homebrew? Install it first:"
    echo "        /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo ""
    echo "      Or download directly: https://www.python.org/downloads/"
    echo ""
    read -r -p "  Press Enter to close..."
    exit 1
fi
echo -e "  ${GR}[OK]${NC} $("$PYTHON" --version 2>&1)"

# pip
if "$PYTHON" -m pip --version &>/dev/null; then
    echo -e "  ${GR}[OK]${NC} pip"
else
    echo -e "  ${YL}[!!]${NC} pip missing - will attempt to fix"
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

# ── Virtual environment ───────────────────────────────────────────────────
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
    echo "  [2/3] Installing dependencies (first run or update, ~1 min)..."
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
        echo "       - xcode-select --install  (for compiler tools)"
        echo "       - Open an issue: https://github.com/luckydcode/luckyd-code/issues"
        read -r -p "  Press Enter to close..."
        exit 1
    fi
    touch "$MARKER"
    echo -e "  ${GR}[2/3] Done.${NC}"
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

# ── API key setup ─────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    [ -f ".env.example" ] && cp .env.example .env || echo "DEEPSEEK_API_KEY=sk-your-key-here" > .env
    echo ""
    echo "  [3/3] No API key found."
    echo "        Get a free key at: https://platform.deepseek.com/api_keys"
    open "https://platform.deepseek.com/api_keys" 2>/dev/null || true
    echo ""
    read -r -p "  Paste your DeepSeek API key (starts with sk-): " API_KEY
    API_KEY="${API_KEY// /}"
    if [[ "$API_KEY" == sk-* ]]; then
        sed -i.bak "s|DEEPSEEK_API_KEY=.*|DEEPSEEK_API_KEY=$API_KEY|" .env && rm -f .env.bak
        echo -e "  ${GR}API key saved.${NC}"
    else
        echo -e "  ${YL}[!]${NC} Key not saved — edit .env manually."
    fi
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
DESKTOP_CMD="$HOME/Desktop/LuckyD Code.command"
if [ ! -f "$DESKTOP_CMD" ]; then
    cat > "$DESKTOP_CMD" << SHORTCUT_EOF
#!/usr/bin/env bash
set -euo pipefail
MAIN_LAUNCHER="$PROJECT_DIR/Install and Run - Mac.command"
if [ ! -f "\$MAIN_LAUNCHER" ]; then
    echo "Error: LuckyD Code not found at: $PROJECT_DIR"
    echo "If you moved the project folder, re-run the installer from the new location."
    read -r -p "Press Enter to close..."
    exit 1
fi
cd "$PROJECT_DIR"
exec bash "\$MAIN_LAUNCHER" "\$@"
SHORTCUT_EOF
    chmod +x "$DESKTOP_CMD"
    echo -e "  ${GR}Desktop shortcut created.${NC}"
fi

# ── Success card (first install only) ─────────────────────────────────────
if [ "$NEEDS_INSTALL" -eq 1 ]; then
    echo ""
    echo "  ╭──────────────────────────────────────────────╮"
    echo "  │  ✅  LuckyD Code v1.3.4 installed!           │"
    echo "  │                                               │"
    echo "  │  Double-click this script to launch          │"
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

# Helper: launch web UI (handles port conflict, readiness poll, browser open)
launch_web() {
    local PORT="${1:-8000}"
    local URL="http://localhost:$PORT"

    # Already running?
    if curl -s -o /dev/null -w "%{http_code}" "$URL" 2>/dev/null | grep -q "200\|302"; then
        echo -e "  ${GR}Server already running at $URL${NC}"
        echo "  Opening browser..."
        open "$URL/?v=$RANDOM"
        return 0
    fi

    # Port conflict?
    if lsof -i ":$PORT" -sTCP:LISTEN &>/dev/null; then
        echo -e "  ${YL}[!]${NC} Port $PORT is in use by another process."
        echo "      Close it or start manually: python main.py --web --port 8001"
        return 1
    fi

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
        echo -e "  ${YL}[!]${NC} Server is taking longer than expected — opening browser anyway."
    fi
    open "$URL/?v=$RANDOM"

    echo ""
    echo "  Server running. Press Ctrl+C or close this window to stop."

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
    # Both: web in background, CLI in foreground; stop web when CLI exits
    python main.py --web &
    WEB_PID=$!
    sleep 2
    open "http://localhost:8000/?v=$RANDOM" 2>/dev/null || true
    echo "  Web UI started. Running CLI..."
    echo ""
    python main.py || true
    echo ""; echo "  Stopping Web UI..."
    kill "$WEB_PID" 2>/dev/null || true
    wait "$WEB_PID" 2>/dev/null || true
elif [ "$LAUNCH_WEB" -eq 1 ]; then
    launch_web 8000
else
    # CLI
    exec python main.py
fi

echo ""
read -r -p "  Session ended. Press Enter to close..."
