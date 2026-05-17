"""Memory (MEMORY.md and named memories) routes."""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..web_app import memory_module

router = APIRouter()


# --- Project Memory (MEMORY.md) ---

@router.get("/api/memory")
async def get_memory(request: Request) -> Any:
    state = request.app.state.web_state
    md = memory_module.load_claude_md()
    return {"claude_md": md, "message_count": state.context.count_messages()}


class MemorySave(BaseModel):
    content: str = ""


@router.post("/api/memory/save")
async def save_memory(request: Request, data: MemorySave) -> Any:
    memory_module.save_claude_md(data.content)
    # Update context so the change is reflected immediately.
    # The <claude-md> block may also contain session memories — preserve them.
    state = request.app.state.web_state
    session_suffix = ""
    for m in state.context.messages:
        if isinstance(m.get("content"), str) and m["content"].startswith("<claude-md>"):
            inner = m["content"][len("<claude-md>"):-len("</claude-md>")]
            if "<memories>" in inner:
                session_suffix = "\n\n" + inner[inner.index("<memories>"):]
            break
    merged = data.content + session_suffix
    for i, m in enumerate(state.context.messages):
        if isinstance(m.get("content"), str) and m["content"].startswith("<claude-md>"):
            state.context.messages[i]["content"] = f"<claude-md>{merged}</claude-md>"
            break
    else:
        state.context.messages.insert(1, {
            "role": "user",
            "content": f"<claude-md>{merged}</claude-md>",
        })
    return {"status": "saved"}


# --- Named memories ---

@router.get("/api/memories")
async def list_memories(request: Request, q: str = "") -> Any:
    state = request.app.state.web_state
    mgr = state.web_memory_mgr
    if q:
        results = mgr.search_memories(q)
        return {"memories": results}
    all_memories = mgr.list_memories()
    return {"memories": all_memories}


class NamedMemorySave(BaseModel):
    name: str
    content: str


@router.post("/api/memories/save")
async def save_memory_web(request: Request, data: NamedMemorySave) -> Any:
    state = request.app.state.web_state
    mgr = state.web_memory_mgr
    mgr.save_memory(data.name, data.content)
    return {"status": "ok", "name": data.name}


@router.delete("/api/memories/{name}")
async def delete_memory_web(request: Request, name: str) -> Any:
    state = request.app.state.web_state
    mgr = state.web_memory_mgr
    ok = mgr.delete_memory(name)
    if ok:
        return {"status": "ok", "name": name}
    return JSONResponse({"error": "Memory not found"}, status_code=404)


@router.get("/api/memories/{name}")
async def get_memory_web(request: Request, name: str) -> Any:
    state = request.app.state.web_state
    mgr = state.web_memory_mgr
    content = mgr.load_memory(name)
    if content:
        return {"name": name, "content": content}
    return JSONResponse({"error": "Memory not found"}, status_code=404)
