# LuckyD Code Plugin System

LuckyD Code supports community plugins — drop a `.py` file into your plugin directory and it auto-loads as a new tool available to the AI in every session.

---

## Quick start

**1. Find your plugin directory**

```bash
# Inside ldc
/plugins dir
```

On most systems this is `~/.luckyd-code/plugins/`.

**2. Create a plugin**

```bash
# Scaffold a starter file automatically
/plugins new my_tool
```

Or copy one of the examples from [`examples/plugins/`](../examples/plugins/).

**3. Activate it**

```bash
/plugins reload
```

No restart needed. Your new tool is immediately available to the AI.

---

## Plugin structure

Every plugin is a single `.py` file with two things:

- A class that extends `Tool`
- A `register(registry)` function

```python
from luckyd_code.tools.registry import Tool

class MyTool(Tool):
    name = "MyTool"                          # must be unique
    description = "One sentence description" # shown to the AI
    parameters = {                           # JSON Schema
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "The input"},
        },
        "required": ["input"],
    }

    def run(self, input: str = "") -> str:
        return f"You passed: {input}"

def register(registry) -> None:
    registry.register(MyTool())
```

That's it.

---

## Tool base class

| Attribute | Type | Description |
|---|---|---|
| `name` | `str` | Unique tool name. Used by the AI to call your tool. |
| `description` | `str` | One sentence shown to the AI. Make it specific. |
| `parameters` | `dict` | JSON Schema describing the arguments. |
| `permission_risk` | `str` | `"safe"` / `"medium"` / `"high"` (default: `"safe"`) |

The `run()` method receives keyword arguments matching your `parameters` schema and must return a `str`.

---

## Examples

| Plugin | What it shows |
|---|---|
| [`hello_world.py`](../examples/plugins/hello_world.py) | Minimal plugin, no dependencies |
| [`word_counter.py`](../examples/plugins/word_counter.py) | File I/O, optional parameters |
| [`json_formatter.py`](../examples/plugins/json_formatter.py) | Error handling, type checking |

---

## CLI commands

| Command | Description |
|---|---|
| `/plugins` | List all loaded plugins and their status |
| `/plugins reload` | Hot-reload all plugins (no restart needed) |
| `/plugins dir` | Show the plugin directory path |
| `/plugins new <name>` | Scaffold a new plugin file |

---

## Tips

- **Return strings** — the AI reads your tool's return value as plain text.
- **Handle errors** — catch exceptions and return a descriptive error string rather than letting them propagate.
- **Keep it focused** — one tool per plugin is the clearest pattern.
- **Use `permission_risk`** — set `"medium"` or `"high"` if your tool writes files or calls external APIs, so the permission system prompts the user before running.
- **No restart needed** — `/plugins reload` hot-swaps plugins in the running session.

---

## Sharing plugins

If you build something useful, open a PR adding it to `examples/plugins/` — community plugins are welcome.

---

## Troubleshooting

**Plugin not loading?**

Run `/plugins list` — it shows each plugin's status and any error. Common causes:

- No `register(registry)` function
- Syntax error in the file
- Import of a package that isn't installed

**Tool not available to AI?**

After adding or editing a plugin, run `/plugins reload`. The tool appears in the AI's tool list immediately after.
