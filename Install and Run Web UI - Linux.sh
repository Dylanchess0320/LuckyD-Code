#!/usr/bin/env bash
# LuckyD Code Web UI — one-click launcher for Linux
# Opens the browser automatically after the server starts.

set -euo pipefail
cd "$(dirname "$0")"

# Colors
CY='\033[0;36m'; GR='\033[0;32m'; YL='\033[0;33m'; RD='\033[0;31m'; NC='\033[0m'

clear
echo ""
echo -e "${CY}  LuckyD Code - Web UI${NC}"
echo "  ─────────────────────────────────────────────"
echo ""

# Python check
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
    echo "          Install from https://python.org"
    exit 1
fi

# Venv
if [ ! -f ".venv/bin/activate" ]; then
    echo "  [INFO] Running first-time setup..."
    exec bash "$(dirname "$0")/Install and Run - Linux.sh" --web
    exit
fi

source .venv/bin/activate

# .env
if [ ! -f ".env" ]; then
    echo -e "  ${RD}[ERROR]${NC} No .env file found. Run the installer first to set up your API key."
    read -r -p "  Press Enter to close..."
    exit 1
fi

echo "  Starting Web UI at http://localhost:8000"
echo "  Press Ctrl+C to stop."
echo ""

# Start the server in the background
python main.py --web &
SERVER_PID=$!

# Wait for the server to be ready
sleep 3

# Open the browser
if command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:8000/?v=$RANDOM" 2>/dev/null || true
elif command -v open &>/dev/null; then
    open "http://localhost:8000/?v=$RANDOM" 2>/dev/null || true
fi

echo ""
echo "  Web UI stopped."

# Wait for server to finish
wait $SERVER_PID 2>/dev/null || true
