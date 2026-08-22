from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.models.user import User, UserRole
from app.models.device_group import UserGroupScope, DeviceGroup
from app.auth.security import get_current_user, require_role, hash_password
from app.auth.password_policy import validate_password

router = APIRouter()


class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: str = "viewer"
    group_ids: list[str] = []


class UserUpdate(BaseModel):
    username: str | None = None
    email: str | None = None
    password: str | None = None
    role: str | None = None
    is_active: bool | None = None
    group_ids: list[str] | None = None


@router.get("")
async def list_users(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    result = await session.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()

    scope_result = await session.execute(select(UserGroupScope))
    all_scopes = scope_result.scalars().all()
    user_groups: dict[str, list[str]] = {}
    for scope in all_scopes:
        user_groups.setdefault(scope.user_id, []).append(scope.group_id)

    group_ids_all = set()
    for gids in user_groups.values():
        group_ids_all.update(gids)
    group_names = {}
    if group_ids_all:
        gr = await session.execute(select(DeviceGroup).where(DeviceGroup.id.in_(group_ids_all)))
        group_names = {g.id: g.name for g in gr.scalars().all()}

    return {
        "items": [
            _user_to_dict(u, user_groups.get(u.id, []), group_names)
            for u in users
        ]
    }


@router.post("", status_code=201)
async def create_user(
    req: UserCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    pwd_errors = validate_password(req.password, role=req.role, username=req.username)
    if pwd_errors:
        raise HTTPException(status_code=422, detail="密码强度不足: " + "; ".join(pwd_errors))

    existing = await session.execute(
        select(User).where((User.username == req.username) | (User.email == req.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="用户名或邮箱已存在")

    new_user = User(
        username=req.username,
        email=req.email,
        hashed_password=hash_password(req.password),
        role=UserRole(req.role),
    )
    session.add(new_user)
    await session.flush()

    for gid in req.group_ids:
        session.add(UserGroupScope(user_id=new_user.id, group_id=gid))

    await session.commit()
    await session.refresh(new_user)
    return _user_to_dict(new_user, req.group_ids, {})


@router.put("/{user_id}")
async def update_user(
    user_id: str,
    req: UserUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    result = await session.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    if req.username is not None:
        target.username = req.username
    if req.email is not None:
        target.email = req.email
    if req.password is not None:
        role_for_check = req.role or target.role.value
        uname_for_check = req.username or target.username
        pwd_errors = validate_password(req.password, role=role_for_check, username=uname_for_check)
        if pwd_errors:
            raise HTTPException(status_code=422, detail="密码强度不足: " + "; ".join(pwd_errors))
        target.hashed_password = hash_password(req.password)
    if req.role is not None:
        target.role = UserRole(req.role)
    if req.is_active is not None:
        target.is_active = req.is_active

    if req.group_ids is not None:
        await session.execute(
            delete(UserGroupScope).where(UserGroupScope.user_id == user_id)
        )
        for gid in req.group_ids:
            session.add(UserGroupScope(user_id=user_id, group_id=gid))

    await session.commit()
    await session.refresh(target)

    group_ids = req.group_ids if req.group_ids is not None else []
    if req.group_ids is None:
        sr = await session.execute(
            select(UserGroupScope.group_id).where(UserGroupScope.user_id == user_id)
        )
        group_ids = [r[0] for r in sr.fetchall()]

    return _user_to_dict(target, group_ids, {})


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己")

    result = await session.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    await session.delete(target)
    await session.commit()


def _user_to_dict(u: User, group_ids: list[str] = None, group_names: dict = None) -> dict:
    gids = group_ids or []
    gnames = group_names or {}
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "role": u.role.value,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "group_ids": gids,
        "group_names": [gnames.get(gid, gid) for gid in gids],
    }
