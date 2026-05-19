#!/usr/bin/env bash
# Resize terminal to a larger size (columns x lines)
# Usage: source resize_terminal.sh [columns] [lines]
# NOTE: Must be SOURCED (not executed) for the escape sequence to work

COLS="${1:-200}"
LINES="${2:-60}"

echo "Resizing terminal to ${COLS}x${LINES}..."

# ANSI escape sequence to resize terminal
printf '\e[8;%d;%dt' "$LINES" "$COLS"

# Also try the 'resize' command if available
if command -v resize &>/dev/null; then
    resize -s "$LINES" "$COLS" 2>/dev/null || true
fi

# Show current terminal size
if command -v stty &>/dev/null; then
    echo "Current terminal size: $(stty size 2>/dev/null || echo 'unknown')"
fi
