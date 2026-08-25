from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.models.setting import SystemSetting
from app.models.user import User
from app.auth.security import get_current_user
from app.copilot.intent import parse_intent, IntentError
from app.copilot.formatter import format_response

router = APIRouter()


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


async def _get_ai_config(session: AsyncSession) -> dict:
    result = await session.execute(
        select(SystemSetting).where(SystemSetting.key.like("ai_%"))
    )
    settings = {s.key: s.value for s in result.scalars().all()}
    return {
        "api_base": settings.get("ai_api_base", ""),
        "api_key": settings.get("ai_api_key", ""),
        "model": settings.get("ai_model", ""),
    }


async def _execute_query(action: str, params: dict, session: AsyncSession, user: User) -> dict:
    if action == "acc_ranking":
        return await _query_acc_ranking(params, session)
    elif action == "acc_trend":
        return await _query_acc_trend(params, session)
    elif action == "metric_data":
        return await _query_metric_data(params, session, user)
    elif action == "alert_events":
        return await _query_alerts(params, session)
    elif action == "device_status":
        return await _query_devices(session)
    return {}


async def _query_acc_ranking(params: dict, session: AsyncSession) -> dict:
    metric_name = params.get("metric_name", "acc_application")
    days = params.get("days", 7)
    limit = params.get("limit", 10)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    label_key = "application" if metric_name == "acc_application" else "threat_name"

    query = text(f"""
        SELECT labels->>'{label_key}' AS name,
               SUM(value) AS total
        FROM metric_data
        WHERE metric_name LIKE :prefix
          AND timestamp >= :start AND timestamp <= :end
          AND labels->>'{label_key}' IS NOT NULL
        GROUP BY name
        ORDER BY total DESC
        LIMIT :limit
    """)
    result = await session.execute(query, {
        "prefix": f"{metric_name}::%",
        "start": start, "end": end, "limit": limit,
    })
    rows = result.fetchall()

    if metric_name == "acc_application":
        return {"items": [{"name": r.name, "bytes": float(r.total)} for r in rows]}
    else:
        return {"items": [{"name": r.name, "count": int(r.total)} for r in rows]}


async def _query_acc_trend(params: dict, session: AsyncSession) -> dict:
    metric_name = params.get("metric_name", "acc_application")
    days = params.get("days", 7)
    top_n = params.get("top_n", 10)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    label_key = "application" if metric_name == "acc_application" else "threat_name"

    query = text(f"""
        SELECT labels->>'{label_key}' AS name, SUM(value) AS total
        FROM metric_data
        WHERE metric_name LIKE :prefix
          AND timestamp >= :start AND timestamp <= :end
          AND labels->>'{label_key}' IS NOT NULL
        GROUP BY name ORDER BY total DESC LIMIT :top_n
    """)
    result = await session.execute(query, {
        "prefix": f"{metric_name}::%", "start": start, "end": end, "top_n": top_n,
    })
    items = [r.name for r in result.fetchall()]

    bucket = "1 day" if days > 7 else "6 hours" if days > 1 else "1 hour"
    return {"items": items, "bucket": bucket}


async def _query_metric_data(params: dict, session: AsyncSession, user: User) -> dict:
    from app.auth.scope import get_scoped_device_ids
    from app.models.metric import MetricDefinition
    from app.metrics.rate import counter_rate_config, counter_rate_source
    metric_name = params.get("metric_name", "cpu_usage")
    days = params.get("days", 7)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    definition = (await session.execute(
        select(MetricDefinition).where(MetricDefinition.name == metric_name)
    )).scalar_one_or_none()
    is_counter, scale, lookback = counter_rate_config(definition)

    scoped_ids = await get_scoped_device_ids(user, session)
    query_params: dict = {"metric": metric_name, "start": start, "end": end}
    if scoped_ids is None:
        device_condition = "TRUE"
    else:
        device_condition = "device_id = ANY(:device_ids)"
        query_params["device_ids"] = scoped_ids

    granularity = 3600 if days <= 7 else 7200

    if is_counter:
        # Answering with the counter itself would report total bytes since the
        # last reboot, which is not what anyone asking about throughput means.
        # Each interface keeps its own counter, so the rate is computed per
        # instance and the *busiest* one is reported: summing interfaces would
        # roughly double-count, because traffic crosses the firewall on two.
        query_params["prefix"] = f"{metric_name}::%"
        rate_sql = counter_rate_source(
            device_condition,
            "(metric_name = :metric OR metric_name LIKE :prefix)",
            lookback,
            scale,
        )
        query = text(f"""
            SELECT ts, MAX(inst_avg) AS avg, MAX(inst_max) AS max_val
            FROM (
                SELECT time_bucket(INTERVAL '{granularity} seconds', timestamp) AS ts,
                       device_id, mn,
                       AVG(value) AS inst_avg, MAX(value) AS inst_max
                FROM ({rate_sql}) AS rates
                GROUP BY ts, device_id, mn
            ) AS per_instance
            GROUP BY ts ORDER BY ts
        """)
    else:
        query = text(f"""
            SELECT time_bucket(INTERVAL '{granularity} seconds', timestamp) AS ts,
                   AVG(value) AS avg, MAX(value) AS max_val
            FROM metric_data
            WHERE metric_name = :metric
              AND timestamp >= :start AND timestamp <= :end
              AND {device_condition}
            GROUP BY ts ORDER BY ts
        """)
    result = await session.execute(query, query_params)
    rows = result.fetchall()
    return {
        "points": [
            {"timestamp": str(r.ts), "avg": float(r.avg), "max": float(r.max_val)}
            for r in rows
        ],
        "unit": (definition.unit if definition else "") or "",
        "derived": "rate" if is_counter else "raw",
    }


async def _query_alerts(params: dict, session: AsyncSession) -> dict:
    from app.models.alert import AlertEvent, Severity, AlertStatus
    days = params.get("days", 7)
    severity = params.get("severity")
    status = params.get("status")

    start = datetime.now(timezone.utc) - timedelta(days=days)
    query = select(AlertEvent).where(AlertEvent.triggered_at >= start)

    if severity:
        query = query.where(AlertEvent.severity == Severity(severity))
    if status:
        query = query.where(AlertEvent.status == AlertStatus(status))

    query = query.order_by(AlertEvent.triggered_at.desc()).limit(50)
    result = await session.execute(query)
    events = result.scalars().all()

    return {"items": [{
        "triggered_at": str(e.triggered_at),
        "severity": e.severity.value,
        "metric_name": e.metric_name,
        "status": e.status.value,
        "value": e.value,
        "message": e.message,
    } for e in events]}


async def _query_devices(session: AsyncSession) -> dict:
    from app.models.device import Device
    result = await session.execute(select(Device))
    devices = result.scalars().all()
    return {"items": [{
        "name": d.name,
        "hostname": d.hostname,
        "status": d.status,
    } for d in devices]}


@router.post("/chat", response_model=ChatResponse)
async def copilot_chat(
    req: ChatRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    config = await _get_ai_config(session)
    if not config["api_base"] or not config["api_key"] or not config["model"]:
        raise HTTPException(status_code=400, detail="AI 助手未配置，请在系统设置中配置模型信息。")

    try:
        intent = await parse_intent(req.message, config["api_base"], config["api_key"], config["model"])
    except IntentError as e:
        return ChatResponse(reply=f"⚠️ AI 服务调用失败：{e}")
    if not intent:
        return ChatResponse(reply="抱歉，我无法理解您的问题。请尝试更具体的描述，例如：「最近3天的威胁Top 10」或「CPU使用率趋势」。")

    action = intent.get("action", "")
    params = intent.get("params", {})
    summary_request = intent.get("summary_request", req.message)

    try:
        result = await _execute_query(action, params, session, user)
        reply = format_response(action, params, result, summary_request)
    except Exception as e:
        reply = f"查询执行出错：{str(e)}"

    return ChatResponse(reply=reply)
