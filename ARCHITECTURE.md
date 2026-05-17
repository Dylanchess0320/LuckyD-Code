# LuckyD Code — Module Architecture

> For the full narrative walkthrough see **[docs/architecture.md](docs/architecture.md)**.

---

## Module dependency diagram

```mermaid
graph TD
    subgraph Entry["Entry points"]
        CLI["cli.py\ncli_entry.py"]
        WEB["web_app.py\nweb_routes/"]
    end

    subgraph Routing["Routing"]
        ROUTER["router.py\n(heuristic + LLM tier)"]
        MODEL["model_registry.py"]
    end

    subgraph Core["Core loop"]
        LOOP["_agent_loop.py\n(Think → Act → Verify)"]
        API["api.py\n(stream_chat SSE)"]
        CTX["context.py\n(token budget)"]
    end

    subgraph Tools["Tools (40)"]
        TREG["tools/registry.py\n(5-min TTL cache)"]
        FOPS["tools/file_ops.py\n(Read/Write/Edit/Glob/Grep)"]
        BASH["tools/bash.py\n(Docker sandbox)"]
        GIT["tools/git_tools.py"]
        BROWSER["tools/browser.py\n(Playwright)"]
        AGEN["tools/agent_tools.py\n(SubAgent/Handoff)"]
        GEN["tools/generators.py\n(Game/Project/Readme/Docker)"]
        WEBT["tools/web.py\n(Fetch/Search)"]
    end

    subgraph Verify["Verification"]
        VER["verify.py\n(syntax→lint→AST→test)"]
    end

    subgraph Brain["Brain / RAG"]
        BRAIN["brain/graph.py\n(knowledge graph)"]
        IDX["brain/indexer.py\n(FAISS)"]
        RETR["brain/retriever.py\n(RRF merge)"]
        EMB["brain/embedder.py\n(sentence-transformers)"]
    end

    subgraph Memory["Memory"]
        PMEM["memory/manager.py\n(project)"]
        UMEM["memory/user.py\n(cross-project)"]
    end

    subgraph Analytics["Analytics"]
        SCAN["analytics/scanner.py"]
        TREND["analytics/trends.py"]
        REP["analytics/reporter.py"]
    end

    subgraph Autonomous["Self-repair"]
        FIXER["autonomous_fixer.py"]
        FANL["feedback_analyzer.py"]
        SIMP["self_improve.py"]
    end

    subgraph Support["Support modules"]
        HOOKS["hooks.py"]
        PLAN["planner.py\nplan_gate.py"]
        ORCH["orchestrator.py"]
        SESS["sessions.py"]
        COST["cost_tracker.py"]
        UNDO["undo.py"]
        RETRY["retry.py"]
        CONF["config.py"]
        PLUG["plugins.py"]
    end

    CLI --> ROUTER
    WEB --> ROUTER
    ROUTER --> MODEL
    ROUTER --> LOOP
    LOOP --> API
    LOOP --> CTX
    LOOP --> TREG
    LOOP --> VER
    LOOP --> PMEM
    LOOP --> UMEM
    TREG --> FOPS
    TREG --> BASH
    TREG --> GIT
    TREG --> BROWSER
    TREG --> AGEN
    TREG --> GEN
    TREG --> WEBT
    TREG --> BRAIN
    AGEN --> LOOP
    ORCH --> LOOP
    FIXER --> FANL
    FIXER --> VER
    BRAIN --> IDX
    BRAIN --> RETR
    RETR --> EMB
    SCAN --> TREND
    SCAN --> REP
    CLI --> HOOKS
    CLI --> SESS
    CLI --> COST
    CLI --> UNDO
    CLI --> PLUG
    CLI --> PLAN
    CLI --> ORCH
```

---

## Layer summary

| Layer | Modules | Role |
|-------|---------|------|
| **Entry** | `cli.py`, `web_app.py`, `web_routes/` | User-facing surfaces — terminal and browser |
| **Routing** | `router.py`, `model_registry.py` | Classify prompt complexity → select model tier |
| **Core loop** | `_agent_loop.py`, `api.py`, `context.py` | Think → Act → Verify agentic harness |
| **Tools** | `tools/` (40 tools, cached registry) | File ops, shell, git, web, browser, generators |
| **Verification** | `verify.py` | Post-write syntax + lint + AST + test gate |
| **Brain / RAG** | `brain/` | Knowledge graph + vector search + BM25 |
| **Memory** | `memory/` | Project and cross-project persistent memory |
| **Analytics** | `analytics/` | Code health, smell detection, trend tracking |
| **Self-repair** | `autonomous_fixer.py`, `feedback_analyzer.py` | Diagnose → patch → validate → PR |
| **Support** | `hooks.py`, `planner.py`, `sessions.py`, etc. | Lifecycle hooks, planning, sessions, cost |

---

## Key design decisions

**Single shared agent loop** — `cli.py`, `web_app.py`, `SubAgent`, and `AgentHandoff` all call the same `run_agent_loop()` in `_agent_loop.py`. Bug fixes and improvements propagate to every agentic path automatically.

**Parallel read / sequential write** — The tool executor runs read-only tools (`Read`, `Glob`, `Grep`, …) concurrently in a `ThreadPoolExecutor` (up to 4 workers). Write-conflict tools (`Write`, `Edit`, `Bash`, `GitCommit`, …) always run sequentially to prevent race conditions.

**Stuck-loop detection** — Each tool-call batch is hashed. If the same hash appears 3 times in a row the loop breaks and asks the model to explain what is blocking it, preventing infinite tool cycles.

**Mid-loop model escalation** — If the verification pipeline keeps failing, the loop promotes to the next model tier (`deepseek-v4-flash` → `deepseek-v4-pro`) for recovery turns, then returns to the original tier.

**Git worktree isolation** — The autonomous fixer applies diffs in a `git worktree add` temporary directory. The user's working copy is never touched.
