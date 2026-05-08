import subprocess


def git_status() -> str:
    try:
        r = subprocess.run(["git", "status"], capture_output=True, text=True, timeout=30)
        return r.stdout.strip() or r.stderr.strip()
    except Exception as e:
        return f"Error: {e}"


def git_diff(staged: bool = False) -> str:
    try:
        cmd = ["git", "diff", "--cached"] if staged else ["git", "diff"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = r.stdout.strip()
        if not out:
            return "No changes"
        return out[:5000]
    except Exception as e:
        return f"Error: {e}"


def git_log(count: int = 10) -> str:
    try:
        r = subprocess.run(
            ["git", "log", f"--max-count={count}", "--oneline"],
            capture_output=True, text=True, timeout=30,
        )
        return r.stdout.strip() or r.stderr.strip()
    except Exception as e:
        return f"Error: {e}"


def git_commit(message: str) -> str:
    try:
        r = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, timeout=30,
        )
        return r.stdout.strip() or r.stderr.strip()
    except Exception as e:
        return f"Error: {e}"


def git_add(files: list[str] | None = None) -> str:
    try:
        cmd = ["git", "add"] + (files if files else ["-A"])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.stdout.strip() or r.stderr.strip() or "Staged"
    except Exception as e:
        return f"Error: {e}"


def git_branch() -> str:
    try:
        r = subprocess.run(
            ["git", "branch", "-a"],
            capture_output=True, text=True, timeout=30,
        )
        return r.stdout.strip() or r.stderr.strip()
    except Exception as e:
        return f"Error: {e}"


def git_create_pr(title: str, body: str = "", draft: bool = True) -> str:
    try:
        cmd = ["gh", "pr", "create", "--title", title, "--body", body]
        if draft:
            cmd.append("--draft")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return r.stdout.strip() or r.stderr.strip()
    except Exception as e:
        return f"Error: {e}"


def git_push(branch: str | None = None) -> str:
    try:
        cmd = ["git", "push", "-u", "origin"]
        if branch:
            cmd.append(branch)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return r.stdout.strip() or r.stderr.strip()
    except Exception as e:
        return f"Error: {e}"
