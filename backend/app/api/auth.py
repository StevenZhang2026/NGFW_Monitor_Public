from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.models.user import User
from app.auth.security import (
    verify_password,
    hash_password,
    create_access_token,
    create_refresh_token,
    get_current_user,
)
from app.auth.password_policy import validate_password

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    from app.config import settings
    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value),
        refresh_token=create_refresh_token(user.id),
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.get("/me")
async def get_me(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    from app.models.device_group import UserGroupScope
    result = await session.execute(
        select(UserGroupScope.group_id).where(UserGroupScope.user_id == user.id)
    )
    group_ids = [row[0] for row in result.fetchall()]
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role.value,
        "group_ids": group_ids,
    }


class PasswordCheckRequest(BaseModel):
    password: str
    role: str = "viewer"
    username: str = ""


@router.post("/password-check")
async def check_password_strength(req: PasswordCheckRequest):
    """Check password strength without creating/updating a user."""
    from app.auth.password_policy import password_strength_score
    errors = validate_password(req.password, role=req.role, username=req.username)
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "score": password_strength_score(req.password),
    }


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.put("/password")
async def change_password(
    req: ChangePasswordRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not verify_password(req.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="当前密码不正确")

    pwd_errors = validate_password(req.new_password, role=user.role.value, username=user.username)
    if pwd_errors:
        raise HTTPException(status_code=422, detail="密码强度不足: " + "; ".join(pwd_errors))

    user.hashed_password = hash_password(req.new_password)
    await session.commit()
    return {"message": "密码已修改"}
