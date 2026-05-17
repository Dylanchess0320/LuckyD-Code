# LuckyD Code

**The AI coding assistant that thinks before it ships.**
Terminal-native · Browser-ready · DeepSeek-powered

<p align="center">
  <a href="https://github.com/Dylanchess0320/LuckyD-Code/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Dylanchess0320/LuckyD-Code/ci.yml?style=flat-square&label=CI&logo=github" alt="CI"></a>
  <a href="https://codecov.io/gh/Dylanchess0320/LuckyD-Code"><img src="https://img.shields.io/codecov/c/github/Dylanchess0320/LuckyD-Code?style=flat-square&logo=codecov&label=Coverage" alt="Coverage"></a>
  <a href="https://pypi.org/project/luckyd-code/"><img src="https://img.shields.io/pypi/v/luckyd-code?style=flat-square&logo=pypi&label=PyPI&color=3775A9" alt="PyPI"></a>
  <a href="https://pypi.org/project/luckyd-code/"><img src="https://img.shields.io/pypi/pyversions/luckyd-code?style=flat-square&logo=python&label=Python&color=3776AB" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL%20v3-blue?style=flat-square&logo=opensourceinitiative" alt="License"></a>
  <a href="https://github.com/Dylanchess0320/LuckyD-Code"><img src="https://img.shields.io/github/stars/Dylanchess0320/LuckyD-Code?style=flat-square&logo=github&color=FCD34D" alt="Stars"></a>
  <a href="https://discord.gg/ApEKKUuKd"><img src="https://img.shields.io/badge/Discord-Join%20Server-5865F2?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
</p>

---

## ✨ Why LuckyD Code?

| | LuckyD Code | Other Assistants |
|---|---|---|
| 🧠 **Reasoning-first** | Self-verifies every write/edit automatically | Hope the LLM gets it right |
| 🔀 **Smart routing** | Picks the right model tier per prompt | Same model for everything |
| 🗺️ **Code Knowledge Graph** | Indexes your codebase; semantic + keyword search | Blind to your project |
| 🕸️ **Web + Terminal** | Full CLI *and* browser UI from the same binary | CLI-only or browser-only |
| 🔒 **Sandboxed** | Docker-isolated command execution | Raw shell access |
| 📊 **Analytics** | Built-in code health, smell detection, trend tracking | None |
| 🔧 **Autonomous Fixer** | Diagnoses bugs → generates patches → validates → opens PR | Manual triage |

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.10+** – [python.org](https://www.python.org/downloads/) or `brew install python@3.12`
- **Rust** – only needed if `pip` can’t find a pre‑built wheel for your platform (uncommon).

### Installation

```bash
# Install from PyPI (recommended)
pip install luckyd-code

# With optional RAG support (code search & knowledge graph)
pip install luckyd-code[rag-full]

# Browser automation (for web scraping / testing)
pip install luckyd-code[browser]
```

Or clone and install in editable mode for development:

```bash
git clone https://github.com/Dylanchess0320/LuckyD-Code
cd LuckyD-Code
pip install -e ".[dev]"
```

### Usage

```bash
# Start the interactive CLI
luckyd-code

# Launch the web UI (FastAPI + WebSocket)
luckyd-code --web

# Show help
luckyd-code --help

# Quick alias (same as luckyd-code)
ldc
```

From source:

```bash
python main.py                    # CLI
python main.py --web              # Web UI
python main.py --version          # v1.3.3
```

---

## 🔑 Configuration

Create a `.env` file in the project root or set the environment variable:

```env
# DeepSeek API key (required)
DEEPSEEK_API_KEY=sk-your-deepseek-key-here
```

Get your key at [platform.deepseek.com](https://platform.deepseek.com).

Optional settings (see `config.py` for all options):

| Variable | Description |
|----------|-------------|
| `DEEPSEEK_API_KEY` | Primary API key |
| `OPENAI_API_KEY` | Fallback/alternative provider |
| `LUCKYD_CONFIG_DIR` | Custom config directory |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

Settings are resolved in this order: environment variable → config file → defaults.

---

## 🌟 Features

### Core
- **Think → Act → Verify loop** – Model generates code, tools execute it, verification checks syntax, lint, and tests automatically.
- **Smart model routing** – Four tiers (T1–T4) from lightweight chat to deep reasoning; heuristic + LLM classifier for sub‑400ms selection.
- **40+ built‑in tools** – File ops, Git operations, Docker sandbox, web fetch, code generators, browser automation, and more.

### Code Intelligence
- **Code Knowledge Graph** (RAG) – FAISS index + sentence‑transformers for semantic code search across your entire project.
- **Project Memory** – Persistent context across sessions: remembers your codebase structure and conversation history.
- **Autonomous Fixer** – Detects errors, writes patches, runs verification, and can open a PR automatically.

### Interface
- **Full CLI** – Rich terminal UI with syntax highlighting, streaming responses, slash commands (`/help`, `/install-rag`, etc.).
- **Web UI** – FastAPI + WebSocket server, same agent loop, accessible from any browser.
- **Lifecycle hooks** – Run custom scripts before/after actions, integrate with CI/CD pipelines.

### Security & Analytics
- **Docker‑sandboxed bash** – All shell commands run isolated by default.
- **Permission system** – Granular control over file read/write, network, and tool access.
- **Code analytics** – Smell detection, trend tracking, and health reporting.

---

## 🏗️ Architecture

```
User input (CLI or Browser)
       │
       ▼
  ┌──────────────────┐      ┌──────────────────┐
  │    cli.py /       │      │  web_app.py      │
  │  cli_entry.py     │      │  (FastAPI)       │
  └────────┬─────────┘      └────────┬─────────┘
           │                         │
           └──────────┬──────────────┘
                      │
              ┌───────▼───────┐
              │   router.py    │  Prompt classification → model tier
              │ (heuristic +   │
              │  LLM fallback) │
              └───────┬───────┘
                      │
              ┌───────▼─────────┐
              │  _agent_loop.py  │  Think → Act → Verify (max N turns)
              └───────┬─────────┘
                      │
         ┌────────────┴────────────┐
         │                         │
  ┌──────▼──────┐        ┌─────────▼──────────┐
  │  api.py      │        │  tools/registry.py  │
  │ (stream SSE)│        │  40 tools + 5min TTL│
  └─────────────┘        └─────────────────────┘
```

For full details, see [ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## 🧪 Development & Testing

```bash
# Run all tests
pytest

# With coverage (target ≥97%)
pytest --cov=luckyd_code

# Type checking
mypy luckyd_code

# Lint with pre‑commit hooks
pre-commit run --all-files

# Scan for accidentally committed secrets
make secrets-scan   # requires gitleaks
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contributor guide.

---

## 🤝 Contributing

We welcome contributions! Please read the [Contributing Guide](CONTRIBUTING.md) for setup instructions, coding standards, and the PR process.

By contributing, you agree that your contributions will be licensed under AGPL v3. For alternative licensing, contact the maintainer.

---

## 📄 License

This project is licensed under the **GNU Affero General Public License v3**. See [LICENSE](LICENSE) for the full text.

---

*Built with ❤️ by [Dylan Kaye](https://github.com/Dylanchess0320).*
