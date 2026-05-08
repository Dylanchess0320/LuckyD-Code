"""Auto-update module."""

import subprocess

def get_version() -> str:
    from luckyd_code import __version__
    return __version__


def check_for_updates() -> str:
    """Check if updates are available via git fetch."""
    try:
        subprocess.run(
            ["git", "fetch", "--quiet"],
            capture_output=True, text=True, timeout=30,
        )
        r = subprocess.run(
            ["git", "rev-list", "--count", "HEAD..origin/HEAD"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            count = int(r.stdout.strip())
            if count > 0:
                return f"{count} commit(s) behind. Run `/update` to pull."
        r = subprocess.run(
            ["git", "remote", "-v"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            return "Up to date."
        return "Not a git repository or no remote configured"
    except Exception as e:
        return f"Cannot check for updates: {e}"


def do_update() -> str:
    """Pull latest changes from git."""
    try:
        # Only stash if there are actual uncommitted changes, so we don't
        # pop a stash the user created manually.
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=15,
        )
        has_changes = bool(status.returncode == 0 and status.stdout.strip())

        if has_changes:
            subprocess.run(["git", "stash"], capture_output=True, text=True, timeout=30)

        r = subprocess.run(
            ["git", "pull"],
            capture_output=True, text=True, timeout=60,
        )

        if has_changes:
            subprocess.run(["git", "stash", "pop"], capture_output=True, text=True, timeout=30)

        return r.stdout.strip() or r.stderr.strip() or "Updated successfully"
    except Exception as e:
        return f"Update failed: {e}"
