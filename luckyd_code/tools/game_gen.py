"""Video game generator tool.

Generates standalone, playable Pygame games from a natural-language description
using the DeepSeek model. Optionally compiles them into self-contained .exe files
via PyInstaller. All games use SDL2's software "windib" driver so they run
without a GPU.

Any game concept is supported — just describe what you want.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from .registry import Tool

# ---------------------------------------------------------------------------
# Difficulty presets injected into every generation prompt
# ---------------------------------------------------------------------------

DIFFICULTIES = ("easy", "normal", "hard")

DIFFICULTY_HINTS = {
    "easy":   "Use slow speeds, generous hitboxes, and forgiving rules. Favor the player.",
    "normal": "Use balanced speeds and standard game rules.",
    "hard":   "Use fast speeds, tight hitboxes, and punishing rules. Challenge the player.",
}

# ---------------------------------------------------------------------------
# System prompt for game generation
# ---------------------------------------------------------------------------

GAME_GEN_SYSTEM_PROMPT = """\
You are an expert Python game developer specialising in Pygame.

Your job is to write a COMPLETE, RUNNABLE, single-file Pygame game based on the
user's description. Follow every rule below without exception.

=== MANDATORY RULES ===

1. OUTPUT ONLY VALID PYTHON CODE — no markdown fences, no prose, no comments
   outside the code. The very first character must be a double-quote (start of
   the module docstring) or the letter 'i' (start of an import).

2. IMPORTS — always start with:
       import os, sys, random, math
       os.environ.setdefault("SDL_VIDEODRIVER", "windib")
       import pygame
   This order ensures the SDL env var is set before pygame.init().

3. STRUCTURE — use a single main() function and end with:
       if __name__ == "__main__":
           main()

4. WINDOW — 800x600, 60 FPS, pygame.display.set_caption("<game name>").

5. THEME COLOR — the caller substitutes the literal string #THEME_COLOR# with a
   hex color such as #00FF00. Use it as the primary foreground color for all
   game elements. Always reference it as:
       THEME_COLOR = "#THEME_COLOR#"
   Then convert once with:
       def _hex(h):
           h = h.lstrip("#")
           return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
       FG = _hex(THEME_COLOR)

6. DIFFICULTY — the caller substitutes the literal float #DIFF_MULT# (0.7 easy /
   1.0 normal / 1.4 hard). Store it as:
       DIFF_MULT = #DIFF_MULT#
   Use it to scale speeds, spawn rates, or AI strength.

7. QUIT — always handle pygame.QUIT and the ESC key to exit cleanly.

8. RESTART — after game-over show a "Press R to restart / ESC to quit" screen
   and honour both keys.

9. HUD — always draw the current score (or lives, timer, etc.) on screen.

10. NO EXTERNAL ASSETS — no image files, no sound files, no fonts beyond
    pygame.font.SysFont. Draw everything with pygame primitives.

11. BEEP — synthesise simple square-wave sound effects using pygame.mixer and
    bytearray; never load .wav / .mp3 files. Use this helper:
        pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=256)
        def beep(freq=440, ms=60, vol=0.12):
            try:
                n = int(22050 * ms / 1000)
                buf = bytearray(n)
                for i in range(n):
                    buf[i] = (127 if (i * freq * 2 // 22050) % 2 == 0 else 129) & 0xFF
                s = pygame.mixer.Sound(buffer=bytes(buf))
                s.set_volume(vol)
                s.play()
            except Exception:
                pass

12. COMPLETENESS — every mechanic you describe must be fully implemented. Do not
    leave stubs, TODOs, or placeholder comments. The file must run as-is with
    only `pip install pygame`.

13. BACKGROUND — use a near-black background (5, 5, 15) for all games.

=== STYLE GUIDELINES ===
- Keep code clean and readable with concise inline comments.
- Prefer pure-Python math over numpy.
- Aim for clean, readable code; prioritise completeness and playability over brevity.
  Never truncate or stub out mechanics — write every function fully.
- Make the game genuinely fun: good game-feel, responsive controls, clear
  feedback on events.
"""


# ---------------------------------------------------------------------------
# Compile helpers
# ---------------------------------------------------------------------------

def _resolve_pyinstaller() -> Optional[str]:
    if shutil.which("pyinstaller"):
        return "found"
    try:
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--version"],
            capture_output=True, timeout=10,
        )
        return "module"
    except Exception:
        return None


def compile_exe(source_path: Path, output_dir: Path, game_name: str) -> tuple[bool, str]:
    """Compile a Python script to a standalone .exe via PyInstaller."""
    if _resolve_pyinstaller() is None:
        return False, "PyInstaller is not installed. Run: pip install pyinstaller"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile", "--windowed", "--noconsole",
        "--name", game_name,
        "--distpath", str(output_dir),
        "--workpath", str(output_dir / "_build"),
        "--specpath", str(output_dir),
        str(source_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=output_dir)
        if result.returncode != 0:
            return False, f"PyInstaller failed (exit {result.returncode}):\n{result.stderr[-500:]}"
        exe_path = output_dir / f"{game_name}.exe"
        if exe_path.exists():
            for artifact in [output_dir / "_build", output_dir / f"{game_name}.spec"]:
                if artifact.is_dir():
                    shutil.rmtree(artifact, ignore_errors=True)
                elif artifact.is_file():
                    artifact.unlink(missing_ok=True)
            return True, str(exe_path)
        return False, f"Compilation ran but .exe not found at {exe_path}"
    except subprocess.TimeoutExpired:
        return False, "PyInstaller timed out (5 minutes)"
    except Exception as e:
        return False, f"PyInstaller error: {e}"


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class GameGenTool(Tool):
    """Generate a playable Pygame game from a natural-language description.

    Use this tool when the user asks to:
      - Create any kind of video game ("make me a top-down shooter")
      - Generate a playable game they can run locally or distribute as an .exe
      - Adjust an existing game's difficulty or visual theme
    """

    name = "GameGen"
    description = (
        "Generate a complete, runnable Pygame game from a plain-English description. "
        "Any game concept is supported — just describe the game you want. "
        "Outputs a .py script or a standalone .exe (requires PyInstaller). "
        "No GPU needed; uses SDL2 software rendering."
    )
    parameters = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": (
                    "Plain-English description of the game to generate. "
                    "Be as specific or as vague as you like — the model will fill in the details. "
                    "Examples: 'a Breakout clone', 'a top-down zombie shooter', "
                    "'a simple platformer where you collect coins'."
                ),
            },
            "difficulty": {
                "type": "string",
                "description": "Game difficulty: easy, normal, or hard.",
                "enum": list(DIFFICULTIES),
                "default": "normal",
            },
            "theme_color": {
                "type": "string",
                "description": "Hex color for the primary game elements, e.g. '#00FF00'.",
                "default": "#00FF00",
            },
            "output_format": {
                "type": "string",
                "description": "'py' for a Python script, 'exe' for a standalone executable.",
                "enum": ["py", "exe"],
                "default": "exe",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory to write the output file to.",
                "default": ".",
            },
        },
        "required": ["description"],
    }
    permission_risk = "safe"

    def _generate_source(self, description: str, difficulty: str, _theme_color: str = "") -> str:
        """Ask the DeepSeek model to write the full Pygame source."""
        try:
            return self._generate_source_api(description, difficulty)
        except Exception:
            return self._generate_source_fallback(description, difficulty)

    def _generate_source_api(self, description: str, difficulty: str) -> str:
        """Use the project's stream_chat API to generate the game."""
        from ..api import stream_chat  # noqa: PLC0415
        from ..config import Config  # noqa: PLC0415

        cfg = Config()
        diff_hint = DIFFICULTY_HINTS.get(difficulty, DIFFICULTY_HINTS["normal"])
        user_prompt = (
            f"Game description: {description}\n\n"
            f"Difficulty hint: {diff_hint}\n\n"
            f"Use #THEME_COLOR# as the literal placeholder for the theme color "
            f"and #DIFF_MULT# as the literal placeholder for the difficulty multiplier."
        )

        messages = [
            {"role": "system", "content": GAME_GEN_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        parts: list[str] = []
        for event in stream_chat(
            messages=messages,
            tools=[],
            model=cfg.model,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            max_tokens=16000,
            temperature=0.3,
        ):
            kind, data = event
            if kind == "text":
                parts.append(data)
            elif kind == "error":
                raise RuntimeError(f"API error: {data}")
        return "".join(parts).strip()

    def _generate_source_fallback(self, description: str, difficulty: str) -> str:
        """Direct API call using Config and urllib."""
        import json
        import urllib.request  # noqa: PLC0415
        from ..config import Config  # noqa: PLC0415

        cfg = Config()
        diff_hint = DIFFICULTY_HINTS.get(difficulty, DIFFICULTY_HINTS["normal"])
        payload = {
            "model": "deepseek-v4-flash",
            "max_tokens": 16000,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": GAME_GEN_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Game description: {description}\n\n"
                        f"Difficulty hint: {diff_hint}\n\n"
                        "Use #THEME_COLOR# and #DIFF_MULT# as literal placeholders."
                    ),
                },
            ],
        }
        req = urllib.request.Request(
            f"{cfg.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg.api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data: dict[str, Any] = json.loads(resp.read())
        return str(data["choices"][0]["message"]["content"].strip())

    def run(
        self,
        description: str,
        difficulty: str = "normal",
        theme_color: str = "#00FF00",
        output_format: str = "exe",
        output_dir: str = ".",
    ) -> str:

        if difficulty not in DIFFICULTIES:
            return f"Error: unknown difficulty '{difficulty}'. Use: {', '.join(DIFFICULTIES)}"
        if output_format not in ("py", "exe"):
            return "Error: output_format must be 'py' or 'exe'."

        out_dir = Path(output_dir).expanduser().resolve()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return f"Error: cannot create output directory: {e}"

        try:
            raw_source = self._generate_source(description, difficulty, theme_color)
        except Exception as e:
            return f"Error: model call failed — {e}"

        source = raw_source
        if source.startswith("```"):
            lines = source.splitlines()
            source = "\n".join(
                ln for ln in lines if not ln.startswith("```")
            ).strip()

        diff_mult = {"easy": 0.7, "normal": 1.0, "hard": 1.4}[difficulty]
        source = source.replace("#THEME_COLOR#", theme_color)
        source = source.replace("#DIFF_MULT#", str(diff_mult))

        slug = "_".join(description.split()[:4])
        slug = "".join(c if c.isalnum() or c == "_" else "" for c in slug) or "Game"
        game_name = slug[:40]

        py_path = out_dir / f"{game_name}.py"
        try:
            py_path.write_text(source, encoding="utf-8")
        except OSError as e:
            return f"Error: failed to write source file: {e}"

        if output_format == "py":
            return (
                f"Game generated successfully.\n"
                f"File : {py_path}\n"
                f"Run  : python \"{py_path}\"\n"
                f"Needs: pip install pygame"
            )

        success, result = compile_exe(py_path, out_dir, game_name)
        if success:
            return f"Standalone .exe created.\nFile: {result}"
        return f"Compilation failed: {result}\nSource saved at: {py_path}"
