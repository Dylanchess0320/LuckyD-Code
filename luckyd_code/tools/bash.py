"""Bash tool with safety guards and optional Docker sandbox.

Auto-detects the best available shell on Windows (Git Bash → WSL → cmd.exe)
so the AI can use standard Unix commands like ls, grep, find, and curl.

Cross-platform subprocess handling:
  - Uses Popen with process groups for reliable timeout enforcement
  - Proper Windows process isolation via creationflags
  - Rewrites interactive commands into non-interactive equivalents
  - Auto-detects .venv/pip/pytest and routes them through cmd.exe on Windows
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from .registry import Tool
from .shell_detect import resolve_shell, ShellInfo
from ..settings import load_settings
from ..sandbox import get_sandbox

# Default working directory for commands — evaluated at runtime so --dir flag works
def _get_cwd() -> Path:
    return Path.cwd()

# Cached shell detection result (reset on /config set shell)
_SHELL_CACHE: ShellInfo | None = None


def _get_shell() -> ShellInfo:
    """Get cached shell info, detecting on first call."""
    global _SHELL_CACHE
    if _SHELL_CACHE is None:
        settings = load_settings()
        shell_setting = str(settings.get("shell", "auto"))
        _SHELL_CACHE = resolve_shell(shell_setting)
    return _SHELL_CACHE


def reset_shell_cache() -> None:
    """Force re-detection on next call. Used by /config set shell."""
    global _SHELL_CACHE
    _SHELL_CACHE = None

# Commands that are blocked for safety
BLOCKED_PATTERNS = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf .",
    "> /dev/sda",
    "mkfs.",
    "dd if=",
    ":(){ :|:& };:",  # fork bomb
    "chmod 777",
    "sudo ",
    "su ",
]

# Interactive commands that will hang on any platform
INTERACTIVE_COMMANDS = [
    "vim", "vi", "nano", "emacs", "less", "more", "top", "htop",
    "ssh", "telnet", "ftp", "python -i", "irb", "node -i",
    # Additional commands that typically require a TTY
    "watch", "tail -f", "journalctl -f", "docker attach",
    "mysql", "psql", "sqlite3", "redis-cli", "mongo",
]

# Windows cmd.exe only — these are normal, non-interactive commands on Mac/Linux
_WINDOWS_INTERACTIVE_COMMANDS = [
    "date", "time", "pause", "choice",
    # stdin readers that block forever without a pipe on Windows
    "clip",
]


def _fix_windows_cmd(command: str) -> str:
    """Rewrite bare Windows commands that are interactive into their
    non-interactive equivalents so they never hang.

    Examples
    --------
    ``date``       → ``date /T``   (print date, don't prompt to change it)
    ``time``       → ``time /T``   (print time, don't prompt to change it)
    ``ping host``  → ``ping -n 4 host``  (bounded ping instead of infinite)
    ``choice``     → ``choice /N /T 0 /D Y``  (non-interactive choice, select default)
    ``pause``      → ``echo.``  (skip pause)
    """
    import re
    stripped = command.strip()

    # 'date' alone or 'date ' with no flags → date /T
    if re.fullmatch(r'date', stripped, re.IGNORECASE):
        return 'date /T'
    if re.match(r'date\s+(?!/)(.+)', stripped, re.IGNORECASE):
        return 'date /T'

    # 'time' alone → time /T
    if re.fullmatch(r'time', stripped, re.IGNORECASE):
        return 'time /T'
    if re.match(r'time\s+(?!/)(.+)', stripped, re.IGNORECASE):
        return 'time /T'

    # 'ping host' without -n → add '-n 4' so it terminates
    ping_match = re.match(r'(ping)\s+(?!.*-n\s+\d)(.+)', stripped, re.IGNORECASE)
    if ping_match:
        return f'ping -n 4 {ping_match.group(2)}'

    # 'choice' without /T → add non-interactive defaults
    if re.fullmatch(r'choice', stripped, re.IGNORECASE):
        return 'choice /N /T 0 /D Y'

    # 'pause' → skip
    if re.fullmatch(r'pause', stripped, re.IGNORECASE):
        return 'echo.'

    # 'clip' without input → pipe nothing
    if re.fullmatch(r'clip', stripped, re.IGNORECASE):
        return 'echo.| clip'

    return command


def _fix_unix_ping(command: str) -> str:
    """On Unix shells, bare 'ping host' runs forever — add '-c 4'."""
    import re
    stripped = command.strip()
    ping_match = re.match(r'(ping)\s+(?!.*-c\s+\d)(.+)', stripped, re.IGNORECASE)
    if ping_match:
        return f'ping -c 4 {ping_match.group(2)}'
    return command


def _is_dangerous(command: str) -> str | None:
    """Check if a command is potentially dangerous. Returns warning or None."""
    cmd_lower = command.lower().strip()

    for pattern in BLOCKED_PATTERNS:
        if pattern in cmd_lower:
            return f"Command blocked for safety: matches '{pattern}'"

    # Build the effective interactive list for this platform
    effective_interactive = INTERACTIVE_COMMANDS[:]
    if sys.platform == "win32":
        effective_interactive.extend(_WINDOWS_INTERACTIVE_COMMANDS)

    # Check for interactive commands
    for ic in effective_interactive:
        if cmd_lower.startswith(ic) or f" {ic} " in f" {cmd_lower} ":
            return f"Interactive command '{ic}' is not supported in non-interactive shell — use the DateTime tool for date/time queries"

    # Warn about pip install / npm install (can be slow or modify system)
    if "pip install" in cmd_lower or "npm install" in cmd_lower:
        pass  # These are generally useful, just warn via permission system

    return None


class _CommandTimeout(Exception):
    """Raised when a command exceeds its timeout."""
    def __init__(self, elapsed: float):
        self.elapsed = elapsed
        super().__init__(f"Command timed out after {elapsed:.0f}s")


def _run_with_timeout(  # pragma: no cover
    cmd: list[str] | str,
    *,
    shell: bool = False,
    timeout_sec: float = 120,
    cwd: str | Path | None = None,
) -> tuple[str, str, int]:
    """Execute a subprocess with reliable timeout enforcement.

    Uses Popen with process groups so that on timeout the entire process
    tree is terminated — no orphaned child processes.

    On Windows, uses CREATE_NEW_PROCESS_GROUP for proper isolation.
    On Unix, uses os.setsid to create a new session.

    Returns (stdout, stderr, returncode).
    Raises _CommandTimeout if the process doesn't finish in time.
    """
    cwd = str(cwd) if cwd else None

    # On Windows, some commands (like 'where') can hang when searching
    # network paths. Mitigate by ensuring system32 is prioritized.
    env = os.environ.copy()
    if sys.platform == "win32" and shell:
        # Ensure system32 is first in PATH for cmd.exe reliability
        system32 = r"C:\Windows\System32"
        current_path = env.get("PATH", "")
        if system32 not in current_path.split(os.pathsep)[:1]:
            env["PATH"] = system32 + os.pathsep + current_path

    # Build creation flags for proper process group handling
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "cwd": cwd,
        "env": env,
    }

    if sys.platform == "win32":
        # CREATE_NEW_PROCESS_GROUP prevents Ctrl+C propagation
        # CREATE_NO_WINDOW prevents a console window from popping up
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        kwargs["creationflags"] = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    else:
        # Create a new session so we can kill the full process tree.
        # start_new_session=True makes the child a process group leader;
        # preexec_fn=os.setsid would do the same thing but Python raises
        # ValueError if both are set simultaneously — use only one.
        kwargs["start_new_session"] = True

    t0 = time.time()
    proc = subprocess.Popen(cmd, shell=shell, **kwargs)

    try:
        stdout, stderr = proc.communicate(timeout=timeout_sec)
        return stdout or "", stderr or "", proc.returncode or 0
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0

        # Kill the full process tree
        try:
            if sys.platform == "win32":
                # Terminate process tree on Windows
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    timeout=10,
                )
            else:
                # Kill the process group on Unix
                os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass

        # Also try direct kill
        try:
            proc.kill()
        except Exception:
            pass

        # Small wait for cleanup
        try:
            proc.wait(timeout=2)
        except Exception:
            pass

        raise _CommandTimeout(elapsed)


class BashTool(Tool):
    name = "Bash"
    description = "Execute a shell command and get its output."
    permission_risk = "high"
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
            "description": {
                "type": "string",
                "description": "Clear description of what this command does",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in milliseconds (default 120000, max 600000)",
            },
        },
        "required": ["command"],
    }

    def run(self, command: str, description: str = "", timeout: int = 120000) -> str:  # pragma: no cover
        # Safety check
        warning = _is_dangerous(command)
        if warning:
            return f"Error: {warning}"

        timeout_sec = min(timeout / 1000, 600)
        # Minimum 1 second timeout
        timeout_sec = max(timeout_sec, 1)

        # Check if sandbox mode is enabled
        settings = load_settings()
        use_sandbox = settings.get("sandbox", False)

        if use_sandbox:
            sandbox = get_sandbox()
            if sandbox.available:
                stdout, stderr, rc = sandbox.run(command, timeout=int(timeout_sec))
                output = stdout
                if stderr:
                    output += ("\n" + stderr) if output else stderr
                if rc != 0 and not output:
                    output = f"Command exited with code {rc}"
                return (output.strip()[:10000]
                        or f"(command completed with exit code {rc}, no output)")

        try:
            shell_info = _get_shell()

            # On Windows, prefer cmd.exe for .venv/pip/pytest/python commands
            # because Git Bash struggles with Windows-style paths and venv scripts.
            use_cmd = False
            if shell_info.unix_like and sys.platform == "win32":
                cmd_lower = command.lower().strip()
                win_indicators = (
                    ".venv", "venv\\", "venv/",
                    "pytest", "pip ", "pip3 ",
                    ".bat", ".exe",
                    "python -m", "python3 -m",
                )
                if any(ind in cmd_lower for ind in win_indicators):
                    use_cmd = True

            if use_cmd or (not shell_info.unix_like and sys.platform == "win32"):
                # cmd.exe — rewrite any interactive-but-fixable commands first
                command = _fix_windows_cmd(command)
                stdout, stderr, rc = _run_with_timeout(
                    command,
                    shell=True,
                    timeout_sec=timeout_sec,
                    cwd=_get_cwd(),
                )
            else:
                # Unix shell (Git Bash / WSL) — fix bare ping before running
                command = _fix_unix_ping(command)
                full_args = [shell_info.path] + shell_info.args + ["-c", command]
                stdout, stderr, rc = _run_with_timeout(
                    full_args,
                    shell=False,
                    timeout_sec=timeout_sec,
                    cwd=_get_cwd(),
                )

            output = ""
            if stdout:
                output += stdout
            if stderr:
                if output:
                    output += "\n"
                output += stderr
            if rc != 0 and not output:
                output = f"Command exited with code {rc}"

            # Truncate very long output
            max_output = 10000
            if len(output) > max_output:
                output = output[:max_output] + f"\n... (truncated, {len(output)} total chars)"

            return output.strip() or f"(command completed with exit code {rc}, no output)"

        except _CommandTimeout as e:
            return f"Error: command timed out after {e.elapsed:.0f}s: {command[:200]}"
        except OSError as e:
            return f"Error: system error executing command: {e}"
        except Exception as e:
            return f"Error executing command: {e}"
