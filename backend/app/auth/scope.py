from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.device import Device
from app.models.device_group import UserGroupScope


async def get_user_group_ids(user: User, session: AsyncSession) -> list[str] | None:
    """
    Return the group IDs this user is scoped to, or None for global access.
    Empty list from DB → None (global). Non-empty → restricted.
    """
    result = await session.execute(
        select(UserGroupScope.group_id).where(UserGroupScope.user_id == user.id)
    )
    group_ids = [row[0] for row in result.fetchall()]
    return group_ids if group_ids else None


async def get_scoped_device_ids(user: User, session: AsyncSession) -> list[str] | None:
    """
    Return device IDs visible to this user, or None for global access.
    Scoped users only see devices whose group_id is in their assigned groups.
    """
    group_ids = await get_user_group_ids(user, session)
    if group_ids is None:
        return None

    result = await session.execute(
        select(Device.id).where(Device.group_id.in_(group_ids))
    )
    return [row[0] for row in result.fetchall()]


async def filter_devices_query(user: User, session: AsyncSession):
    """
    Return a Device select query filtered by user's scope.
    Global users see all devices; scoped users see only their groups' devices.
    """
    group_ids = await get_user_group_ids(user, session)
    query = select(Device)
    if group_ids is not None:
        query = query.where(Device.group_id.in_(group_ids))
    return query


async def check_device_in_scope(device_id: str, user: User, session: AsyncSession) -> bool:
    """Check if a specific device is within the user's scope."""
    scoped_ids = await get_scoped_device_ids(user, session)
    if scoped_ids is None:
        return True
    return device_id in scoped_ids
