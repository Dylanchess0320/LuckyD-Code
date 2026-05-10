#!/usr/bin/env python3
"""Resize terminal to a larger size.

Usage:
    python resize_terminal.py [columns] [lines]

Default: 200 columns x 60 lines
"""
import sys
import os
import platform
import shutil
import subprocess

COLS = int(sys.argv[1]) if len(sys.argv) > 1 else 200
LINES = int(sys.argv[2]) if len(sys.argv) > 2 else 60

system = platform.system()

print(f"Resizing terminal to {COLS}x{LINES}...")

if system == "Windows":
    os.system(f"mode con cols={COLS} lines={LINES}")
elif system == "Darwin" or system == "Linux":
    # ANSI escape sequence (works in most terminals when sourced)
    print(f"\033[8;{LINES};{COLS}t", end="", flush=True)
    # Try the 'resize' command (no shell injection — inputs are int)
    subprocess.run(
        ["resize", "-s", str(LINES), str(COLS)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

# Show new size
terminal_size = shutil.get_terminal_size()
print(f"Terminal size: {terminal_size.columns} columns x {terminal_size.lines} lines")
print(f"Requested: {COLS}x{LINES}")
