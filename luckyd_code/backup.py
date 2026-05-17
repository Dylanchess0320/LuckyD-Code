"""Backup system — git-based snapshots before destructive operations.

Creates a timestamped git commit (or stash if git commits aren't desired)
so that /self-improve and /debug can always be fully reverted.

Usage from CLI:
    /backup              — snapshot now with auto message
    /backup <message>    — snapshot with custom message
    /backup list         — show recent backup snapshots
    /backup restore      — restore the most recent backup snapshot
    /backup restore <n>  — restore backup snapshot N (from /backup list)
"""

import subprocess
from datetime import datetime
from pathlib import Path


# Tag prefix used to identify backup commits so we can list/restore them
BACKUP_TAG_PREFIX = "luckyd-backup/"


def _git(*args: str, cwd: str | None = None) -> tuple[int, str, str]:
    """Run a git command. Returns (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd or str(Path.cwd()),
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return 1, "", "git not found in PATH"
    except Exception as e:
        return 1, "", str(e)


def _is_git_repo(cwd: str | None = None) -> bool:
    code, _, _ = _git("rev-parse", "--is-inside-work-tree", cwd=cwd)
    return code == 0


def _has_changes(cwd: str | None = None) -> bool:
    """Returns True if there are any tracked or untracked changes."""
    _, out, _ = _git("status", "--porcelain", cwd=cwd)
    return bool(out.strip())


def _current_branch(cwd: str | None = None) -> str:
    _, out, _ = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    return out or "unknown"


def _short_hash(cwd: str | None = None) -> str:
    _, out, _ = _git("rev-parse", "--short", "HEAD", cwd=cwd)
    return out or "unknown"


def create_backup(message: str = "", cwd: str | None = None) -> dict:
    """Create a git backup snapshot of the current working tree.

    Strategy:
      1. `git add -A`  — stage everything (new, modified, deleted)
      2. `git commit`  — commit with a timestamped message
      3. `git tag`     — tag it with dsc-backup/<timestamp> for easy lookup

    If there is nothing to commit, returns success with a note.

    Returns a dict with keys: ok, message, tag, hash, error
    """
    result = {"ok": False, "message": "", "tag": "", "hash": "", "error": ""}

    if not _is_git_repo(cwd):
        result["error"] = (
            "No git repository found. Run `git init` in your project root to enable backups."
        )
        return result

    if not _has_changes(cwd):
        # Nothing dirty — point at the current HEAD as the backup
        h = _short_hash(cwd)
        result["ok"] = True
        result["hash"] = h
        result["message"] = f"Nothing to commit — working tree is clean (HEAD is {h})"
        return result

    # Stage everything
    code, _, err = _git("add", "-A", cwd=cwd)
    if code != 0:
        result["error"] = f"git add failed: {err}"
        return result

    # Build commit message
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    label = message.strip() or "pre-operation snapshot"
    commit_msg = f"[luckyd-backup] {label} ({ts})"

    code, _, err = _git("commit", "-m", commit_msg, cwd=cwd)
    if code != 0:
        result["error"] = f"git commit failed: {err}"
        return result

    # Tag it so we can find it later
    tag_name = BACKUP_TAG_PREFIX + datetime.now().strftime("%Y%m%d_%H%M%S")
    _git("tag", tag_name, cwd=cwd)  # best-effort, don't fail if tagging fails

    h = _short_hash(cwd)
    result["ok"] = True
    result["hash"] = h
    result["tag"] = tag_name
    result["message"] = f"Backup created: {h}  tag: {tag_name}"
    return result


def list_backups(limit: int = 10, cwd: str | None = None) -> list[dict]:
    """Return a list of recent backup commits (newest first).

    Each entry: {n, hash, tag, date, subject}
    """
    # List tags matching our prefix, sorted by creation date descending
    _, tag_out, _ = _git(
        "tag", "--list", f"{BACKUP_TAG_PREFIX}*",
        "--sort=-creatordate",
        "--format=%(refname:short)|%(objectname:short)|%(creatordate:short)",
        cwd=cwd,
    )

    entries = []
    for i, line in enumerate(tag_out.splitlines()[:limit]):
        parts = line.split("|")
        if len(parts) >= 3:
            entries.append({
                "n": i + 1,
                "tag": parts[0],
                "hash": parts[1],
                "date": parts[2],
                "subject": parts[0].replace(BACKUP_TAG_PREFIX, ""),
            })
        elif len(parts) == 2:
            entries.append({
                "n": i + 1,
                "tag": parts[0],
                "hash": parts[1],
                "date": "",
                "subject": parts[0].replace(BACKUP_TAG_PREFIX, ""),
            })

    # Fallback: search commit log for [dsc-backup] messages
    if not entries:
        _, log_out, _ = _git(
            "log", f"--max-count={limit}",
            "--pretty=format:%h|%ad|%s",
            "--date=short",
            "--grep=[luckyd-backup]",  # new name
            cwd=cwd,
        )
        # Also search for pre-rename commits (historical)
        if not log_out:
            _, log_out, _ = _git(
                "log", f"--max-count={limit}",
                "--pretty=format:%h|%ad|%s",
                "--date=short",
                "--grep=[dsc-backup]",
                cwd=cwd,
            )
        for i, line in enumerate(log_out.splitlines()):
            parts = line.split("|", 2)
            if len(parts) == 3:
                entries.append({
                    "n": i + 1,
                    "tag": "",
                    "hash": parts[0],
                    "date": parts[1],
                    "subject": parts[2],
                })
    return entries


def restore_backup(ref: str, cwd: str | None = None) -> dict:
    """Restore working tree to a backup snapshot.

    Uses `git checkout <ref> -- .` so it only touches the working tree
    (does NOT move HEAD), leaving you on the same branch. Any currently
    staged/unstaged changes are overwritten.

    Args:
        ref: A tag name, commit hash, or index number (as string) from list_backups()

    Returns a dict with keys: ok, message, error
    """
    result = {"ok": False, "message": "", "error": ""}

    if not _is_git_repo(cwd):
        result["error"] = "No git repository found."
        return result

    # Resolve numeric index to a real ref
    if ref.isdigit():
        backups = list_backups(cwd=cwd)
        idx = int(ref)
        match = next((b for b in backups if b["n"] == idx), None)
        if not match:
            result["error"] = f"No backup #{idx} found. Run /backup list to see options."
            return result
        ref = match["tag"] or match["hash"]

    # Stash any current dirty state first so we don't lose it
    dirty = _has_changes(cwd)
    stash_msg = ""
    if dirty:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        code, _, _ = _git("stash", "push", "-m", f"pre-restore-{ts}", cwd=cwd)
        if code == 0:
            stash_msg = " (current changes stashed — run `git stash pop` to recover them)"

    # Checkout the files from the backup ref into the working tree
    code, _, err = _git("checkout", ref, "--", ".", cwd=cwd)
    if code != 0:
        # Try to recover stash
        if dirty:
            _git("stash", "pop", cwd=cwd)
        result["error"] = f"git checkout failed: {err}"
        return result

    result["ok"] = True
    result["message"] = f"Restored to {ref}{stash_msg}"
    return result


def format_backup_list(backups: list[dict]) -> str:
    """Format backup list for display."""
    if not backups:
        return "No backups found. Run /backup to create one."
    lines = ["[bold]Recent backups:[/bold]\n"]
    for b in backups:
        date_str = f"  {b['date']}" if b["date"] else ""
        tag_str = f"  [{b['tag']}]" if b["tag"] else ""
        lines.append(f"  [cyan]#{b['n']}[/cyan]  {b['hash']}{date_str}{tag_str}")
        if b["subject"] and not b["subject"].startswith(BACKUP_TAG_PREFIX):
            lines.append(f"       [dim]{b['subject'][:80]}[/dim]")
    lines.append("\n[dim]Use /backup restore <#> to restore any of these[/dim]")
    return "\n".join(lines)
