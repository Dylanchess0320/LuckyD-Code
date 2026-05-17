"""Code review and security review routes."""

from typing import Any

from fastapi import APIRouter

from ..skills import review as review_skill
from ..skills import security as security_skill

router = APIRouter()


@router.get("/api/review")
async def review_code() -> Any:
    diff = review_skill.review_changes()
    return {"diff": diff}


@router.get("/api/security-review")
async def security_review() -> Any:
    analysis = security_skill.security_review()
    return {"analysis": analysis}
