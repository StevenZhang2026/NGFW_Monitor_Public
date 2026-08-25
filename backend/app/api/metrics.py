from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.models.metric import MetricDefinition
from app.metrics.rate import counter_rate_config, counter_rate_source
from app.models.user import User, UserRole
from app.auth.security import get_current_user, require_role
from app.auth.scope import check_device_in_scope

router = APIRouter()

# Threat severity ranked by danger, worst first.
SEVERITY_RANK = ["critical", "high", "medium", "low", "informational"]

# Collapsing several threat IDs onto one display name must report the worst
# severity among them. Aggregating the raw string instead would sort
# alphabetically (critical < high < informational < low < medium) and
# systematically under-report critical findings. Unrecognised values fall back
# to the raw string rather than vanishing.
SEVERITY_AGG = (
    "COALESCE((ARRAY["
    + ",".join(f"'{s}'" for s in SEVERITY_RANK)
    + "])[MIN(CASE labels->>'severity' "
    + " ".join(f"WHEN '{s}' THEN {i + 1}" for i, s in enumerate(SEVERITY_RANK))
    + f" ELSE {len(SEVERITY_RANK) + 1} END)], MIN(labels->>'severity'))"
)


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
    raw_counter: bool = Query(
        default=False,
        description="Return the stored cumulative counter instead of a rate",
    ),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if instance:
        name_filter = f"{metric_name}::{instance}"
        name_condition = "metric_name = :metric_name"
    else:
        name_filter = metric_name
        name_condition = "(metric_name = :metric_name OR metric_name LIKE :metric_name_prefix)"

    definition = (await session.execute(
        select(MetricDefinition).where(MetricDefinition.name == metric_name)
    )).scalar_one_or_none()

    data_type = getattr(definition.data_type, "value", None) if definition else None
    is_counter, scale, lookback = counter_rate_config(definition)
    as_rate = is_counter and not raw_counter
    if as_rate:
        source = (
            "("
            + counter_rate_source(
                "device_id = :device_id", name_condition, lookback, scale
            )
            + ") AS src"
        )
        select_cols = "timestamp, mn, value"
    else:
        source = "metric_data"
        select_cols = "timestamp, metric_name AS mn, value"

    params = {"device_id": device_id, "metric_name": name_filter, "start": start, "end": end}
    if not instance:
        params["metric_name_prefix"] = f"{metric_name}::%"

    # The rate subquery has already applied the device/name/time filters; a
    # plain metric_data read still needs them.
    outer_where = (
        "TRUE" if as_rate
        else f"device_id = :device_id AND {name_condition}"
             " AND timestamp >= :start AND timestamp <= :end"
    )

    if granularity == 0:
        query = text(f"""
            SELECT {select_cols} FROM {source}
            WHERE {outer_where}
            ORDER BY timestamp
            LIMIT 2000
        """)
        rows = (await session.execute(query, params)).fetchall()
        points = [
            {
                "timestamp": str(r.timestamp),
                "value": r.value,
                "instance": r.mn.split("::")[-1] if "::" in r.mn else None,
            }
            for r in rows
        ]
    else:
        # For a counter, the rate is computed per raw sample first and only then
        # bucketed. Bucketing the cumulative values first and differencing the
        # bucket averages would smear each reset across a whole bucket.
        query = text(f"""
            SELECT
                time_bucket(INTERVAL '{int(granularity)} seconds', timestamp) AS ts,
                mn,
                AVG(value) AS avg,
                MAX(value) AS max,
                MIN(value) AS min
            FROM ({f"SELECT {select_cols} FROM {source} WHERE {outer_where}"}) AS pts
            GROUP BY ts, mn
            ORDER BY ts
        """)
        rows = (await session.execute(query, params)).fetchall()
        points = [
            {
                "timestamp": str(r.ts),
                "avg": r.avg,
                "max": r.max,
                "min": r.min,
                "instance": r.mn.split("::")[-1] if "::" in r.mn else None,
            }
            for r in rows
        ]

    return {
        "device_id": device_id,
        "metric_name": metric_name,
        "granularity": granularity,
        "data_type": data_type,
        # Tells the caller whether it is looking at the stored counter or a rate
        # derived from it, so a chart can label the axis honestly.
        "derived": "rate" if as_rate else "raw",
        "unit": (definition.unit if definition else "") or "",
        "points": points,
    }


@router.get("/acc-trend")
async def query_acc_trend(
    metric_name: str = Query(description="acc_application or acc_threat"),
    start: datetime = Query(default=None),
    end: datetime = Query(default=None),
    device_id: str = Query(default=""),
    top_n: int = Query(default=10, ge=1, le=50),
    severity: str = Query(default="", description="Filter by severity: 'critical,high' or empty for all"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return Top N items with time-bucketed trend data for ACC metrics."""
    from datetime import timezone, timedelta

    if metric_name not in ("acc_application", "acc_threat"):
        raise HTTPException(status_code=400, detail="metric_name must be acc_application or acc_threat")

    if device_id and not await check_device_in_scope(device_id, user, session):
        raise HTTPException(status_code=403, detail="No access to this device")

    if not end:
        end = datetime.now(timezone.utc)
    if not start:
        start = end - timedelta(days=7)

    label_key = "application" if metric_name == "acc_application" else "threat_name"

    device_filter = "AND device_id = :device_id" if device_id else ""
    params: dict = {"metric_prefix": f"{metric_name}::%", "start": start, "end": end}
    if device_id:
        params["device_id"] = device_id

    VALID_SEVERITIES = {"critical", "high", "medium", "low", "informational"}
    severity_filter = ""
    severity_order = ""
    if metric_name == "acc_threat" and severity:
        sev_list = [s.strip() for s in severity.split(",") if s.strip() and s.strip() in VALID_SEVERITIES]
        if sev_list:
            severity_filter = "AND labels->>'severity' = ANY(:severities)"
            params["severities"] = sev_list
            case_lines = " ".join(f"WHEN '{s}' THEN {i}" for i, s in enumerate(sev_list))
            severity_order = f"CASE MIN(labels->>'severity') {case_lines} END,"

    top_query = text(f"""
        SELECT labels->>'{label_key}' AS item_name, SUM(value) AS total
        FROM metric_data
        WHERE metric_name LIKE :metric_prefix
          AND timestamp >= :start AND timestamp <= :end
          {device_filter}
          {severity_filter}
          AND labels->>'{label_key}' IS NOT NULL
        GROUP BY item_name
        ORDER BY {severity_order} total DESC
        LIMIT :top_n
    """)
    params["top_n"] = top_n
    result = await session.execute(top_query, params)
    top_items = [row.item_name for row in result.fetchall()]

    if not top_items:
        return {"metric_name": metric_name, "items": [], "series": []}

    hours_span = (end - start).total_seconds() / 3600
    if hours_span <= 24:
        bucket = "1 hour"
    elif hours_span <= 168:
        bucket = "6 hours"
    else:
        bucket = "1 day"

    series_query = text(f"""
        SELECT
            time_bucket(INTERVAL '{bucket}', timestamp) AS ts,
            labels->>'{label_key}' AS item_name,
            SUM(value) AS total
        FROM metric_data
        WHERE metric_name LIKE :metric_prefix
          AND timestamp >= :start AND timestamp <= :end
          {device_filter}
          {severity_filter}
          AND labels->>'{label_key}' = ANY(:items)
        GROUP BY ts, item_name
        ORDER BY ts
    """)
    series_params: dict = {"metric_prefix": f"{metric_name}::%", "start": start, "end": end, "items": top_items}
    if device_id:
        series_params["device_id"] = device_id
    if "severities" in params:
        series_params["severities"] = params["severities"]
    result = await session.execute(series_query, series_params)
    rows = result.fetchall()

    series: dict[str, list] = {item: [] for item in top_items}
    for row in rows:
        series[row.item_name].append({"timestamp": str(row.ts), "value": float(row.total)})

    return {
        "metric_name": metric_name,
        "bucket": bucket,
        "items": top_items,
        "series": series,
    }


@router.get("/acc-ranking")
async def query_acc_ranking(
    metric_name: str = Query(description="acc_application or acc_threat"),
    start: datetime = Query(default=None),
    end: datetime = Query(default=None),
    device_id: str = Query(default=""),
    limit: int = Query(default=200, ge=0, le=1000, description="0 = no limit"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return full ranking list for ACC metrics with extra label fields."""
    from datetime import timezone, timedelta

    if metric_name not in ("acc_application", "acc_threat"):
        raise HTTPException(status_code=400, detail="metric_name must be acc_application or acc_threat")

    if device_id and not await check_device_in_scope(device_id, user, session):
        raise HTTPException(status_code=403, detail="No access to this device")

    if not end:
        end = datetime.now(timezone.utc)
    if not start:
        start = end - timedelta(days=7)

    device_filter = "AND device_id = :device_id" if device_id else ""
    params: dict = {"metric_prefix": f"{metric_name}::%", "start": start, "end": end}
    if device_id:
        params["device_id"] = device_id

    # limit=0 means return the full ranking
    limit_clause = ""
    if limit > 0:
        limit_clause = "LIMIT :limit_n"
        params["limit_n"] = limit

    if metric_name == "acc_application":
        query = text(f"""
            SELECT
                labels->>'application' AS name,
                SUM(value) AS bytes,
                SUM((labels->>'sessions')::bigint) AS sessions,
                MAX(labels->>'risk') AS risk
            FROM metric_data
            WHERE metric_name LIKE :metric_prefix
              AND timestamp >= :start AND timestamp <= :end
              {device_filter}
              AND labels->>'application' IS NOT NULL
            GROUP BY name
            ORDER BY bytes DESC
            {limit_clause}
        """)
    else:
        query = text(f"""
            SELECT
                labels->>'threat_name' AS name,
                SUM(value) AS count,
                {SEVERITY_AGG} AS severity,
                MAX(labels->>'category') AS category
            FROM metric_data
            WHERE metric_name LIKE :metric_prefix
              AND timestamp >= :start AND timestamp <= :end
              {device_filter}
              AND labels->>'threat_name' IS NOT NULL
            GROUP BY name
            ORDER BY count DESC
            {limit_clause}
        """)

    result = await session.execute(query, params)
    rows = result.fetchall()

    if metric_name == "acc_application":
        items = [
            {"name": r.name, "bytes": float(r.bytes), "sessions": int(r.sessions or 0), "risk": r.risk or ""}
            for r in rows
        ]
    else:
        items = [
            {"name": r.name, "count": float(r.count), "severity": r.severity or "", "category": r.category or ""}
            for r in rows
        ]

    return {
        "metric_name": metric_name,
        "items": items,
        "limit": limit,
        "truncated": limit > 0 and len(items) >= limit,
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
