"""Update check and self-update routes."""

from fastapi import APIRouter

from .. import update as updater

router = APIRouter()


@router.get("/api/update/check")
async def check_updates():
    result = updater.get_version()
    return {"version": result, "update_available": False}


@router.post("/api/update")
async def do_update():
    result = updater.do_update()
    return {"status": "ok", "message": result}
