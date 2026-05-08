#!/usr/bin/env python3
"""
LuckyD Code — AI coding assistant in your terminal.

Usage:
    python main.py                          # Start CLI
    python main.py --web                    # Launch web UI
    python main.py --help                   # Show all options
    python main.py --version                # Show version

After pip install:
    luckyd-code                             # Start CLI
    luckyd-code --web                       # Launch web UI
"""

import sys
import os

# Make the project importable when running directly from source
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from luckyd_code import __version__
from luckyd_code.cli_entry import main

if __name__ == "__main__":
    if "--version" in sys.argv:
        print(f"LuckyD Code v{__version__}")
        sys.exit(0)
    sys.exit(main())
