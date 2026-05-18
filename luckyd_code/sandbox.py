"""Docker sandbox for secure command execution."""

import os
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Optional


SANDBOX_IMAGE = "python:3.10-slim"
SANDBOX_MEM_LIMIT = "512m"
SANDBOX_CPU_LIMIT = "1.0"

# Supported language → interpreter mapping
_LANGUAGE_INTERPRETERS: dict[str, list[str]] = {
    "python": ["python3", "-c"],
    "javascript": ["node", "-e"],
    "ruby": ["ruby", "-e"],
    "sh": ["sh", "-c"],
    "bash": ["bash", "-c"],
}


@dataclass
class SandboxResult:
    """Result from a sandboxed code execution."""
    success: bool = False
    stdout: str = ""
    stderr: str = ""
    returncode: int = -1
    error: Optional[str] = None


def run_sandboxed(
    code: str,
    language: str = "python",
    timeout: int = 30,
) -> SandboxResult:
    """Run code in a sandboxed subprocess.

    Args:
        code:     Source code to execute.
        language: Language name ("python", "javascript", etc.).
        timeout:  Max execution time in seconds.

    Returns a SandboxResult with success/stdout/stderr/error.
    """
    lang = language.lower()
    if lang not in _LANGUAGE_INTERPRETERS:
        return SandboxResult(
            success=False,
            error=f"Unsupported language: {language!r}. Supported: {list(_LANGUAGE_INTERPRETERS)}",
        )

    cmd_prefix = _LANGUAGE_INTERPRETERS[lang]
    cmd = cmd_prefix + [code]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return SandboxResult(
            success=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=proc.stderr,
            returncode=proc.returncode,
            error=proc.stderr.strip() if proc.returncode != 0 else None,
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(
            success=False,
            error=f"Execution timed out after {timeout}s",
        )
    except FileNotFoundError as exc:
        return SandboxResult(
            success=False,
            error=f"Interpreter not found: {exc}",
        )
    except Exception as exc:
        return SandboxResult(
            success=False,
            error=str(exc),
        )


def check_docker() -> tuple[bool, str]:
    """Check if Docker is available. Returns (available, version_string)."""
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return True, version
        return False, "Docker not available"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False, "Docker not found"


class Sandbox:
    """Run commands in a Docker container for isolation."""

    def __init__(self, image: str = SANDBOX_IMAGE):
        self.image = image
        self.available = False
        self._check()

    def _check(self) -> None:
        available, _ = check_docker()
        self.available = available

    def run(self, command: str, cwd: str | None = None, timeout: int = 120) -> tuple[str, str, int]:
        """Run a command in a sandboxed Docker container.

        Returns:
            (stdout, stderr, returncode)
        """
        if not self.available:
            # Fallback to direct execution
            return self._run_direct(command, timeout)

        return self._run_docker(command, cwd, timeout)

    def _run_docker(self, command: str, cwd: str | None, timeout: int) -> tuple[str, str, int]:
        """Run command inside a Docker container."""
        work_dir = cwd or os.getcwd()

        # Escape the command for passing to docker
        docker_cmd = [
            "docker", "run", "--rm",
            "--network", "none",
            "--memory", SANDBOX_MEM_LIMIT,
            "--cpus", SANDBOX_CPU_LIMIT,
            "--read-only",
            "-v", f"{work_dir}:/workspace",
            "-w", "/workspace",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            self.image,
            "sh", "-c", command,
        ]

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True, text=True,
                timeout=timeout,
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return "", f"Sandbox: command timed out after {timeout}s", -1
        except OSError as e:
            return "", f"Sandbox error: {e}", -1

    def _run_direct(self, command: str, timeout: int) -> tuple[str, str, int]:
        """Fallback: run directly without sandbox."""
        try:
            result = subprocess.run(
                command, shell=True,
                capture_output=True, text=True,
                timeout=timeout,
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return "", f"Command timed out after {timeout}s", -1
        except Exception as e:
            return "", f"Error: {e}", -1

    def pull_image(self) -> str:
        """Pull the sandbox Docker image. Returns status message."""
        if not self.available:
            return "Docker not available"
        try:
            result = subprocess.run(
                ["docker", "pull", self.image],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                return f"Pulled {self.image}"
            return f"Failed to pull image: {result.stderr.strip()[:200]}"
        except subprocess.TimeoutExpired:
            return "Pull timed out"
        except Exception as e:
            return f"Error: {e}"

    def ensure_image(self) -> bool:
        """Ensure the sandbox image is available. Returns True if ready."""
        if not self.available:
            return False
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", self.image],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return True
            # Image not found, try to pull
            self.pull_image()
            result = subprocess.run(
                ["docker", "image", "inspect", self.image],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False


# Global singleton — lock guards against simultaneous creation from multiple
# threads (possible in the Web UI where requests run concurrently).
_sandbox: Sandbox | None = None
_sandbox_lock = threading.Lock()


def get_sandbox() -> Sandbox:
    """Get or create the global sandbox instance (thread-safe)."""
    global _sandbox
    if _sandbox is None:
        with _sandbox_lock:
            if _sandbox is None:  # double-checked locking
                instance = Sandbox()
                if instance.available:
                    instance.ensure_image()
                _sandbox = instance
    return _sandbox


def is_sandbox_available() -> bool:
    """Check if Docker sandbox is available."""
    return get_sandbox().available
