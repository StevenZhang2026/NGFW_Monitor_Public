from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.models.device import Device, AuthType
from app.models.user import User, UserRole
from app.auth.security import get_current_user, require_role

router = APIRouter()


class DeviceCreate(BaseModel):
    name: str
    hostname: str
    ssh_username: str
    ssh_password: str
    ssh_port: int = 22
    collect_enabled: bool = True


class DeviceUpdate(BaseModel):
    name: str | None = None
    hostname: str | None = None
    api_key: str | None = None
    ssh_username: str | None = None
    ssh_password: str | None = None
    collect_enabled: bool | None = None


@router.get("")
async def list_devices(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    result = await session.execute(select(Device))
    devices = result.scalars().all()
    return {"items": [_device_to_dict(d) for d in devices], "total": len(devices)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_device(
    req: DeviceCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    api_key = await _generate_api_key(req.hostname, req.ssh_username, req.ssh_password)
    if not api_key:
        raise HTTPException(status_code=400, detail="无法获取 API Key，请检查设备地址和凭据是否正确")

    device = Device(
        name=req.name,
        hostname=req.hostname,
        auth_type=AuthType.both,
        api_key_encrypted=api_key,
        ssh_username=req.ssh_username,
        ssh_password_encrypted=req.ssh_password,
        collect_enabled=req.collect_enabled,
    )
    session.add(device)
    await session.commit()
    await session.refresh(device)
    return _device_to_dict(device)


async def _generate_api_key(hostname: str, username: str, password: str) -> str | None:
    """Call PAN-OS keygen API to generate an API key from credentials."""
    import httpx
    from lxml import etree

    try:
        url = f"https://{hostname}/api/"
        params = {
            "type": "keygen",
            "user": username,
            "password": password,
        }
        async with httpx.AsyncClient(verify=False, timeout=15) as client:
            resp = await client.get(url, params=params)
        root = etree.fromstring(resp.content)
        if root.get("status") == "success":
            key_el = root.find(".//key")
            if key_el is not None and key_el.text:
                return key_el.text
    except Exception:
        pass
    return None


@router.put("/{device_id}")
async def update_device(
    device_id: str,
    req: DeviceUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await session.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    for field, value in req.model_dump(exclude_unset=True).items():
        if field == "api_key":
            device.api_key_encrypted = value  # TODO: encrypt
        elif field == "ssh_password":
            device.ssh_password_encrypted = value  # TODO: encrypt
        else:
            setattr(device, field, value)

    await session.commit()
    return _device_to_dict(device)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    result = await session.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    await session.delete(device)
    await session.commit()


@router.post("/{device_id}/test-connection")
async def test_connection(
    device_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    result = await session.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    from app.collectors import collector_registry
    results = {}
    if device.api_key_encrypted:
        collector = collector_registry.get("panos_api")
        if collector:
            results["api"] = await collector.test_connection(device)
    if device.ssh_username:
        collector = collector_registry.get("panos_ssh")
        if collector:
            results["ssh"] = await collector.test_connection(device)

    return {"device_id": device_id, "results": results}


def _device_to_dict(device: Device) -> dict:
    return {
        "id": device.id,
        "name": device.name,
        "hostname": device.hostname,
        "model": device.model,
        "serial": device.serial,
        "panos_version": device.panos_version,
        "ha_state": device.ha_state,
        "status": device.status.value if device.status else "unknown",
        "collect_enabled": device.collect_enabled,
        "last_seen": device.last_seen,
        "created_at": str(device.created_at) if device.created_at else None,
    }
