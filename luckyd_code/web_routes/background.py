"""Background agent task routes."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..log import get_logger

logger = get_logger()
router = APIRouter()


class BackgroundStart(BaseModel):
    task: str


@router.get("/api/background")
async def background_list(request: Request):
    try:
        from ..background import BackgroundAgent
        state = request.app.state.web_state
        bg = BackgroundAgent(state.config)
        bg.load_history()
        statuses = bg.get_status()
        return {"tasks": statuses}
    except Exception as e:
        logger.warning(f"background_list error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/background/start")
async def background_start(request: Request, data: BackgroundStart):
    try:
        from ..background import BackgroundAgent
        state = request.app.state.web_state
        task = data.task or ""
        if not task:
            return JSONResponse({"error": "task description required"}, status_code=400)
        bg = BackgroundAgent(state.config)
        task_id = bg.start_task(task)
        return {"task_id": task_id, "status": "started"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/background/status/{task_id}")
async def background_status(request: Request, task_id: str):
    try:
        from ..background import BackgroundAgent
        state = request.app.state.web_state
        bg = BackgroundAgent(state.config)
        bg.load_history()
        statuses = bg.get_status(task_id)
        if statuses:
            return {"task": statuses[0]}
        return JSONResponse({"error": "Task not found"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/background/result/{task_id}")
async def background_result(request: Request, task_id: str):
    try:
        from ..background import BackgroundAgent
        state = request.app.state.web_state
        bg = BackgroundAgent(state.config)
        bg.load_history()
        result = bg.get_result(task_id)
        if result:
            return {"result": result}
        return JSONResponse({"error": "Result not available"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
