"""
Planning API Rate Limit - 限流端点

限流状态查询和重置。
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from backend.services.rate_limiter import rate_limiter, RateLimiter

logger = logging.getLogger(__name__)
router = APIRouter()


def get_rate_limiter() -> RateLimiter:
    return rate_limiter


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


@router.get("/api/planning/rate-limit/status")
async def get_rate_limit_status(limiter: RateLimiterDep):
    """获取限流状态"""
    return limiter.get_status()


@router.post("/api/planning/rate-limit/reset/{project_name}")
async def reset_rate_limit(project_name: str, limiter: RateLimiterDep):
    """重置项目限流"""
    limiter.reset_project(project_name)
    return {"message": f"Rate limit reset for {project_name}"}


__all__ = ["router"]