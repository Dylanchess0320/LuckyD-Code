"""Smart project indexing — scan project structure and inject into context."""

import os
import json
from pathlib import Path
from typing import Any

from .log import get_logger


def _load_gitignore(path: Path) -> list[str]:
    """Load .gitignore patterns."""
    patterns = []
    gitignore = path / ".gitignore"
    if gitignore.exists():
        try:
            for line in gitignore.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
        except Exception:
            get_logger().warning("Could not load .gitignore", exc_info=True)
    return patterns


def _is_ignored(name: str, patterns: list[str]) -> bool:
    """Check if a name matches gitignore patterns."""
    for p in patterns:
        if p.endswith("/") and name == p.rstrip("/"):
            return True
        if name == p:
            return True
        if p.startswith("*.") and name.endswith(p[1:]):
            return True
    return False


IGNORED_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    ".tox", ".eggs", "dist", "build", ".next", ".nuxt",
    "target", "vendor", ".bundle", ".claude", ".vscode", ".idea",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
}

IGNORED_EXTS = {
    ".pyc", ".pyo", ".so", ".o", ".class", ".jar",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".exe", ".msi", ".dmg", ".pkg",
    ".log", ".tmp",
}


def scan_project(root: Path, max_depth: int = 3, max_items: int = 80) -> dict[str, Any]:
    """Scan a project directory and return structured metadata."""
    root = root.resolve()
    gitignore_patterns = _load_gitignore(root)

    info: dict[str, Any] = {
        "name": root.name,
        "path": str(root),
        "languages": set(),
        "frameworks": [],
        "config_files": {},
        "file_tree": [],
        "dependency_files": [],
        "entry_points": [],
        "total_files": 0,
    }

    dirs_to_scan = [(root, 0)]
    scanned = 0

    while dirs_to_scan and scanned < max_items:
        current, depth = dirs_to_scan.pop(0)

        if depth > max_depth:
            continue

        try:
            entries = sorted(current.iterdir(), key=lambda x: (not x.is_dir(), x.name))
        except PermissionError:
            continue

        indent = "  " * depth
        for entry in entries:
            if scanned >= max_items:
                break

            name = entry.name
            if name in IGNORED_DIRS or _is_ignored(name, gitignore_patterns):
                continue

            if entry.is_dir():
                if not name.startswith(".") and not name.endswith(".egg-info"):
                    info["file_tree"].append(f"{indent}{name}/")
                    dirs_to_scan.append((entry, depth + 1))
                    scanned += 1
            else:
                ext = entry.suffix.lower()
                if ext in IGNORED_EXTS:
                    continue

                info["file_tree"].append(f"{indent}{name}")
                info["total_files"] += 1
                scanned += 1

                # Detect language
                lang = _detect_language(ext)
                if lang:
                    info["languages"].add(lang)

                # Detect dependency files
                if name in ("package.json", "pyproject.toml", "Cargo.toml",
                            "requirements.txt", "Gemfile", "go.mod", "CMakeLists.txt",
                            "composer.json", "Pipfile", "build.gradle", "pom.xml"):
                    info["dependency_files"].append(name)
                    deps = _extract_deps(entry, name)
                    if deps:
                        info["config_files"][name] = deps

                # Detect entry points
                if name in ("main.py", "index.js", "app.js", "cli.py",
                            "main.go", "main.rs", "index.ts", "app.ts"):
                    info["entry_points"].append(str(entry.relative_to(root)))

    # Detect framework
    info["frameworks"] = _detect_frameworks(info["config_files"], info["dependency_files"])

    # Convert languages set to sorted list
    info["languages"] = sorted(info["languages"])

    return info


def _detect_language(ext: str) -> str | None:
    mapping = {
        ".py": "Python", ".pyi": "Python",
        ".js": "JavaScript", ".jsx": "JavaScript/JSX",
        ".ts": "TypeScript", ".tsx": "TypeScript/TSX",
        ".rs": "Rust",
        ".go": "Go",
        ".java": "Java",
        ".kt": "Kotlin",
        ".rb": "Ruby",
        ".php": "PHP",
        ".c": "C", ".h": "C",
        ".cpp": "C++", ".hpp": "C++", ".cc": "C++",
        ".cs": "C#",
        ".swift": "Swift",
        ".toml": "TOML", ".yaml": "YAML", ".yml": "YAML",
        ".json": "JSON", ".html": "HTML", ".css": "CSS",
        ".md": "Markdown",
        ".sql": "SQL",
        ".sh": "Shell", ".bat": "Batch",
        ".pl": "Perl",
        ".lua": "Lua",
        ".r": "R",
        ".scala": "Scala",
    }
    return mapping.get(ext)


def _detect_frameworks(config_files: dict[str, Any], dep_files: list[str]) -> list[str]:
    frameworks = []
    for fname, deps in config_files.items():
        deps_lower = {d.lower() for d in deps}
        # Python
        if "django" in deps_lower:
            frameworks.append("Django")
        if "flask" in deps_lower:
            frameworks.append("Flask")
        if "fastapi" in deps_lower:
            frameworks.append("FastAPI")
        # JS/TS
        if "react" in deps_lower or "next" in deps_lower:
            frameworks.append("React/Next.js")
        if "vue" in deps_lower:
            frameworks.append("Vue")
        if "express" in deps_lower or "@nestjs/core" in deps_lower:
            frameworks.append("Express/NestJS")
        if "tailwindcss" in deps_lower:
            frameworks.append("Tailwind CSS")
        # Rust
        if "actix-web" in deps_lower or "axum" in deps_lower:
            frameworks.append("Actix/Axum")
        # Other
        if "spring-boot" in deps_lower:
            frameworks.append("Spring Boot")

    return list(set(frameworks))


def _extract_deps(filepath: Path, name: str) -> list[str]:
    """Extract dependency names from a config file."""
    try:
        if name == "package.json":
            data = json.loads(filepath.read_text(encoding="utf-8"))
            return list(data.get("dependencies", {}).keys()) + list(data.get("devDependencies", {}).keys())
        elif name == "pyproject.toml":
            content = filepath.read_text(encoding="utf-8")
            deps = []
            for line in content.splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("[") and not line.startswith("#"):
                    parts = line.split("=")
                    key = parts[0].strip().strip('"').strip("'")
                    if key and not key.startswith("_"):
                        deps.append(key)
            return deps[:30]
        elif name == "requirements.txt":
            content = filepath.read_text(encoding="utf-8")
            deps = []
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("-"):
                    dep = line.split(">=")[0].split("==")[0].split("~=")[0].strip()
                    deps.append(dep)
            return deps[:30]
        elif name == "Cargo.toml":
            content = filepath.read_text(encoding="utf-8")
            deps = []
            in_deps = False
            for line in content.splitlines():
                line = line.strip()
                if line == "[dependencies]":
                    in_deps = True
                    continue
                if in_deps and line.startswith("["):
                    break
                if in_deps and "=" in line:
                    dep = line.split("=")[0].strip().strip('"').strip("'")
                    if dep:
                        deps.append(dep)
            return deps[:20]
    except Exception:
        get_logger().warning("Could not extract dependencies from %s", name, exc_info=True)
    return []


def format_project_context(info: dict[str, Any]) -> str:
    """Format project info into a concise context string for the AI."""
    parts = [f"# Project: {info['name']}"]

    if info["languages"]:
        parts.append(f"Languages: {', '.join(info['languages'])}")

    if info["frameworks"]:
        parts.append(f"Frameworks: {', '.join(info['frameworks'])}")

    if info["entry_points"]:
        parts.append(f"Entry points: {', '.join(info['entry_points'])}")

    if info["dependency_files"]:
        parts.append(f"Config files: {', '.join(info['dependency_files'])}")

    if info["total_files"]:
        parts.append(f"Total source files: {info['total_files']}")

    # File tree
    if info["file_tree"]:
        parts.append("\nFile tree:")
        parts.append("\n".join(info["file_tree"]))

    return "\n".join(parts)


def index_project(project_dir: str | None = None) -> str:
    """Scan a project and return formatted context. Runs in <1s."""
    if project_dir:
        root = Path(project_dir).resolve()
    else:
        root = Path(os.getcwd()).resolve()

    if not root.exists():
        return ""

    info = scan_project(root)
    return format_project_context(info)
