"""Theme support for DeepSeek Code."""

from rich.theme import Theme

DARK_THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "green",
    "dim": "dim white",
    "code": "green",
    "title": "bold cyan",
    "subtitle": "dim white",
    "tool": "bold green",
    "tool_result": "yellow",
    "prompt": "bold",
    "hl": "bold cyan",
    "path": "underline blue",
    "number": "bold yellow",
    "keyword": "bold magenta",
})

LIGHT_THEME = Theme({
    "info": "blue",
    "warning": "orange3",
    "error": "bold red",
    "success": "green",
    "dim": "grey58",
    "code": "green",
    "title": "bold blue",
    "subtitle": "grey58",
    "tool": "bold green",
    "tool_result": "orange3",
    "prompt": "bold",
    "hl": "bold blue",
    "path": "underline blue",
    "number": "bold orange3",
    "keyword": "bold magenta",
})

THEMES = {
    "dark": DARK_THEME,
    "light": LIGHT_THEME,
}


def get_theme(name: str = "dark") -> Theme:
    return THEMES.get(name, DARK_THEME)
