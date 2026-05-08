#!/usr/bin/env bash
# Resize the current Terminal window to a comfortable size.
# Double-click this file from Finder on macOS.
# Works with Terminal.app, iTerm2, and most modern terminals.

set -euo pipefail

# ── Self-healing: fix exec permissions after git clone ────────────────────
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for f in "$PROJECT_DIR"/*.command; do
    [ -f "$f" ] && [ ! -x "$f" ] && chmod +x "$f" 2>/dev/null || true
done

COLS="${1:-200}"
LINES="${2:-60}"

echo "Resizing terminal to ${COLS}x${LINES}..."

# ANSI escape sequence (xterm-compatible, works in Terminal.app and iTerm2)
printf '\e[8;%d;%dt' "$LINES" "$COLS"

# Also try the 'resize' command if available (Homebrew: brew install xterm)
if command -v resize &>/dev/null; then
    resize -s "$LINES" "$COLS" 2>/dev/null || true
fi

# Show current size
if command -v stty &>/dev/null; then
    read -r ROWS COLS_NOW < <(stty size 2>/dev/null) || true
    echo "Current terminal size: ${COLS_NOW:-?}x${ROWS:-?}"
fi

echo "Done."
