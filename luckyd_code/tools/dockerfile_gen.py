"""Dockerfile & docker-compose generator tool.

Scans the project to detect the stack, then generates a production-ready
Dockerfile (and optionally a docker-compose.yml) using the DeepSeek model.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

from .registry import Tool

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a senior DevOps engineer specialising in Docker.

Given a list of project files and their contents, generate a production-ready
Dockerfile and, if the project has external dependencies (database, cache,
message broker, etc.), a docker-compose.yml too.

OUTPUT FORMAT — respond with ONLY a JSON object:
{
  "dockerfile": "<full Dockerfile content>",
  "compose":    "<full docker-compose.yml content or empty string if not needed>",
  "notes":      "<optional short notes: port, env vars, commands to know>"
}

RULES:
1. Output ONLY the JSON. No markdown fences, no prose.
2. Use multi-stage builds for compiled languages.
3. Run as a non-root user in the final stage.
4. Use .dockerignore best practices (hint in notes if needed).
5. Use ARG/ENV for configurable values; never hard-code secrets.
6. Pin base image versions (e.g. python:3.12-slim, node:20-alpine).
7. Install only production dependencies in the final image.
8. If compose is generated: use named volumes, health checks, depends_on.
"""

_MAX_FILE_CHARS = 2000
_PRIORITY_FILES = {
    "requirements.txt", "pyproject.toml", "setup.py", "Pipfile",
    "package.json", "yarn.lock", "pnpm-lock.yaml",
    "go.mod", "go.sum", "Cargo.toml",
    "Gemfile", "build.gradle", "pom.xml",
    "main.py", "app.py", "server.py", "index.js", "index.ts",
    "main.go", "main.rs", ".env.example",
}
_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    "dist", "build", "target",
}
_SKIP_EXTS = {".pyc", ".pyo", ".so", ".dll", ".exe", ".png", ".jpg", ".lock"}


def _collect_context(root: Path) -> str:
    parts: list[str] = []
    seen: set[str] = set()

    for name in _PRIORITY_FILES:
        p = root / name
        if p.exists() and p.is_file():
            rel = str(p.relative_to(root))
            try:
                text = p.read_text(encoding="utf-8", errors="replace")[:_MAX_FILE_CHARS]
                parts.append(f"=== {rel} ===\n{text}")
                seen.add(rel)
            except Exception:
                pass

    count = 0
    for p in sorted(root.rglob("*")):
        if count >= 10:
            break
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.suffix in _SKIP_EXTS or not p.is_file():
            continue
        rel = str(p.relative_to(root))
        if rel in seen:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:_MAX_FILE_CHARS]
            parts.append(f"=== {rel} ===\n{text}")
            seen.add(rel)
            count += 1
        except Exception:
            pass

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class DockerfileGenTool(Tool):
    """Generate a production-ready Dockerfile (and docker-compose.yml if needed).

    Use this tool when the user asks to:
      - Dockerise or containerise their project
      - Write a Dockerfile for any language / framework
      - Set up docker-compose with services (database, cache, etc.)
    """

    name = "DockerfileGen"
    description = (
        "Scan the current project and generate a production-ready Dockerfile "
        "and docker-compose.yml. Works with any language or framework. "
        "Auto-detects the stack from dependency files and source code."
    )
    parameters = {
        "type": "object",
        "properties": {
            "project_dir": {
                "type": "string",
                "description": "Root directory of the project. Defaults to cwd.",
                "default": ".",
            },
            "overwrite": {
                "type": "boolean",
                "description": "Overwrite existing Dockerfile / docker-compose.yml.",
                "default": False,
            },
        },
        "required": [],
    }
    permission_risk = "medium"

    def _call_model(self, context: str) -> dict[str, Any]:
        user_msg = f"Project files:\n\n{context}\n\nGenerate the Dockerfile and compose file."
        raw = self._call_model_direct(user_msg)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = "\n".join(ln for ln in raw.splitlines() if not ln.startswith("```")).strip()
        return dict(json.loads(raw))

    def _call_model_direct(self, user_msg: str) -> str:  # pragma: no cover
        from ..config import get_api_key, get_base_url  # noqa: PLC0415
        payload = {
            "model": "deepseek-v4-flash",
            "max_tokens": 4096,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        }
        req = urllib.request.Request(
            f"{get_base_url()}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {get_api_key()}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read())
        return str(data["choices"][0]["message"]["content"])

    def run(self, project_dir: str = ".", overwrite: bool = False) -> str:
        root = Path(project_dir).expanduser().resolve()
        if not root.is_dir():
            return f"Error: '{root}' is not a directory."

        df_path = root / "Dockerfile"
        compose_path = root / "docker-compose.yml"

        if df_path.exists() and not overwrite:
            return "Dockerfile already exists. Pass overwrite=true to replace it."

        context = _collect_context(root)
        if not context:
            return "Error: no readable source files found."

        try:
            result = self._call_model(context)
        except json.JSONDecodeError as e:
            return f"Error: model returned invalid JSON \u2014 {e}"
        except Exception as e:
            return f"Error: model call failed \u2014 {e}"

        dockerfile = result.get("dockerfile", "").strip()
        compose = result.get("compose", "").strip()
        notes = result.get("notes", "")

        written: list[str] = []

        if dockerfile:
            try:
                df_path.write_text(dockerfile, encoding="utf-8")
                written.append(str(df_path))
            except OSError as e:
                return f"Error writing Dockerfile: {e}"

        if compose:
            try:
                compose_path.write_text(compose, encoding="utf-8")
                written.append(str(compose_path))
            except OSError as e:
                return f"Error writing docker-compose.yml: {e}"

        lines = [f"Generated {len(written)} file(s):"]
        lines.extend(f"  {w}" for w in written)
        if notes:
            lines += ["", f"Notes: {notes}"]
        return "\n".join(lines)
