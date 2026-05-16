"""Web UI server for LuckyD Code."""

import time
from collections import defaultdict
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

# Module-level imports so test patches to luckyd_code.web_app.X still resolve
from .config import Config
from .context import ConversationContext
from .tools import get_default_registry
from . import memory as memory_module
from .mcp.client import MCPManager
from .log import get_logger
from .web_routes import WebAppState

logger = get_logger()


def create_app(config: Optional[Config] = None) -> FastAPI:
    if config is None:
        config = Config()
        try:
            config.validate()
        except ValueError as e:
            logger.warning(f"Config validation: {e}")

    registry = get_default_registry()

    # Wire up agent tools so SubAgent and AgentHandoff work from the web UI
    from .tools.agent_tools import set_repl as _set_repl

    class _WebRepl:
        """Minimal repl-like object the agent tools need."""
        config: Config
        registry: Any

    _web_repl = _WebRepl()
    _web_repl.config = config
    _web_repl.registry = registry
    _set_repl(_web_repl)
    mcp = MCPManager()
    settings = {}
    try:
        from . import settings as cfg
        settings = cfg.load_settings()
        mcp.load_from_config(settings)
    except Exception:
        logger.warning("Failed to load MCP servers", exc_info=True)
    context = ConversationContext(config.system_prompt, max_messages=100)

    # Load project memory (MEMORY.md) merged with session memories for a single memory block
    from .memory import MemoryManager
    web_memory_mgr = MemoryManager()
    md = memory_module.load_claude_md()
    session_memories = web_memory_mgr.get_all_memories_formatted()
    if md and session_memories:
        merged = md + "\n\n" + session_memories
    elif session_memories:
        merged = session_memories
    else:
        merged = md or ""

    if merged:
        context.messages.insert(1, {
            "role": "user",
            "content": f"<claude-md>{merged}</claude-md>",
        })

    # Smart project indexing
    from .indexer import index_project
    project_context = index_project()
    if project_context:
        idx = 2 if md else 1
        has_context = any(
            isinstance(m.get("content"), str) and m["content"].startswith("<project-context>")
            for m in context.messages
        )
        if not has_context:
            context.messages.insert(idx, {
                "role": "user",
                "content": f"<project-context>\n{project_context}\n</project-context>",
            })
            logger.info(f"Project indexed ({project_context.count(chr(10)) + 1} items)")

    app = FastAPI(title="LuckyD Code")

    # --- Auth middleware ---
    web_token = settings.get("web_token", "")
    if web_token:  # pragma: no cover
        @app.middleware("http")
        async def auth_middleware(request: Request, call_next):  # pragma: no cover
            if request.url.path in ("/", "/manifest.json", "/sw.js",
                                    "/icon-192.png", "/icon-512.png"):
                return await call_next(request)
            auth = request.headers.get("authorization", "")
            if auth != f"Bearer {web_token}":
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            return await call_next(request)

    # --- Rate limiting middleware (token bucket, per-IP) ---
    rate_limit_buckets: dict = defaultdict(lambda: {"tokens": 60, "last": time.time()})
    RATE_LIMIT_RATE = 60
    RATE_LIMIT_WINDOW = 60.0

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        if request.url.path in ("/", "/manifest.json", "/sw.js",
                                "/icon-192.png", "/icon-512.png"):
            return await call_next(request)
        ip = request.client.host if request.client else "unknown"
        bucket = rate_limit_buckets[ip]
        now = time.time()
        elapsed = now - bucket["last"]
        bucket["last"] = now
        bucket["tokens"] = min(bucket["tokens"] + elapsed * (RATE_LIMIT_RATE / RATE_LIMIT_WINDOW), RATE_LIMIT_RATE)
        if bucket["tokens"] < 1:
            return JSONResponse({"error": "Rate limit exceeded"}, status_code=429)
        bucket["tokens"] -= 1
        return await call_next(request)

    # --- Attach shared state ---
    app.state.web_state = WebAppState(
        config=config,
        context=context,
        registry=registry,
        mcp=mcp,
        web_memory_mgr=web_memory_mgr,
        settings=settings,
        rate_limit_buckets=rate_limit_buckets,
        memory_module=memory_module,
    )

    # --- Register routers ---
    from .web_routes import static, files, brain, sessions, settings as settings_routes
    from .web_routes import memories, project, review, background, cost, update, misc, ws

    app.include_router(static.router)
    app.include_router(files.router)
    app.include_router(brain.router)
    app.include_router(sessions.router)
    app.include_router(settings_routes.router)
    app.include_router(memories.router)
    app.include_router(project.router)
    app.include_router(review.router)
    app.include_router(background.router)
    app.include_router(cost.router)
    app.include_router(update.router)
    app.include_router(misc.router)
    app.include_router(ws.router)

    return app


_app_instance = None


def get_app() -> FastAPI:
    """Lazy-init the app instance. create_app() runs only on first call."""
    global _app_instance
    if _app_instance is None:
        _app_instance = create_app()
    return _app_instance


def run_web(host: str = "127.0.0.1", port: int = 8000):  # pragma: no cover
    """Run the web UI server.

    Defaults to localhost only (127.0.0.1) for security.
    Pass host='0.0.0.0' explicitly to expose on the local network.
    """
    import sys
    if sys.version_info >= (3, 15):
        # Python 3.15+: uvicorn's asyncio_run wrapper is incompatible
        # with the beta's patched asyncio. Bypass it and serve directly.
        import asyncio
        config = uvicorn.Config(get_app(), host=host, port=port)
        server = uvicorn.Server(config)
        asyncio.run(server.serve())
    else:
        uvicorn.run(get_app(), host=host, port=port)
