"""README generator tool.

Scans the current project directory and generates a polished, professional
README.md using the DeepSeek model. Understands any language or framework.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from .registry import Tool

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a senior technical writer. Your job is to write a polished, professional
README.md for a software project based on the source files you are given.

RULES:
1. Output ONLY valid Markdown — no preamble, no code fences around the whole output.
2. Structure: title, one-line description, badges (if applicable), Features,
   Prerequisites, Installation, Usage, Configuration (.env vars if any),
   Contributing, License.
3. Be concise but complete. Real examples over generic placeholders.
4. Infer the tech stack, purpose, and usage from the files provided.
5. Use proper Markdown code blocks with language tags for all code/commands.
6. If a LICENSE file is present, reference the licence type in the badge/section.
"""

_MAX_FILE_CHARS = 3000
_MAX_FILES      = 20

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "node_modules",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".claude", ".deepseek-code",
}

_SKIP_EXTS = {
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe", ".egg",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".lock", ".min.js", ".min.css",
}

_PRIORITY_FILES = {
    "main.py", "app.py", "cli.py", "server.py", "index.js", "index.ts",
    "main.go", "main.rs", "Cargo.toml", "go.mod", "pyproject.toml",
    "package.json", "requirements.txt", "setup.py", "Makefile",
    "Dockerfile", ".env.example", "LICENSE",
}


def _collect_files(root: Path) -> list[tuple[str, str]]:
    """Return list of (relative_path, content_snippet) for key project files."""
    collected: list[tuple[str, str]] = []
    seen_names: set[str] = set()

    def _walk(path: Path, depth: int = 0):
        if depth > 5 or len(collected) >= _MAX_FILES:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_dir(), p.name))
        except PermissionError:
            return
        for entry in entries:
            if entry.name.startswith(".") and entry.name not in {".env.example"}:
                continue
            if entry.name in _SKIP_DIRS:
                continue
            if entry.is_dir():
                _walk(entry, depth + 1)
            elif entry.is_file() and entry.suffix not in _SKIP_EXTS:
                rel = str(entry.relative_to(root))
                if rel in seen_names or len(collected) >= _MAX_FILES:
                    continue
                seen_names.add(rel)
                try:
                    text = entry.read_text(encoding="utf-8", errors="replace")
                    snippet = text[:_MAX_FILE_CHARS]
                    if len(text) > _MAX_FILE_CHARS:
                        snippet += f"\n... ({len(text) - _MAX_FILE_CHARS} chars truncated)"
                    collected.append((rel, snippet))
                except Exception:
                    pass

    for name in _PRIORITY_FILES:
        candidate = root / name
        if candidate.exists() and candidate.is_file():
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
                snippet = text[:_MAX_FILE_CHARS]
                if len(text) > _MAX_FILE_CHARS:
                    snippet += f"\n... ({len(text) - _MAX_FILE_CHARS} chars truncated)"
                collected.append((str(candidate.relative_to(root)), snippet))
                seen_names.add(str(candidate.relative_to(root)))
            except Exception:
                pass

    _walk(root)
    return collected


def _format_context(files: list[tuple[str, str]]) -> str:
    parts = []
    for rel, content in files:
        parts.append(f"=== {rel} ===\n{content}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class ReadmeGenTool(Tool):
    """Generate a polished README.md by scanning the current project.

    Use this tool when the user asks to:
      - Write or improve the README for their project
      - Auto-generate documentation from source files
      - Create a professional project description
    """

    name = "ReadmeGen"
    description = (
        "Scan the current project directory and generate a professional README.md. "
        "Works with any language or framework. Infers stack, features, and usage "
        "automatically from source files."
    )
    parameters = {
        "type": "object",
        "properties": {
            "project_dir": {
                "type": "string",
                "description": "Root directory of the project to document. Defaults to cwd.",
                "default": ".",
            },
            "output_path": {
                "type": "string",
                "description": "Where to write the README. Defaults to <project_dir>/README.md.",
                "default": "",
            },
            "overwrite": {
                "type": "boolean",
                "description": "Overwrite an existing README.md. Defaults to false.",
                "default": False,
            },
        },
        "required": [],
    }
    permission_risk = "medium"

    def _call_model(self, context: str) -> str:
        return self._call_model_direct(context)

    def _call_model_direct(self, context: str) -> str:
        from ..config import get_api_key, get_base_url  # noqa: PLC0415
        payload = {
            "model": "deepseek-v4-flash",
            "max_tokens": 4096,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Project files:\n\n{context}\n\nGenerate the README.md."},
            ],
        }
        req = urllib.request.Request(
            f"{get_base_url()}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {get_api_key()}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]

    def run(
        self,
        project_dir: str = ".",
        output_path: str = "",
        overwrite: bool = False,
    ) -> str:  # type: ignore[override]
        root = Path(project_dir).expanduser().resolve()
        if not root.is_dir():
            return f"Error: '{root}' is not a directory."

        out = Path(output_path).expanduser().resolve() if output_path else root / "README.md"

        if out.exists() and not overwrite:
            return (
                f"README already exists at {out}. "
                "Pass overwrite=true to replace it."
            )

        files = _collect_files(root)
        if not files:
            return "Error: no readable source files found."

        context = _format_context(files)

        try:
            readme = self._call_model(context)
        except Exception as e:
            return f"Error: model call failed — {e}"

        readme = readme.strip()
        if readme.startswith("```markdown"):
            readme = readme[len("```markdown"):].lstrip("\n")
        if readme.endswith("```"):
            readme = readme[:-3].rstrip("\n")

        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(readme, encoding="utf-8")
        except OSError as e:
            return f"Error: could not write file — {e}"

        return (
            f"README.md generated from {len(files)} file(s).\n"
            f"Written to: {out}"
        )
