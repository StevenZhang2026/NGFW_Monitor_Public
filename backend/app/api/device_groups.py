from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.models.device import Device
from app.models.device_group import DeviceGroup
from app.models.user import User, UserRole
from app.auth.security import get_current_user, require_role

router = APIRouter()


class GroupCreate(BaseModel):
    name: str
    description: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


@router.get("")
async def list_groups(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(
            DeviceGroup,
            func.count(Device.id).label("device_count"),
        )
        .outerjoin(Device, Device.group_id == DeviceGroup.id)
        .group_by(DeviceGroup.id)
        .order_by(DeviceGroup.name)
    )
    rows = result.all()
    return {
        "items": [
            {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "device_count": count,
                "created_at": group.created_at.isoformat() if group.created_at else None,
            }
            for group, count in rows
        ]
    }


@router.post("", status_code=201)
async def create_group(
    req: GroupCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    existing = await session.execute(
        select(DeviceGroup).where(DeviceGroup.name == req.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="分组名称已存在")

    group = DeviceGroup(name=req.name, description=req.description)
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return {"id": group.id, "name": group.name, "description": group.description}


@router.put("/{group_id}")
async def update_group(
    group_id: str,
    req: GroupUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    result = await session.execute(select(DeviceGroup).where(DeviceGroup.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="分组不存在")

    if req.name is not None:
        group.name = req.name
    if req.description is not None:
        group.description = req.description

    await session.commit()
    await session.refresh(group)
    return {"id": group.id, "name": group.name, "description": group.description}


@router.delete("/{group_id}", status_code=204)
async def delete_group(
    group_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    result = await session.execute(select(DeviceGroup).where(DeviceGroup.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="分组不存在")

    await session.execute(
        Device.__table__.update().where(Device.group_id == group_id).values(group_id=None)
    )
    await session.delete(group)
    await session.commit()
