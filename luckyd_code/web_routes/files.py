"""File browsing, reading, writing, and editing routes."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..tools import path_validate

router = APIRouter()

MAX_MESSAGE_LENGTH = 10000
MAX_READ_BYTES = 1_000_000   # 1 MB
MAX_WRITE_BYTES = 10_485_760  # 10 MB — matches CLI WriteTool


def _safe_resolve(path: str) -> Path | None:
    """Wrap safe_resolve so callers get None instead of a raw ValueError."""
    try:
        return path_validate.safe_resolve(path)
    except ValueError:
        return None


class WriteData(BaseModel):
    path: str = ""
    content: str = ""


class EditData(BaseModel):
    path: str = ""
    old_string: str = ""
    new_string: str = ""


@router.get("/api/tools")
async def list_tools(request: Request) -> Any:
    """List available tool names."""
    state = request.app.state.web_state
    tools = state.registry.list_tools()
    tool_objects = [{"name": t["function"]["name"]} for t in tools]
    return {"tools": tool_objects, "count": len(tools)}


@router.get("/api/files")
async def list_files(request: Request, dir: str = ".") -> Any:
    """List directory contents."""
    safe = _safe_resolve(dir)
    if safe is None:
        return JSONResponse({"error": "Access denied: path traversal detected"}, status_code=403)
    path = Path(safe)
    if not path.exists():
        return JSONResponse({"error": f"Directory not found: {dir}"}, status_code=404)
    if not path.is_dir():
        return JSONResponse({"error": f"Not a directory: {dir}"}, status_code=400)

    try:
        items = []
        for child in sorted(path.iterdir()):
            try:
                items.append({
                    "name": child.name,
                    "is_dir": child.is_dir(),
                    "size": child.stat().st_size if child.is_file() else 0,
                })
            except OSError:
                continue
        parent = str(path.parent) if path.parent != path else str(path)
        return {"files": items, "current": str(path), "parent": parent}
    except PermissionError:
        return JSONResponse({"error": "Permission denied"}, status_code=403)


@router.get("/api/read-file")
async def read_file(request: Request, path: str = "") -> Any:
    if not path:
        return JSONResponse({"error": "path parameter required"}, status_code=400)
    safe = _safe_resolve(path)
    if safe is None:
        return JSONResponse({"error": "Access denied: path traversal detected"}, status_code=403)
    file_path = Path(safe)
    if not file_path.exists():
        return JSONResponse({"error": f"File not found: {path}"}, status_code=404)
    if not file_path.is_file():
        return JSONResponse({"error": f"Not a file: {path}"}, status_code=400)
    try:
        # Check size via stat before reading into memory
        if file_path.stat().st_size > MAX_READ_BYTES:
            return JSONResponse({"error": "File too large (max 1 MB)"}, status_code=413)
        content = file_path.read_text(encoding="utf-8")
        return {"content": content, "path": str(file_path), "size": len(content)}
    except Exception as e:
        return JSONResponse({"error": f"Failed to read file: {e}"}, status_code=500)


@router.post("/api/write-file")
async def write_file(request: Request, data: WriteData) -> Any:
    if not data.path:
        return JSONResponse({"error": "path required"}, status_code=400)
    if len(data.content) > MAX_WRITE_BYTES:
        return JSONResponse({"error": "Content too large (max 10 MB)"}, status_code=413)
    safe = _safe_resolve(data.path)
    if safe is None:
        return JSONResponse({"error": "Access denied: path traversal detected"}, status_code=403)
    file_path = Path(safe)
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(data.content, encoding="utf-8")
        return {"status": "written", "path": str(file_path), "size": len(data.content)}
    except Exception as e:
        return JSONResponse({"error": f"Failed to write file: {e}"}, status_code=500)


@router.post("/api/edit-file")
async def edit_file(request: Request, data: EditData) -> Any:
    if not data.path or not data.old_string:
        return JSONResponse({"error": "path and old_string required"}, status_code=400)
    safe = _safe_resolve(data.path)
    if safe is None:
        return JSONResponse({"error": "Access denied: path traversal detected"}, status_code=403)
    file_path = Path(safe)
    if not file_path.exists():
        return JSONResponse({"error": f"File not found: {data.path}"}, status_code=404)
    try:
        content = file_path.read_text(encoding="utf-8")
        if data.old_string not in content:
            return JSONResponse({"error": "old_string not found in file", "content": content}, status_code=400)
        new_content = content.replace(data.old_string, data.new_string, 1)
        file_path.write_text(new_content, encoding="utf-8")
        return {"status": "edited", "path": str(file_path), "replacements": 1}
    except Exception as e:
        return JSONResponse({"error": f"Failed to edit file: {e}"}, status_code=500)
