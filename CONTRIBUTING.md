# Contributing

Thanks for your interest in LuckyD Code!

## Development Setup

```bash
# Clone the repo
git clone https://github.com/Dylanchess0320/LuckyD-Code
cd LuckyD-Code

# Create virtual environment
python -m venv .venv

# Activate it
# Windows: .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Install optional RAG dependencies
pip install -e ".[rag-full]"
```

## Running Tests

```bash
# Run all tests
pytest

# With coverage
pytest --cov=luckyd_code

# Specific test file
pytest tests/test_router.py -v
```

## Type Checking

```bash
mypy luckyd_code
```

## Code Style

- Target Python 3.10+
- Follow PEP 8
- Use type hints for all function signatures
- Write docstrings for public APIs
- Keep functions focused and small

## Pull Request Process

1. Create a feature branch from `main`
2. Write tests for new functionality
3. Ensure all existing tests pass
4. Update documentation (README, CHANGELOG) as needed
5. Submit the PR with a clear description

## Project Structure

```
luckyd_code/
├── cli.py               # Terminal UI and REPL
├── cli_commands/        # Slash-command handlers
├── web_app.py           # Web UI server (FastAPI)
├── web_routes/          # Web UI route handlers
├── api.py               # API streaming client
├── router.py            # Model routing
├── config.py            # Configuration
├── context.py           # Conversation context
├── cost_tracker.py      # Cost tracking
├── hooks.py             # Lifecycle hooks
├── model_registry.py    # Model definitions
├── memory/              # Persistent memory
├── brain/               # Knowledge graph & RAG
├── tools/               # Tool registry (40 tools)
├── mcp/                 # MCP client
├── permissions/         # Permission system
├── skills/              # Review & security
├── analytics/           # Usage analytics
├── templates/           # Web UI assets
└── background/          # Background agents
```

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
