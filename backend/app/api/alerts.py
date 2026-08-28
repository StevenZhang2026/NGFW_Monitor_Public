from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import get_session
from app.models.alert import AlertRule, AlertEvent, AlertType, Severity, AlertStatus
from app.models.user import User, UserRole
from app.auth.security import get_current_user, require_role
from app.auth.scope import get_scoped_device_ids

router = APIRouter()


class AlertRuleCreate(BaseModel):
    name: str
    metric_name: str
    device_ids: list[str]
    type: str
    condition: dict
    severity: str = "warning"
    notification_channel_ids: list[str] = []
    notify_interval: int = 30
    enabled: bool = True


@router.get("/rules")
async def list_rules(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    result = await session.execute(select(AlertRule))
    rules = result.scalars().all()
    return {"items": [_rule_to_dict(r) for r in rules]}


@router.post("/rules", status_code=201)
async def create_rule(
    req: AlertRuleCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    rule = AlertRule(
        name=req.name,
        metric_name=req.metric_name,
        device_ids=req.device_ids,
        type=AlertType(req.type),
        condition=req.condition,
        severity=Severity(req.severity),
        notification_channel_ids=req.notification_channel_ids,
        notify_interval=req.notify_interval,
        enabled=req.enabled,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return _rule_to_dict(rule)


class AlertRuleUpdate(BaseModel):
    name: str | None = None
    metric_name: str | None = None
    device_ids: list[str] | None = None
    type: str | None = None
    condition: dict | None = None
    severity: str | None = None
    notification_channel_ids: list[str] | None = None
    notify_interval: int | None = None
    enabled: bool | None = None


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: str,
    req: AlertRuleUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await session.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    if req.name is not None:
        rule.name = req.name
    if req.metric_name is not None:
        rule.metric_name = req.metric_name
    if req.device_ids is not None:
        rule.device_ids = req.device_ids
    if req.type is not None:
        rule.type = AlertType(req.type)
    if req.condition is not None:
        rule.condition = req.condition
    if req.severity is not None:
        rule.severity = Severity(req.severity)
    if req.notification_channel_ids is not None:
        rule.notification_channel_ids = req.notification_channel_ids
    if req.notify_interval is not None:
        rule.notify_interval = req.notify_interval
    if req.enabled is not None:
        rule.enabled = req.enabled

    await session.commit()
    await session.refresh(rule)
    return _rule_to_dict(rule)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    result = await session.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    await session.delete(rule)
    await session.commit()


@router.get("/events")
async def list_events(
    severity: str | None = None,
    status: str | None = None,
    device_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, le=200),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    filters = []
    scoped_ids = await get_scoped_device_ids(user, session)
    if scoped_ids is not None:
        filters.append(AlertEvent.device_id.in_(scoped_ids))

    if severity:
        filters.append(AlertEvent.severity == Severity(severity))
    if status:
        filters.append(AlertEvent.status == AlertStatus(status))
    if device_id:
        filters.append(AlertEvent.device_id == device_id)

    # Returned so the client can page through everything. Without it the client
    # can only paginate the rows it happens to have been given, and the event
    # list silently ends at one page_size worth of history.
    total = (await session.execute(
        select(func.count(AlertEvent.id)).where(*filters)
    )).scalar_one()

    query = (
        select(AlertEvent)
        .where(*filters)
        .order_by(AlertEvent.triggered_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(query)
    events = result.scalars().all()
    return {
        "items": [_event_to_dict(e) for e in events],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/active-count")
async def active_alert_count(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    query = select(func.count(AlertEvent.id)).where(AlertEvent.status == AlertStatus.firing)
    scoped_ids = await get_scoped_device_ids(user, session)
    if scoped_ids is not None:
        query = query.where(AlertEvent.device_id.in_(scoped_ids))
    count = (await session.execute(query)).scalar_one()
    return {"count": count}


@router.get("/collection-health")
async def collection_health(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    """Raw vitals behind the 采集健康度 alerts, for diagnosing one.

    Reads the cumulative skip tally rather than the per-window deltas: taking the
    deltas advances a snapshot, and only the health check may do that.
    """
    from app.alerts.health import HEALTH_RULE_METRIC, _cycle_budget
    from app.models.device import Device
    from app.models.metric import MetricDefinition
    from app.tasks.locks import collect_durations, collect_skips, queue_depth

    rule = (await session.execute(
        select(AlertRule).where(AlertRule.metric_name == HEALTH_RULE_METRIC)
    )).scalars().first()

    devices = (await session.execute(
        select(Device).where(Device.collect_enabled == True)
    )).scalars().all()
    metrics = (await session.execute(
        select(MetricDefinition).where(MetricDefinition.enabled == True)
    )).scalars().all()

    durations = collect_durations()
    skips = collect_skips()
    budget = _cycle_budget(metrics)

    return {
        "rule": {"id": rule.id, "enabled": rule.enabled, "condition": rule.condition} if rule else None,
        "cycle_budget_seconds": budget,
        "queue_depth": queue_depth(),
        "device_count": len(devices),
        "worker_concurrency": settings.collector_concurrency,
        "devices": [
            {
                "device_id": d.id,
                "name": d.name,
                "status": d.status.value if hasattr(d.status, "value") else d.status,
                "last_seen": d.last_seen,
                "last_collect_seconds": (durations.get(d.id) or {}).get("last"),
                "peak_collect_seconds": (durations.get(d.id) or {}).get("max"),
                "last_collect_at": (durations.get(d.id) or {}).get("at"),
                "skipped_cycles": (skips.get(d.id) or {}).get("count", 0),
                "last_skip_at": (skips.get(d.id) or {}).get("last"),
            }
            for d in devices
        ],
    }


class BatchAcknowledge(BaseModel):
    event_ids: list[str] | None = None
    rule_id: str | None = None


@router.post("/events/batch-acknowledge")
async def batch_acknowledge_events(
    req: BatchAcknowledge,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    from datetime import datetime, timezone
    query = select(AlertEvent).where(AlertEvent.status == AlertStatus.firing)
    if req.event_ids:
        query = query.where(AlertEvent.id.in_(req.event_ids))
    elif req.rule_id:
        query = query.where(AlertEvent.rule_id == req.rule_id)

    # scope 过滤要无条件生效：只放在 else 分支里的话，带 event_ids / rule_id
    # 的调用就能确认（静音）范围外设备的告警。
    scoped_ids = await get_scoped_device_ids(user, session)
    if scoped_ids is not None:
        query = query.where(AlertEvent.device_id.in_(scoped_ids))

    result = await session.execute(query)
    events = result.scalars().all()
    now = datetime.now(timezone.utc)
    for event in events:
        event.status = AlertStatus.acknowledged
        event.acknowledged_at = now
        event.acknowledged_by = user.id
    await session.commit()
    return {"acknowledged": len(events)}


@router.post("/events/{event_id}/acknowledge")
async def acknowledge_event(
    event_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    from datetime import datetime, timezone
    from app.auth.scope import check_device_in_scope
    result = await session.execute(select(AlertEvent).where(AlertEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    # 范围外的事件按"不存在"处理，不泄露它的存在
    if event.device_id and not await check_device_in_scope(event.device_id, user, session):
        raise HTTPException(status_code=404, detail="Event not found")
    event.status = AlertStatus.acknowledged
    event.acknowledged_at = datetime.now(timezone.utc)
    event.acknowledged_by = user.id
    await session.commit()
    return _event_to_dict(event)


def _rule_to_dict(r: AlertRule) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "metric_name": r.metric_name,
        "device_ids": r.device_ids,
        "type": r.type.value,
        "condition": r.condition,
        "severity": r.severity.value,
        "notification_channel_ids": r.notification_channel_ids,
        "notify_interval": r.notify_interval,
        "enabled": r.enabled,
    }


def _event_to_dict(e: AlertEvent) -> dict:
    return {
        "id": e.id,
        "rule_id": e.rule_id,
        "device_id": e.device_id,
        "metric_name": e.metric_name,
        "severity": e.severity.value,
        "status": e.status.value,
        "message": e.message,
        "value": e.value,
        "triggered_at": str(e.triggered_at),
        "resolved_at": str(e.resolved_at) if e.resolved_at else None,
        "acknowledged_at": str(e.acknowledged_at) if e.acknowledged_at else None,
    }
