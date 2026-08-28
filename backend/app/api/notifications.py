from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.models.notification import NotificationChannel, ChannelType
from app.models.user import User, UserRole
from app.auth.security import get_current_user, require_role

router = APIRouter()

MASK = "***"

# 值本身就是凭据的 key。飞书/企微的 webhook URL 是 bearer 型凭据 ——
# 拿到就能往客户群里发消息 —— 所以按口令对待，不能当成主机名那样明文回显。
# 用显式片段而不是裸 "key"，否则将来加个 keyword 字段会被误判成密钥。
_SECRET_KEY_PARTS = ("password", "passwd", "secret", "token", "api_key", "apikey", "webhook_url")


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SECRET_KEY_PARTS)


def _merge_config(new_config: dict, old_config: dict) -> dict:
    """把提交上来的 config 与已存的合并。

    读接口把密钥字段回显成 `***`，前端编辑时会把它原样提交回来。直接落库会
    用掩码覆盖掉真实凭据（原本 email 的 password 就有这个问题：编辑任何字段
    都会把口令清掉）。所以掩码值意味着"保持不变"。
    """
    merged = dict(new_config)
    for key, value in new_config.items():
        if value == MASK and key in old_config:
            merged[key] = old_config[key]
    return merged


class ChannelCreate(BaseModel):
    name: str
    type: str
    config: dict
    enabled: bool = True


@router.get("/channels")
async def list_channels(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    result = await session.execute(select(NotificationChannel))
    channels = result.scalars().all()
    return {"items": [_channel_to_dict(c) for c in channels]}


@router.post("/channels", status_code=201)
async def create_channel(
    req: ChannelCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    channel = NotificationChannel(
        name=req.name,
        type=ChannelType(req.type),
        config=req.config,
        enabled=req.enabled,
    )
    session.add(channel)
    await session.commit()
    await session.refresh(channel)
    return _channel_to_dict(channel)


class ChannelUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    config: dict | None = None
    enabled: bool | None = None


@router.put("/channels/{channel_id}")
async def update_channel(
    channel_id: str,
    req: ChannelUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    result = await session.execute(select(NotificationChannel).where(NotificationChannel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    if req.name is not None:
        channel.name = req.name
    if req.type is not None:
        channel.type = ChannelType(req.type)
    if req.config is not None:
        channel.config = _merge_config(req.config, channel.config or {})
    if req.enabled is not None:
        channel.enabled = req.enabled

    await session.commit()
    await session.refresh(channel)
    return _channel_to_dict(channel)


@router.delete("/channels/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    result = await session.execute(select(NotificationChannel).where(NotificationChannel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    await session.delete(channel)
    await session.commit()


@router.post("/channels/{channel_id}/test")
async def test_channel(
    channel_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    result = await session.execute(select(NotificationChannel).where(NotificationChannel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    from app.alerts.notifiers import notifier_registry
    notifier_cls = notifier_registry.get(channel.type.value)
    if not notifier_cls:
        raise HTTPException(status_code=400, detail=f"No notifier for type: {channel.type.value}")

    notifier = notifier_cls()
    result = await notifier.test(channel.config)
    resp = {"success": result.success}
    if not result.success and result.error:
        resp["error"] = result.error
    return resp


def _channel_to_dict(c: NotificationChannel) -> dict:
    safe_config = {k: (MASK if _is_secret_key(k) else v) for k, v in c.config.items()}
    return {
        "id": c.id,
        "name": c.name,
        "type": c.type.value,
        "config": safe_config,
        "enabled": c.enabled,
    }
