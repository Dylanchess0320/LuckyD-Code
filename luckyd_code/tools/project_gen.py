"""Project scaffold generator tool.

Generates complete, ready-to-run project scaffolds from a plain-English
description using the DeepSeek model. Writes every file directly to disk.

Any project type is supported — web app, CLI tool, REST API, Discord bot,
data pipeline, etc. Just describe what you want.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

from .registry import Tool

# ---------------------------------------------------------------------------
# Prompt for the scaffold generator
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert software architect and developer.

Your job is to generate a COMPLETE project scaffold from a plain-English
description. The scaffold must be immediately usable: clone, install deps, run.

OUTPUT FORMAT — respond with a single JSON object and nothing else:
{
  "project_name": "<slug, lowercase, hyphens only>",
  "description":  "<one sentence>",
  "stack":        "<comma-separated key tech>",
  "files": [
    { "path": "relative/path/to/file.ext", "content": "<full file content>" },
    ...
  ],
  "install":  "<shell command to install dependencies>",
  "run":      "<shell command to start the project>",
  "notes":    "<optional short notes for the developer>"
}

RULES:
1. Output ONLY the JSON — no markdown fences, no prose before or after.
2. Every file must have COMPLETE content — no placeholders, no TODOs.
3. Always include: README.md, .gitignore, a dependency manifest
   (requirements.txt, package.json, pyproject.toml, go.mod, etc.).
4. Include at least one working entry-point file and one basic test file.
5. Keep the scaffold focused and minimal — just enough to be genuinely useful.
6. Use modern, idiomatic conventions for the chosen language/framework.
7. All secrets/API keys must use environment variables loaded from a .env file;
   include a .env.example but never a real .env.
"""


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class ProjectGenTool(Tool):
    """Generate a complete project scaffold from a plain-English description.

    Use this tool when the user asks to:
      - Start a new project ("create a FastAPI CRUD app")
      - Generate boilerplate for any language or framework
      - Scaffold a CLI tool, web API, Discord bot, data pipeline, etc.
    """

    name = "ProjectGen"
    description = (
        "Generate a complete, ready-to-run project scaffold from a plain-English "
        "description. Writes all files to disk. Any project type is supported — "
        "web app, CLI tool, REST API, Discord bot, data pipeline, browser extension, etc."
    )
    parameters = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": (
                    "Plain-English description of the project to generate. "
                    "Include the language/framework if you have a preference. "
                    "Examples: 'a FastAPI CRUD API with SQLite', "
                    "'a React todo app with Tailwind', "
                    "'a Python CLI that converts Markdown to PDF'."
                ),
            },
            "output_dir": {
                "type": "string",
                "description": (
                    "Parent directory to create the project folder inside. "
                    "Defaults to the current working directory."
                ),
                "default": ".",
            },
        },
        "required": ["description"],
    }
    permission_risk = "medium"

    def _call_model(self, description: str) -> dict[str, Any]:
        """Ask the model to generate the scaffold JSON."""
        raw = self._call_model_direct(description)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = "\n".join(
                ln for ln in raw.splitlines() if not ln.startswith("```")
            ).strip()

        return dict(json.loads(raw))

    def _call_model_direct(self, description: str) -> str:
        from ..config import get_api_key, get_base_url  # noqa: PLC0415
        payload = {
            "model": "deepseek-v4-flash",
            "max_tokens": 8192,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Project description: {description}"},
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
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return str(data["choices"][0]["message"]["content"])

    def run(self, description: str, output_dir: str = ".") -> str:
        parent = Path(output_dir).expanduser().resolve()
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return f"Error: cannot create output directory: {e}"

        try:
            scaffold = self._call_model(description)
        except json.JSONDecodeError as e:
            return f"Error: model returned invalid JSON — {e}"
        except Exception as e:
            return f"Error: model call failed — {e}"

        project_name = scaffold.get("project_name", "generated-project")
        files: list[dict[str, Any]] = scaffold.get("files", [])
        if not files:
            return "Error: model returned no files."

        project_dir = parent / project_name
        written: list[str] = []
        errors: list[str] = []

        for f in files:
            rel = f.get("path", "").lstrip("/")
            content = f.get("content", "")
            if not rel:
                continue
            target = project_dir / rel
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                written.append(rel)
            except OSError as e:
                errors.append(f"{rel}: {e}")

        lines = [
            f"Project '{project_name}' created at {project_dir}",
            f"Stack   : {scaffold.get('stack', 'n/a')}",
            f"Files   : {len(written)} written",
        ]
        if errors:
            lines.append(f"Errors  : {len(errors)}")
            lines.extend(f"  {e}" for e in errors)
        lines += [
            "",
            f"Install : {scaffold.get('install', 'n/a')}",
            f"Run     : {scaffold.get('run', 'n/a')}",
        ]
        if scaffold.get("notes"):
            lines += ["", f"Notes   : {scaffold['notes']}"]

        return "\n".join(lines)
