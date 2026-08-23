from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.models.setting import SystemSetting
from app.models.user import User, UserRole
from app.auth.security import require_role
from app.collectors import collector_registry

router = APIRouter()


@router.get("/health")
async def system_health(session: AsyncSession = Depends(get_session)):
    from sqlalchemy import text
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    import redis.asyncio as aioredis
    from app.config import settings
    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        redis_ok = True
        await r.close()
    except Exception:
        redis_ok = False

    return {
        "status": "ok" if (db_ok and redis_ok) else "degraded",
        "database": db_ok,
        "redis": redis_ok,
    }


@router.get("/collectors")
async def list_collectors(user: User = Depends(require_role(UserRole.admin))):
    return {"collectors": collector_registry.list_all()}


@router.get("/settings")
async def get_settings(user: User = Depends(require_role(UserRole.admin))):
    from app.config import settings
    return {
        "retention_raw_days": settings.retention_raw_days,
        "compress_after_days": settings.compress_after_days,
        "collector_concurrency": settings.collector_concurrency,
        "collector_timeout": settings.collector_timeout,
    }


class AISettingsUpdate(BaseModel):
    api_base: str = ""
    api_key: str = ""
    model: str = ""


@router.get("/ai-settings")
async def get_ai_settings(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    result = await session.execute(
        select(SystemSetting).where(SystemSetting.key.like("ai_%"))
    )
    settings_map = {s.key: s.value for s in result.scalars().all()}
    return {
        "api_base": settings_map.get("ai_api_base", ""),
        "api_key": settings_map.get("ai_api_key", ""),
        "model": settings_map.get("ai_model", ""),
    }


@router.put("/ai-settings")
async def update_ai_settings(
    req: AISettingsUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    pairs = [
        ("ai_api_base", req.api_base),
        ("ai_api_key", req.api_key),
        ("ai_model", req.model),
    ]
    for key, value in pairs:
        result = await session.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = value
        else:
            session.add(SystemSetting(key=key, value=value))
    await session.commit()
    return {"status": "ok"}
