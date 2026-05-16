"""Miscellaneous routes: clear, undo, compact, context info."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..memory import MemoryManager
from ..undo import undo_last

router = APIRouter()


@router.post("/api/clear")
async def clear_context(request: Request):
    try:
        state = request.app.state.web_state
        context = state.context
        memory_module = state.memory_module
        context.reset()
        # Re-inject merged memory block
        mgr = MemoryManager()
        md = memory_module.load_claude_md()
        session_memories = mgr.get_all_memories_formatted()
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
        return {"status": "cleared"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/undo")
async def undo():
    try:
        result = undo_last()
        return {"status": result}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/compact")
async def compact(request: Request):
    try:
        state = request.app.state.web_state
        result = state.context.compact(state.config, state.config.model)
        return {"status": result}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/context")
async def context_info(request: Request):
    try:
        context = request.app.state.web_state.context
        return {
            "message_count": context.count_messages(),
            "max_messages": context.max_messages,
            "estimated_tokens": context.estimate_tokens(),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
