"""Shell auto-detection for Windows — finds Git Bash, WSL, or falls back to cmd.exe."""

import os
import shutil
import sys
from dataclasses import dataclass


@dataclass
class ShellInfo:
    name: str
    path: str
    args: list[str]
    unix_like: bool
    description: str


def detect_shell() -> ShellInfo:
    """Probe for the best available shell.

    On Mac/Linux: uses $SHELL or falls back to /bin/bash.

    On Windows detection order:
      1. Git Bash (most common for developers on Windows)
      2. WSL (Windows Subsystem for Linux)
      3. cmd.exe (stock Windows — always available)

    Returns the first match found.
    """
    # ── Mac / Linux ──────────────────────────────────────────────────────────
    if sys.platform != "win32":
        shell_path = os.environ.get("SHELL", "/bin/bash")
        # Resolve to an absolute path; fall back to /bin/bash if not found
        resolved = shutil.which(shell_path) or shell_path
        name = os.path.basename(resolved).split("-")[0]  # e.g. "zsh" from "/usr/local/bin/zsh-5.9"
        return ShellInfo(
            name=name,
            path=resolved,
            args=[],
            unix_like=True,
            description=resolved,
        )

    # ── Windows ──────────────────────────────────────────────────────────────
    git_bash = _find_git_bash()
    if git_bash:
        return ShellInfo(
            name="git_bash",
            path=git_bash,
            args=["--norc", "--noprofile"],
            unix_like=True,
            description="Git Bash",
        )

    wsl = _find_wsl()
    if wsl:
        return ShellInfo(
            name="wsl",
            path=wsl,
            args=["--", "bash"],
            unix_like=True,
            description="WSL (Ubuntu)",
        )

    return ShellInfo(
        name="cmd",
        path=os.environ.get("COMSPEC", "cmd.exe"),
        args=[],
        unix_like=False,
        description="cmd.exe",
    )


def _is_windows_store_stub(path: str) -> bool:
    """Return True if path is a Windows Store app stub.

    Store stubs live under %LOCALAPPDATA%\\Microsoft\\WindowsApps\\ and are
    thin launchers that require COM / MSI registration to work. Invoking them
    via subprocess raises REGDB_E_CLASSNOTREG on systems where the Store
    infrastructure isn't fully registered. We must skip them.
    """
    normalized = path.replace("/", "\\").lower()
    return "windowsapps" in normalized


def _find_git_bash() -> str | None:
    """Locate Git Bash — use PATH lookup first, then common install paths.

    Skips Windows Store app stubs (AppData\\Local\\Microsoft\\WindowsApps\\bash.exe)
    which raise REGDB_E_CLASSNOTREG when launched via subprocess.
    """
    bash_in_path = shutil.which("bash")
    if bash_in_path and not _is_windows_store_stub(bash_in_path):
        return bash_in_path

    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Git\bin\bash.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _find_wsl() -> str | None:
    """Check if WSL is available."""
    wsl_path = shutil.which("wsl.exe") or shutil.which("wsl")
    if wsl_path:
        return wsl_path
    return None


def resolve_shell(shell_setting: str = "auto") -> ShellInfo:
    """Resolve the shell to use based on a user setting.

    Args:
        shell_setting: One of "auto", "git_bash", "wsl", "cmd".

    Returns:
        The resolved ShellInfo.
    """
    mapping = {
        "git_bash": lambda: _find_git_bash(),
        "wsl": lambda: _find_wsl(),
        "cmd": lambda: os.environ.get("COMSPEC", "cmd.exe"),
    }

    if shell_setting != "auto":
        finder = mapping.get(shell_setting)
        if finder:
            path = finder()
            if path:
                if shell_setting == "git_bash":
                    return ShellInfo("git_bash", path, ["--norc", "--noprofile"], True, "Git Bash")
                elif shell_setting == "wsl":
                    return ShellInfo("wsl", path, ["--", "bash"], True, "WSL (Ubuntu)")
                else:
                    return ShellInfo("cmd", path, [], False, "cmd.exe")
        # Fall through to auto if the override shell wasn't found

    return detect_shell()
