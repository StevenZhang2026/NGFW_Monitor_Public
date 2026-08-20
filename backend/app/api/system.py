from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
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
