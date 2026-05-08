"""Project initialization, indexing, tasks, and plans routes."""

from fastapi import APIRouter, Request

from .. import tasks, planner, init as project_init

router = APIRouter()


@router.post("/api/init")
async def init_project():
    result = project_init.init_project()
    return {"status": "ok", "message": result}


@router.post("/api/index")
async def reindex_project(request: Request):
    from ..indexer import index_project
    project_context = index_project()
    state = request.app.state.web_state
    if project_context and state.context:
        new_content = f"<project-context>\n{project_context}\n</project-context>"
        replaced = False
        for i, m in enumerate(state.context.messages):
            content = str(m.get("content", ""))
            if content.startswith("<project-context>") and content.endswith("</project-context>"):
                state.context.messages[i]["content"] = new_content
                replaced = True
                break
        if not replaced:
            state.context.messages.insert(1, {
                "role": "user",
                "content": new_content,
            })
        return {"status": "ok", "items": project_context.count("\n") + 1}
    return {"status": "ok", "items": 0}


@router.get("/api/tasks")
async def list_tasks(status: str = ""):
    result = tasks.list_tasks(status or None)
    return {"tasks": result}


@router.get("/api/plans")
async def list_plans():
    plans = planner.list_plans()
    return {"plans": plans}
