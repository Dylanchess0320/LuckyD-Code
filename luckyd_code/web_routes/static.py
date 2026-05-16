"""Static / frontend routes."""

import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse, Response

router = APIRouter()

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


@router.get("/")
async def index():
    path = TEMPLATES / "index.html"
    if path.exists():  # pragma: no cover
        return HTMLResponse(
            path.read_text(encoding="utf-8"),
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return HTMLResponse("<h1>DeepSeek Code Web UI</h1><p>Template not found.</p>")  # pragma: no cover


@router.get("/manifest.json")
async def manifest():  # pragma: no cover
    path = TEMPLATES / "manifest.json"
    if path.exists():
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
    return JSONResponse({}, status_code=404)  # pragma: no cover


@router.get("/sw.js")
async def service_worker():  # pragma: no cover
    path = TEMPLATES / "sw.js"
    if path.exists():
        return Response(path.read_bytes(), media_type="application/javascript")
    return Response(status_code=404)  # pragma: no cover


@router.get("/icon-192.png")
async def icon_192():  # pragma: no cover
    path = TEMPLATES / "icon-192.png"
    if path.exists():
        return Response(path.read_bytes(), media_type="image/png")
    return Response(status_code=404)  # pragma: no cover


@router.get("/icon-512.png")
async def icon_512():  # pragma: no cover
    path = TEMPLATES / "icon-512.png"
    if path.exists():
        return Response(path.read_bytes(), media_type="image/png")
    return Response(status_code=404)  # pragma: no cover


@router.get("/favicon.ico")
async def favicon():  # pragma: no cover
    path = TEMPLATES / "icon-192.png"
    if path.exists():
        return Response(path.read_bytes(), media_type="image/png")
    return Response(status_code=404)  # pragma: no cover
