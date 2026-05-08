#!/usr/bin/env bash
# LuckyD Code Web UI — double-click launcher for Mac (Finder)
# Opens in Terminal automatically when double-clicked, then opens the browser.
# Automatically reconnects to an already-running server.

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
echo -e "${CY}  LuckyD Code — Web UI${NC}"
echo "  ─────────────────────────────────────────────"
echo ""

# ── Python check ──────────────────────────────────────────────────────────
PYTHON=""
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
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
    echo "          Install via Homebrew:  brew install python@3.12"
    echo "          Or:                    https://www.python.org/downloads/"
    read -r -p "  Press Enter to close..."
    exit 1
fi

# ── Virtual environment — delegate to main installer if missing ────────────
if [ ! -f ".venv/bin/activate" ]; then
    echo "  [INFO] First run — setting up environment..."
    exec bash "$PROJECT_DIR/Install and Run - Mac.command" --web
    exit
fi

source .venv/bin/activate

# ── .env check ────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo -e "  ${RD}[ERROR]${NC} No .env file found. Run the installer first to set up your API key."
    read -r -p "  Press Enter to close..."
    exit 1
fi

# ── Port (default 8000, overridable) ──────────────────────────────────────
PORT="${1:-8000}"
# Strip non-digits in case user passes "--port 8000"
PORT="$(echo "$PORT" | grep -o '[0-9]*' | head -1)"
: "${PORT:=8000}"

URL="http://localhost:$PORT"

# ── Check if server is already running ────────────────────────────────────
if curl -s -o /dev/null -w "%{http_code}" "$URL" 2>/dev/null | grep -q "200\|302"; then
    echo -e "  ${GR}Server already running at $URL${NC}"
    echo "  Opening browser..."
    open "$URL/?v=$RANDOM"
    echo ""
    read -r -p "  Press Enter to close..."
    exit 0
fi

# ── Check for port conflict ───────────────────────────────────────────────
if lsof -i ":$PORT" -sTCP:LISTEN &>/dev/null; then
    echo -e "  ${YL}[WARN]${NC} Port $PORT is already in use by another process."
    echo "         Close the other process or use a different port:"
    echo "         python main.py --web --port 8001"
    read -r -p "  Press Enter to close..."
    exit 1
fi

echo "  Starting Web UI at $URL"
echo "  Press Ctrl+C to stop."
echo ""

# ── Start server in background ────────────────────────────────────────────
python main.py --web --port "$PORT" &
SERVER_PID=$!

# ── Poll for server readiness (up to 15 seconds) ─────────────────────────
SERVER_READY=0
for i in $(seq 1 30); do
    sleep 0.5
    if kill -0 "$SERVER_PID" 2>/dev/null; then
        if curl -s -o /dev/null -w "%{http_code}" "$URL" 2>/dev/null | grep -q "200\|302"; then
            SERVER_READY=1
            break
        fi
    else
        # Server died — show the error
        echo ""
        echo -e "  ${RD}[ERROR]${NC} Server failed to start. Check the output above."
        read -r -p "  Press Enter to close..."
        exit 1
    fi
done

if [ "$SERVER_READY" -eq 1 ]; then
    echo -e "  ${GR}Server ready. Opening browser...${NC}"
    open "$URL/?v=$RANDOM"
else
    echo -e "  ${YL}[WARN]${NC} Server is taking longer than expected..."
    echo "         Opening browser anyway (may take a moment to connect)."
    open "$URL/?v=$RANDOM"
fi

echo ""
echo "  Server running. Press Ctrl+C or close this window to stop."

# ── Wait for server process; clean up on exit ────────────────────────────
cleanup() {
    echo ""
    echo "  Stopping server..."
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    echo "  Web UI stopped."
}
trap cleanup EXIT INT TERM
wait "$SERVER_PID" 2>/dev/null || true
