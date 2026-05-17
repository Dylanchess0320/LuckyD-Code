"""Session management routes."""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..sessions import list_sessions, save_session, load_session, delete_session

router = APIRouter()


class SessionSave(BaseModel):
    name: str


class SessionLoad(BaseModel):
    name: str


@router.get("/api/sessions")
async def sessions_list() -> Any:
    result = list_sessions()
    return {"sessions": result}


@router.post("/api/sessions/save")
async def sessions_save(request: Request, data: SessionSave) -> Any:
    state = request.app.state.web_state
    result = save_session(data.name, state.context)
    return {"status": "ok", "message": result}


@router.post("/api/sessions/load")
async def sessions_load(request: Request, data: SessionLoad) -> Any:
    state = request.app.state.web_state
    result = load_session(data.name, state.context)
    return {"status": "ok", "message": result}


@router.delete("/api/sessions/{name}")
async def sessions_delete(name: str) -> Any:
    result = delete_session(name)
    return {"status": "ok", "message": result}
