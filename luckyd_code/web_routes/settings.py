"""Settings and model configuration routes."""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .. import settings as cfg

router = APIRouter()


@router.get("/api/settings")
async def get_settings(request: Request) -> Any:
    return cfg.load_settings()


class SettingUpdate(BaseModel):
    key: str
    value: str


@router.post("/api/settings")
async def set_settings(data: SettingUpdate) -> Any:
    cfg.save_setting(data.key, data.value)
    return {"status": "ok", "key": data.key, "value": data.value}


@router.get("/api/models")
async def list_models() -> Any:
    from ..model_registry import format_model_list, get_unique_model_count
    return {"models": format_model_list(), "count": get_unique_model_count()}


class ModelSet(BaseModel):
    model: str


@router.post("/api/models/set")
async def set_model(data: ModelSet) -> Any:
    from ..config import Config
    c = Config()
    c.model = data.model
    c.save()
    return {"status": "ok", "model": data.model}
