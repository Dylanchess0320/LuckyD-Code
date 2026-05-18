"""Shared I/O utilities for the CLI REPL."""

import logging
import os
import sys
import time as _time
from typing import Any

from rich.console import Console

from . import settings as cfg

console = Console()
_logger = logging.getLogger("luckyd_code.cli_utils")

# Sensible default terminal size (columns × rows)
DEFAULT_COLS = 200
DEFAULT_ROWS = 60


def resize_terminal(cols: int = DEFAULT_COLS, rows: int = DEFAULT_ROWS) -> None:
    """Attempt to resize the terminal window to a comfortable size.

    Respects user settings: set ``auto_resize_terminal`` to ``false``
    (or ``0`` / ``no``) to skip resizing entirely.  Use
    ``terminal_columns`` and ``terminal_rows`` to override the defaults.

    Uses platform-specific mechanisms:
      - Windows: ``mode con:`` command
      - Unix: xterm escape sequence (works on Terminal.app, iTerm2,
        gnome-terminal, Windows Terminal, and most modern terminals)

    Silently ignores failures — some terminals (e.g. tmux, screen, or
    piped output) don't support resize requests.
    """
    try:
        settings = cfg.load_settings()
        auto = settings.get("auto_resize_terminal", True)
        # Normalise bool-ish values stored as strings (JSON /config set)
        if isinstance(auto, str):
            auto = auto.lower() not in ("false", "0", "no", "off")
        if not auto:
            _logger.debug("Terminal auto-resize disabled via settings")
            return

        cols = int(str(settings.get("terminal_columns", cols)))
        rows = int(str(settings.get("terminal_rows", rows)))

        if sys.platform == "win32":
            # Only resize columns on Windows — setting 'lines' causes prompt_toolkit
            # to treat the buffer height as its viewport and renders the >>> prompt
            # at the bottom of that buffer (e.g. row 59 of 60), creating a huge
            # blank gap between the header and the input box.
            import time
            os.system(f"mode con: cols={cols}")
            time.sleep(0.15)  # Let Windows fully process the resize before prompt_toolkit initializes
        else:
            # xterm-compatible resize escape: \\033[8;ROWS;COLSt
            sys.stdout.write(f"\033[8;{rows};{cols}t")
            sys.stdout.flush()
    except Exception:
        _logger.debug("Terminal resize not supported in this environment")


def play_completion_sound(success: bool = True) -> None:
    """Play a notification sound when a response completes.

    Platform support:
      - Windows: system sounds via winsound
      - macOS: afplay (native system sound)
      - Linux: paplay (PulseAudio), aplay (ALSA), or terminal bell fallback
    """
    try:
        settings = cfg.load_settings()
        enabled = settings.get("completion_sound", True)
        if not enabled:
            return

        if sys.platform == "win32":
            import winsound
            if success:
                winsound.PlaySound(
                    "SystemExclamation",
                    winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                )
            else:
                winsound.PlaySound(
                    "SystemHand",
                    winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                )
        elif sys.platform == "darwin":
            # macOS — use afplay for a pleasant system sound
            import subprocess
            try:
                sound = "/System/Library/Sounds/Glass.aiff" if success else "/System/Library/Sounds/Basso.aiff"
                subprocess.Popen(
                    ["afplay", sound],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                # Fallback to terminal bell
                sys.stdout.write("\a" if success else "\a\a\a")
                sys.stdout.flush()
        else:
            # Linux — try PulseAudio, then ALSA, then terminal bell
            import subprocess
            played = False
            if success:
                # Try paplay (PulseAudio)
                try:
                    subprocess.run(
                        ["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=2,
                    )
                    played = True
                except Exception:
                    pass
                # Try aplay (ALSA)
                if not played:
                    try:
                        subprocess.run(
                            ["aplay", "/usr/share/sounds/alsa/Front_Center.wav"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=2,
                        )
                        played = True
                    except Exception:
                        pass
            if not played:
                # Terminal bell fallback
                if success:
                    sys.stdout.write("\a")
                else:
                    for _ in range(3):
                        sys.stdout.write("\a")
                        _time.sleep(0.08)
                sys.stdout.flush()
    except Exception:
        _logger.debug("Completion sound failed, falling back to terminal bell", exc_info=True)
        try:
            if success:
                sys.stdout.write("\a")
            else:
                for _ in range(3):
                    sys.stdout.write("\a")
                    _time.sleep(0.08)
            sys.stdout.flush()
        except Exception:
            _logger.debug("Terminal bell also failed")


def init_prompt_session() -> Any:
    """Create prompt session with custom keybindings."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from .keybindings import apply_keybindings

    try:
        return PromptSession(
            history=FileHistory(".luckyd_history"),
            key_bindings=apply_keybindings(),
            multiline=True,
            complete_while_typing=False,
        )
    except Exception:
        _logger.debug("PromptSession creation failed, trying fallback", exc_info=True)

    try:
        from prompt_toolkit.output.vt100 import Vt100_Output
        from prompt_toolkit.data_structures import Size
        import shutil

        def _get_size() -> Any:
            ts = shutil.get_terminal_size()
            return Size(rows=ts.lines, columns=ts.columns)

        return PromptSession(
            history=FileHistory(".luckyd_history"),
            key_bindings=apply_keybindings(),
            output=Vt100_Output(sys.stdout, get_size=_get_size),
            multiline=True,
            complete_while_typing=False,
        )
    except Exception:
        _logger.warning("Failed to create prompt session", exc_info=True)
        return None


def read_input(session: Any) -> str | None:
    """Read a line of input from the user."""
    if session:
        try:
            return str(session.prompt(">>> "))
        except KeyboardInterrupt:
            return None
        except EOFError:
            return "__EOF__"

    try:
        lines: list[str] = []
        while True:
            line = input(">>> " if not lines else "... ")
            if line.rstrip().endswith("\\"):
                lines.append(line.rstrip()[:-1])
            else:
                lines.append(line)
                break
        return "\n".join(lines)
    except EOFError:
        if lines:
            return "\n".join(lines)
        return "__EOF__"
    except KeyboardInterrupt:
        return None
