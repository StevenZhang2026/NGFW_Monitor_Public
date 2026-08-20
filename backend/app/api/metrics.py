from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.models.metric import MetricDefinition
from app.models.user import User, UserRole
from app.auth.security import get_current_user, require_role

router = APIRouter()


class MetricDefinitionCreate(BaseModel):
    name: str
    display_name: str
    category: str
    collector: str
    command: str
    parser: dict
    data_type: str = "gauge"
    unit: str = ""
    chart_type: str = "line"
    interval: int = 60
    interval_min: int = 10
    interval_max: int = 300


class MetricIntervalUpdate(BaseModel):
    interval: int


@router.get("/definitions")
async def list_definitions(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    result = await session.execute(select(MetricDefinition))
    metrics = result.scalars().all()
    return {"items": [_def_to_dict(m) for m in metrics]}


@router.post("/definitions", status_code=201)
async def create_definition(
    req: MetricDefinitionCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    metric = MetricDefinition(
        name=req.name,
        display_name=req.display_name,
        category=req.category,
        collector=req.collector,
        command=req.command,
        parser=req.parser,
        data_type=req.data_type,
        unit=req.unit,
        chart_type=req.chart_type,
        interval=req.interval,
        interval_min=req.interval_min,
        interval_max=req.interval_max,
        builtin=False,
    )
    session.add(metric)
    await session.commit()
    await session.refresh(metric)
    return _def_to_dict(metric)


class MetricDefinitionUpdate(BaseModel):
    display_name: str | None = None
    category: str | None = None
    collector: str | None = None
    command: str | None = None
    parser: dict | None = None
    data_type: str | None = None
    unit: str | None = None
    chart_type: str | None = None
    interval: int | None = None
    interval_min: int | None = None
    interval_max: int | None = None
    enabled: bool | None = None


@router.put("/definitions/{metric_id}/interval")
async def update_interval(
    metric_id: str,
    req: MetricIntervalUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    result = await session.execute(select(MetricDefinition).where(MetricDefinition.id == metric_id))
    metric = result.scalar_one_or_none()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    if req.interval < metric.interval_min or req.interval > metric.interval_max:
        raise HTTPException(
            status_code=400,
            detail=f"Interval must be between {metric.interval_min}s and {metric.interval_max}s",
        )

    metric.interval = req.interval
    await session.commit()
    return _def_to_dict(metric)


@router.put("/definitions/{metric_id}")
async def update_definition(
    metric_id: str,
    req: MetricDefinitionUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    result = await session.execute(select(MetricDefinition).where(MetricDefinition.id == metric_id))
    metric = result.scalar_one_or_none()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    if metric.builtin:
        if req.interval is not None:
            metric.interval = req.interval
        if req.enabled is not None:
            metric.enabled = req.enabled
    else:
        if req.display_name is not None:
            metric.display_name = req.display_name
        if req.category is not None:
            metric.category = req.category
        if req.collector is not None:
            metric.collector = req.collector
        if req.command is not None:
            metric.command = req.command
        if req.parser is not None:
            metric.parser = req.parser
        if req.data_type is not None:
            metric.data_type = req.data_type
        if req.unit is not None:
            metric.unit = req.unit
        if req.chart_type is not None:
            metric.chart_type = req.chart_type
        if req.interval is not None:
            metric.interval = req.interval
        if req.interval_min is not None:
            metric.interval_min = req.interval_min
        if req.interval_max is not None:
            metric.interval_max = req.interval_max
        if req.enabled is not None:
            metric.enabled = req.enabled

    await session.commit()
    await session.refresh(metric)
    return _def_to_dict(metric)


@router.delete("/definitions/{metric_id}", status_code=204)
async def delete_definition(
    metric_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.admin)),
):
    result = await session.execute(select(MetricDefinition).where(MetricDefinition.id == metric_id))
    metric = result.scalar_one_or_none()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")
    if metric.builtin:
        raise HTTPException(status_code=400, detail="Cannot delete built-in metric. Disable it instead.")
    await session.delete(metric)
    await session.commit()


@router.get("/data")
async def query_metric_data(
    device_id: str,
    metric_name: str,
    start: datetime,
    end: datetime,
    instance: str = Query(default="", description="Instance filter for multi-instance metrics"),
    granularity: int = Query(default=0, description="Aggregation bucket in seconds. 0 = raw"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if instance:
        name_filter = f"{metric_name}::{instance}"
        name_condition = "metric_name = :metric_name"
    else:
        name_filter = metric_name
        name_condition = "(metric_name = :metric_name OR metric_name LIKE :metric_name_prefix)"

    if granularity == 0:
        query = text(f"""
            SELECT timestamp, metric_name as mn, value FROM metric_data
            WHERE device_id = :device_id AND {name_condition}
              AND timestamp >= :start AND timestamp <= :end
            ORDER BY timestamp
            LIMIT 2000
        """)
        params = {"device_id": device_id, "metric_name": name_filter, "start": start, "end": end}
        if not instance:
            params["metric_name_prefix"] = f"{metric_name}::%"
        result = await session.execute(query, params)
        rows = result.fetchall()
        points = [{"timestamp": str(r.timestamp), "value": r.value, "instance": r.mn.split("::")[-1] if "::" in r.mn else None} for r in rows]
    else:
        query = text(f"""
            SELECT
                time_bucket(INTERVAL '{int(granularity)} seconds', timestamp) AS ts,
                metric_name as mn,
                AVG(value) AS avg,
                MAX(value) AS max,
                MIN(value) AS min
            FROM metric_data
            WHERE device_id = :device_id AND {name_condition}
              AND timestamp >= :start AND timestamp <= :end
            GROUP BY ts, mn
            ORDER BY ts
        """)
        params = {"device_id": device_id, "metric_name": name_filter, "start": start, "end": end}
        if not instance:
            params["metric_name_prefix"] = f"{metric_name}::%"
        result = await session.execute(query, params)
        rows = result.fetchall()
        points = [{"timestamp": str(r.ts), "avg": r.avg, "max": r.max, "min": r.min, "instance": r.mn.split("::")[-1] if "::" in r.mn else None} for r in rows]

    return {
        "device_id": device_id,
        "metric_name": metric_name,
        "granularity": granularity,
        "points": points,
    }


def _def_to_dict(m: MetricDefinition) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "display_name": m.display_name,
        "category": m.category,
        "collector": m.collector,
        "command": m.command,
        "parser": m.parser,
        "data_type": m.data_type.value if hasattr(m.data_type, "value") else m.data_type,
        "unit": m.unit,
        "chart_type": m.chart_type.value if hasattr(m.chart_type, "value") else m.chart_type,
        "interval": m.interval,
        "interval_min": m.interval_min,
        "interval_max": m.interval_max,
        "enabled": m.enabled,
        "builtin": m.builtin,
    }
