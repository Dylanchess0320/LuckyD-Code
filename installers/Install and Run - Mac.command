#!/usr/bin/env bash
# LuckyD Code — double-click launcher for Mac (Finder)
# This file opens in Terminal automatically on Mac when double-clicked.
# For Linux, use: Install and Run - Linux.sh

set -euo pipefail

# ── Self-healing: fix exec permissions lost after git clone ──────────────
# git does not track the executable bit reliably on macOS, so .command files
# may lose +x after cloning. Auto-fix this so double-clicking always works.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for f in "$PROJECT_DIR"/*.command; do
    [ -f "$f" ] && [ ! -x "$f" ] && chmod +x "$f" 2>/dev/null || true
done
cd "$PROJECT_DIR"

# Colors
CY='\033[0;36m'; GR='\033[0;32m'; YL='\033[0;33m'; RD='\033[0;31m'; NC='\033[0m'

clear
echo ""
echo -e "${CY}  LuckyD Code v1.3.1${NC}"
echo "  AI coding assistant powered by DeepSeek API"
echo "  ─────────────────────────────────────────────"
echo ""

# ── Python check (with Homebrew paths for Apple Silicon + Intel) ─────────
PYTHON=""
# Add common Homebrew Python paths to PATH temporarily
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
    echo ""
    # Detect architecture for the right Homebrew path
    ARCH="$(uname -m)"
    if [ "$ARCH" = "arm64" ]; then
        echo "  Apple Silicon (M1/M2/M3/M4) detected."
        echo "  Install via Homebrew:  brew install python@3.12"
        echo "  (Installs to /opt/homebrew/bin/python3)"
    else
        echo "  Intel Mac detected."
        echo "  Install via Homebrew:  brew install python@3.12"
        echo "  (Installs to /usr/local/bin/python3)"
    fi
    echo ""
    echo "  If you don't have Homebrew, install it first:"
    echo "    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo ""
    echo "  Or download Python directly: https://www.python.org/downloads/"
    echo ""
    read -r -p "  Press Enter to close..."
    exit 1
fi

echo -e "  ${GR}Using: $PYTHON ($("$PYTHON" --version 2>&1))${NC}"

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
# Also reinstall if pyproject.toml is newer than .venv marker
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
        echo -e "  ${RD}[ERROR]${NC} Installation failed. See error above."
        echo "         Common fixes:"
        echo "         - Check your internet connection"
        echo "         - xcode-select --install  (for compiler tools)"
        read -r -p "  Press Enter to close..."
        exit 1
    fi
    touch "$MARKER"
    echo -e "  ${GR}[2/3] Done.${NC}"
fi

# Dev dependencies
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
        echo -e "  ${YL}[WARN]${NC} Key not saved — edit .env manually."
    fi
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

# ── Desktop shortcut — uses absolute path, works from any location ─────────
DESKTOP_CMD="$HOME/Desktop/LuckyD Code.command"
if [ ! -f "$DESKTOP_CMD" ]; then
    cat > "$DESKTOP_CMD" << SHORTCUT_EOF
#!/usr/bin/env bash
# LuckyD Code — Desktop shortcut
# Auto-generated by Install and Run - Mac.command
# Points to: $PROJECT_DIR

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

# ── Launch ─────────────────────────────────────────────────────────────────
# Forward all CLI args (main.py handles --web, --port, --model, etc.)
# Terminal resize is handled by Python's cli_utils.resize_terminal()
clear
exec python main.py "$@"
