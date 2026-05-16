<p align="center">
  <img src="https://raw.githubusercontent.com/Dylanchess0320/LuckyD-Code/main/docs/luckyd-logo.png?v=2" alt="LuckyD Code Logo" width="128">
</p>

<p align="center">
  <b>The AI coding assistant that thinks before it ships.</b><br>
  Terminal-native · Browser-ready · DeepSeek-powered
</p>

<p align="center">
  <a href="https://github.com/Dylanchess0320/LuckyD-Code/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Dylanchess0320/LuckyD-Code/ci.yml?style=flat-square&label=CI&logo=github" alt="CI"></a>
  <a href="https://pypi.org/project/luckyd-code/"><img src="https://img.shields.io/pypi/v/luckyd-code?style=flat-square&logo=pypi&label=PyPI&color=3775A9" alt="PyPI"></a>
  <a href="https://pypi.org/project/luckyd-code/"><img src="https://img.shields.io/pypi/pyversions/luckyd-code?style=flat-square&logo=python&label=Python&color=3776AB" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square&logo=opensourceinitiative" alt="License"></a>
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

### 📋 Prerequisites

- **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/) or `brew install python@3.12`
- **Rust** (only if pip can't find a pre-built wheel for your platform, e.g. old macOS versions) — `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`

> 💡 `tiktoken` (the tokenizer library) is Rust-based. Pre-built wheels are available for macOS (Intel + Apple Silicon), Linux x86_64, and Windows. If you see a Rust compiler error during `pip install`, that means no wheel matched your platform — install Rust and retry.

### ⚡ One-click launchers

| OS | Script |
|---|---|
| **Windows** | Double-click `installers/Install and Run - Windows.bat` |
| **Windows (Web UI)** | Double-click `installers/Install and Run Web UI - Windows.bat` |
| **macOS** | Double-click `installers/Install and Run - Mac.command` |
| **Linux** | `chmod +x "installers/Install and Run - Linux.sh" && "./installers/Install and Run - Linux.sh"` |

The launcher creates a virtual environment, installs dependencies, prompts for your API key, and starts the assistant — **no terminal knowledge required**.

### 📦 Install via pip

```bash
pip install luckyd-code
```

### 🏗️ From source

```bash
git clone https://github.com/Dylanchess0320/LuckyD-Code
cd LuckyD-Code
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

> ⚠️ If `pip install` fails with a Rust error, install Rust first:
> `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`
> Then open a new terminal and retry.

### 🔑 Get your API key

1. Visit [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys)
2. Create a key (free credits available)
3. Set it in `.env`:
   ```bash
   DEEPSEEK_API_KEY=sk-your-key-here
   ```

---

## 🖥️ Usage

```bash
# Start the CLI
luckyd-code
# or the short alias
ldc

# Start the Web UI
luckyd-code --web
# → Open http://localhost:8000

# Pick a model
luckyd-code --model deepseek-v4-pro

# Custom port
luckyd-code --web --port 9090
```

### ⌨️ CLI slash commands

| Command | Action |
|---|---|
| `/help` | Show all commands |
| `/clear` | Reset the conversation |
| `/compact` | Summarize and compress context |
| `/undo` | Revert the last file change |
| `/model [name]` | Switch models |
| `/cost` | View token usage and spending |
| `/memory [query]` | Search saved memories |
| `/brain [query]` | Search the codebase knowledge graph |
| `/export [format]` | Export conversation to Markdown or HTML |
| `/sessions` | Save, load, or list sessions |
| `/review [file]` | Code review a file |
| `/orchestrate [goal]` | Run the multi-agent pipeline |
| `/background [task]` | Start a background agent |

---

## 🧠 Smart Model Routing

LuckyD Code automatically classifies your prompt and routes it to the right model — optimizing for speed, cost, or reasoning depth.

| Tier | Model | Best For |
|:----:|-------|----------|
| **T1** | DeepSeek V4 Flash | Simple chat, quick Q&A, trivial edits |
| **T2** | DeepSeek V4 Flash | General coding, file ops, search |
| **T3** | DeepSeek V4 Pro | Debugging, architecture, complex analysis |
| **T4** | DeepSeek V4 Pro | Large refactors, code generation, reviews |

- **Heuristic classifier** returns in microseconds for known patterns
- **LLM classifier** runs in the background for ambiguous prompts (4 s timeout)
- **Mid-loop escalation** — if T1/T2 produces repeated errors, the loop auto-promotes to a higher tier
- **Cost-aware** — T1 runs at **$0.00014/1K input tokens** (80× cheaper than GPT-4)

---

## 📊 Codebase Analytics

Built-in health scanning that runs on demand — no external service needed.

| Feature | Description |
|---|---|
| 🧪 **Health Score** | 0–100 score based on complexity, duplication, and structure |
| 👃 **Smell Detection** | Identifies 12 code smells including deep nesting, god functions, magic numbers |
| 📈 **Trend Tracking** | Snapshots your project over time; compare any two points |
| 📋 **Report Export** | Terminal output, Markdown, JSON, or HTML reports |

```bash
# In-session commands
/brain scan              # Scan and index current project
/brain stats             # View knowledge graph statistics
```

---

## 🕸️ Web UI

Launch with `luckyd-code --web` and open `http://localhost:8000`.

| Panel | What You Can Do |
|---|---|
| 💬 **Chat** | Full conversational interface with streaming responses |
| 💰 **Cost** | Real-time token and cost dashboard |
| 🧠 **Memory** | Browse, search, and edit persistent memories |
| 🗺️ **Brain** | Explore the knowledge graph; run codebase searches |
| 📁 **Files** | Browse project files with syntax highlighting |
| 🔍 **Review** | Request automated code reviews |
| ⚙️ **Settings** | Configure models, keys, and defaults from the browser |
| 📡 **WebSocket** | Live streaming chat with bidirectional updates |

The Web UI uses the same engine as the CLI — everything syncs.

---

## 🧰 Tools Gallery

LuckyD Code ships with **40 built-in tools**, organized by category:

### 📁 File Operations
`Read` · `Write` · `Edit` · `Glob` · `Grep`

> Write and Edit support `dry_run=true` for safe diff previews. All writes are auto-verified after execution.

### 🐚 Shell & Environment
`Bash` · `DateTime` · `ShellDetect`

> Bash runs are sandboxed via Docker. Shell auto-detection picks the right shell on Windows (Git Bash → WSL → cmd).

### 🌐 Web & Browser
`WebFetch` · `WebSearch` · `BrowserNavigate` · `BrowserClick` · `BrowserType` · `BrowserSnapshot` · `BrowserScreenshot`

> Browser tools use Playwright for full-page automation and testing.

### 🔀 Git & Version Control
`GitStatus` · `GitDiff` · `GitLog` · `GitCommit` · `GitAdd` · `GitBranch` · `GitPush` · `GitPR` · `GitWorktree`

> Automated PR creation, worktree isolation for safe fix application.

### 🧠 Brain & Knowledge Graph
`BrainSearch` · `BrainStatus`

> Semantic vector search across your codebase with keyword fallback.

### 🤖 Agent & Orchestration
`SubAgent` · `AgentHandoff`

> Spawn independent sub-agents or hand off to researcher, coder, or reviewer specialists.

### 🎮 Generators
`GameGen` · `ProjectGen` · `ReadmeGen` · `DockerfileGen`

> Generate complete Pygame games, project scaffolds, READMEs, or Docker configurations from plain-English descriptions.

### 🎬 Media & Misc
`YouTubePlaylist` · `OpenInBrowser`

---

## 🏗️ Architecture

```
luckyd_code/
│
├── 🖥️  cli.py              Terminal UI (Rich + prompt_toolkit)
├── 🕸️  web_app.py          FastAPI server + WebSocket streaming
├── 🔄  _agent_loop.py      Shared agent loop (CLI + sub-agents + handoffs)
│
├── 🧠  brain/              Knowledge Graph & Semantic Search
│    ├── graph.py            Vector index + dependency tracking
│    ├── embedder.py         Sentence transformer embeddings
│    ├── chunker.py          Smart code chunking (AST-aware + fallback)
│    ├── indexer.py          Full-project scanner & indexer
│    └── retriever.py        Semantic + keyword search
│
├── 🛠️  tools/               Tool Registry (40 tools)
│    ├── registry.py          Cached tool registry (5 min TTL)
│    ├── file_ops.py          Read/Write/Edit/Glob/Grep
│    ├── bash.py              Sandboxed shell execution
│    ├── git_tools.py         Git operations
│    ├── browser.py           Playwright browser automation
│    ├── agent_tools.py       Sub-agents & handoffs
│    └── ...                  Generators, YouTube, Web tools
│
├── 🤖  orchestrator.py     Multi-agent pipeline (Researcher → Coder → Reviewer)
├── 🔀  router.py            Model tier classifier (heuristic + LLM)
├── 📋  model_registry.py    Model definitions with costs & capabilities
│
├── 💾  memory/             Persistent Memory System
├── 📊  analytics/          Code Health · Smells · Trends · Reports
├── 🔗  mcp/                Model Context Protocol client
├── 🔒  permissions/         Permission management
├── 🪝  hooks.py            Lifecycle hook system (pre/post tool, pre/post chat)
├── 🔧  autonomous_fixer.py Diagnose → patch → validate → PR pipeline
├── 🔄  self_improve.py     Automated code improvement engine
├── 📡  audit_daemon.py     Background audit and monitoring
│
├── 📁  sessions.py         Conversation save/load
├── ↩️  undo.py             Revert file changes
├── 📤  export.py           Export to Markdown or HTML
├── 🎨  themes.py           CLI color themes
├── ⌨️  keybindings.py      Custom keybindings
├── 🔌  plugins.py          Runtime plugin loader
├── ⚙️  config.py           Configuration management
├── 📈  cost_tracker.py     Per-session cost tracking (JSONL append-only)
├── 📝  context.py          Context window management with auto-compaction
└── 🔁  retry.py            Retry logic with exponential backoff
```

---

## 🔌 Plugins

LuckyD Code supports community plugins. Drop a `.py` file into `~/.luckyd-code/plugins/` and it loads automatically as a new tool.

```bash
# Scaffold a new plugin
/plugins new my_tool

# Hot-reload without restarting
/plugins reload
```

See **[docs/PLUGINS.md](docs/PLUGINS.md)** for the full guide and **[examples/plugins/](examples/plugins/)** for working examples.

---

## 📦 Optional Extras

```bash
# RAG — semantic codebase search with sentence-transformers
pip install "luckyd-code[rag]"

# Full RAG — adds FAISS vector store + file watcher for live re-indexing
pip install "luckyd-code[rag-full]"

# Browser — Playwright-powered web automation
pip install "luckyd-code[browser]"

# Dev — test suite, type checker, coverage
pip install "luckyd-code[dev]"
```

---

## 🧪 Development

```bash
# Clone & install with all dev deps
git clone https://github.com/Dylanchess0320/LuckyD-Code
cd LuckyD-Code
pip install -e ".[dev,rag-full]"

# Run the test suite
pytest

# With coverage report
pytest --cov=luckyd_code --cov-report=term-missing

# Type checking
mypy luckyd_code

# Build distribution
python -m build
```

---

## 🤝 Contributing

We welcome contributions! See **[CONTRIBUTING.md](CONTRIBUTING.md)** for the full guide.

1. 🍴 Fork the repo
2. 🌿 Create a feature branch from `main`
3. ✅ Write tests for new functionality
4. ✔️ Ensure `pytest` passes
5. 📝 Update CHANGELOG.md
6. 🚀 Submit a pull request

---

## 🔐 Security

To report a vulnerability, **do not** open a public issue. Use the **[private advisory form](https://github.com/Dylanchess0320/LuckyD-Code/security/advisories/new)** or contact the maintainer directly.

| Version | Support |
|:--------|:--------|
| 1.2.x   | ✅ Full support |
| 1.1.x   | ⚠️ Critical fixes only |
| ≤ 1.0.x | ❌ Unsupported |

See **[SECURITY.md](SECURITY.md)** for full policy.

---

## 📜 License

MIT © 2026 [Dylan Kaye](https://github.com/Dylanchess0320)

---

<p align="center">
  <sub>Built with ❤️ by <a href="https://github.com/Dylanchess0320">Dylan Kaye</a> · Powered by <a href="https://platform.deepseek.com">DeepSeek</a></sub>
</p>
