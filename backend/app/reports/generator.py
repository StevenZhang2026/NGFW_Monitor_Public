"""Report generator: queries data, computes analysis, renders charts, produces PDF."""

import os
import base64
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from pathlib import Path

import jinja2
import numpy as np
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device, DeviceStatus
from app.models.metric import MetricData
from app.models.report import ReportTemplate, ReportHistory, ReportStatus
from app.reports.analysis import analyze_trend, compute_ranking, TrendResult
from app.reports.charts import (
    render_trend_chart,
    render_pie_chart,
    render_severity_bar,
)

REPORT_DIR = Path("/app/data/reports")
TEMPLATE_DIR = Path(__file__).parent / "templates"

METRIC_THRESHOLDS = {
    "cpu_usage": 80.0,
    "memory_usage": 85.0,
    "packet_descriptor": 80.0,
}

METRIC_LABELS = {
    "cpu_usage": ("CPU 使用率", "%"),
    "memory_usage": ("内存使用率", "%"),
    "session_count": ("活跃会话数", "sessions"),
    "session_cps": ("每秒新建会话", "cps"),
    "packet_descriptor": ("Packet Descriptor 使用率", "%"),
    "acc_application": ("应用流量 Top 10", "KB"),
    "acc_threat": ("威胁统计", "次数"),
}


async def generate_report(template: ReportTemplate, session: AsyncSession) -> ReportHistory:
    """Generate a full report from template definition."""
    now = datetime.now(timezone.utc)

    if template.type.value == "weekly":
        period_end = now
        period_start = now - timedelta(days=7)
        title = "周报"
    elif template.type.value == "monthly":
        period_end = now
        period_start = now - timedelta(days=30)
        title = "月报"
    else:
        period_end = now
        period_start = now - timedelta(days=7)
        title = "自定义报表"

    history = ReportHistory(
        template_id=template.id,
        title=f"{template.name} ({period_start.strftime('%m/%d')}-{period_end.strftime('%m/%d')})",
        period_start=period_start,
        period_end=period_end,
        status=ReportStatus.generating,
    )
    session.add(history)
    await session.commit()

    try:
        devices = await _get_devices(session, template.device_ids)
        device_ids = [d.id for d in devices]

        sections = []
        summary_lines = []

        for metric_conf in template.metrics:
            metric_name = metric_conf["metric"]
            analyses = metric_conf.get("analysis", ["trend"])

            if metric_name in ("acc_application", "acc_threat"):
                section = await _build_acc_section(
                    session, metric_name, device_ids, period_start, period_end, analyses
                )
            else:
                section = await _build_metric_section(
                    session, metric_name, device_ids, period_start, period_end, analyses
                )

            if section:
                sections.append(section)
                if section.get("conclusion"):
                    summary_lines.append(section["conclusion"])

        threat_total = await _get_threat_total(session, device_ids, period_start, period_end)

        html = _render_html(
            report_title=title,
            period_start=period_start.strftime("%Y-%m-%d"),
            period_end=period_end.strftime("%Y-%m-%d"),
            device_count=len(devices),
            online_count=sum(1 for d in devices if d.status == DeviceStatus.online),
            alert_count=0,
            threat_total=threat_total,
            sections=sections,
            summary_lines=summary_lines,
            generated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
        )

        pdf_bytes = _html_to_pdf(html)

        file_path = _save_pdf(pdf_bytes, template.type.value, now)

        history.file_path = str(file_path)
        history.file_size = len(pdf_bytes)
        history.status = ReportStatus.success
        await session.commit()

        return history

    except Exception as e:
        history.status = ReportStatus.failed
        history.error_message = str(e)[:500]
        await session.commit()
        raise


async def _get_devices(session: AsyncSession, device_ids: list | None) -> list[Device]:
    query = select(Device)
    if device_ids:
        query = query.where(Device.id.in_(device_ids))
    result = await session.execute(query)
    return list(result.scalars().all())


async def _build_metric_section(
    session: AsyncSession,
    metric_name: str,
    device_ids: list[str],
    start: datetime,
    end: datetime,
    analyses: list[str],
) -> dict | None:
    result = await session.execute(
        select(MetricData.timestamp, MetricData.value)
        .where(
            MetricData.metric_name == metric_name,
            MetricData.device_id.in_(device_ids),
            MetricData.timestamp >= start,
            MetricData.timestamp <= end,
        )
        .order_by(MetricData.timestamp)
    )
    rows = result.all()
    if not rows:
        return None

    timestamps = [r.timestamp for r in rows]
    values = [float(r.value) for r in rows]

    t0 = timestamps[0]
    hours = [(t - t0).total_seconds() / 3600 for t in timestamps]

    threshold = METRIC_THRESHOLDS.get(metric_name)
    label, unit = METRIC_LABELS.get(metric_name, (metric_name, ""))

    prev_total = None
    if "predict" in analyses or True:
        prev_start = start - (end - start)
        prev_result = await session.execute(
            select(func.sum(MetricData.value))
            .where(
                MetricData.metric_name == metric_name,
                MetricData.device_id.in_(device_ids),
                MetricData.timestamp >= prev_start,
                MetricData.timestamp < start,
            )
        )
        prev_total = prev_result.scalar()

    trend = analyze_trend(values, hours, threshold=threshold, prev_period_total=prev_total)

    chart = ""
    if "trend" in analyses:
        chart = render_trend_chart(
            timestamps, values, label, unit,
            slope_per_hour=trend.slope_per_hour,
            threshold=threshold,
        )

    stats = [
        {"label": "平均", "value": f"{trend.avg}{unit}"},
        {"label": "最高", "value": f"{trend.max}{unit}"},
        {"label": "最低", "value": f"{trend.min}{unit}"},
    ]

    trend_direction = "up" if trend.slope_per_week > 0.5 else ("down" if trend.slope_per_week < -0.5 else "stable")
    if trend_direction == "up":
        trend_text = f"↑{abs(trend.slope_per_week):.1f}{unit}/周"
    elif trend_direction == "down":
        trend_text = f"↓{abs(trend.slope_per_week):.1f}{unit}/周"
    else:
        trend_text = "持平"

    conclusion = _metric_conclusion(metric_name, trend)

    return {
        "title": label,
        "chart": chart,
        "stats": stats,
        "trend_text": trend_text,
        "trend_direction": trend_direction,
        "conclusion": conclusion,
        "table": None,
        "sub_chart": None,
    }


async def _build_acc_section(
    session: AsyncSession,
    metric_name: str,
    device_ids: list[str],
    start: datetime,
    end: datetime,
    analyses: list[str],
) -> dict | None:
    prefix = f"{metric_name}::"
    result = await session.execute(
        select(MetricData.metric_name, MetricData.value, MetricData.labels)
        .where(
            MetricData.metric_name.like(f"{prefix}%"),
            MetricData.device_id.in_(device_ids),
            MetricData.timestamp >= start,
            MetricData.timestamp <= end,
        )
    )
    rows = result.all()
    if not rows:
        return None

    label, unit = METRIC_LABELS.get(metric_name, (metric_name, ""))

    totals: dict[str, float] = defaultdict(float)
    extras: dict[str, dict] = {}

    for row in rows:
        item_name = row.metric_name.replace(prefix, "")
        totals[item_name] += float(row.value)
        if row.labels and item_name not in extras:
            extras[item_name] = row.labels

    ranking = compute_ranking(totals, extras, top_n=10)

    chart = ""
    if ranking:
        names = [r.name for r in ranking]
        vals = [r.value for r in ranking]
        chart = render_pie_chart(names, vals, f"{label} 占比")

    table = None
    if metric_name == "acc_application" and ranking:
        table = {
            "columns": ["#", "应用", "流量", "会话数", "风险"],
            "rows": [
                [i + 1, r.name, _format_bytes(r.value), r.extra.get("sessions", "-"), r.extra.get("risk", "-")]
                for i, r in enumerate(ranking)
            ],
        }
    elif metric_name == "acc_threat" and ranking:
        table = {
            "columns": ["#", "威胁名称", "次数", "严重性", "类别"],
            "rows": [
                [i + 1, r.name, int(r.value), r.extra.get("severity", "-"), r.extra.get("category", "-")]
                for i, r in enumerate(ranking)
            ],
        }

    sub_chart = ""
    if metric_name == "acc_threat":
        sev_counts = defaultdict(int)
        for row in rows:
            if row.labels and "severity" in row.labels:
                sev_counts[row.labels["severity"]] += 1
        if sev_counts:
            sub_chart = render_severity_bar(dict(sev_counts), "威胁严重性分布")

    total_count = sum(totals.values())
    if metric_name == "acc_threat":
        conclusion = f"本期共检测到 {int(total_count)} 次威胁事件，Top 1 为 {ranking[0].name}（{int(ranking[0].value)} 次）。" if ranking else ""
    else:
        conclusion = f"本期应用流量 Top 1 为 {ranking[0].name}，占比 {ranking[0].value / total_count * 100:.1f}%。" if ranking and total_count > 0 else ""

    return {
        "title": label,
        "chart": chart,
        "stats": [{"label": "总计", "value": f"{int(total_count)} {unit}"}],
        "trend_text": None,
        "trend_direction": None,
        "conclusion": conclusion,
        "table": table,
        "sub_chart": sub_chart,
    }


async def _get_threat_total(session: AsyncSession, device_ids: list[str], start: datetime, end: datetime) -> int:
    result = await session.execute(
        select(func.sum(MetricData.value))
        .where(
            MetricData.metric_name.like("acc_threat::%"),
            MetricData.device_id.in_(device_ids),
            MetricData.timestamp >= start,
            MetricData.timestamp <= end,
        )
    )
    val = result.scalar()
    return int(val) if val else 0


def _metric_conclusion(metric_name: str, trend: TrendResult) -> str:
    label, unit = METRIC_LABELS.get(metric_name, (metric_name, ""))

    if trend.slope_per_week > 0.5:
        base = f"本期{label}呈上升趋势（均值 {trend.avg}{unit}，"
        if trend.change_pct is not None:
            base += f"环比 +{trend.change_pct}%）"
        else:
            base += f"周增 {trend.slope_per_week:.1f}{unit}）"
        if trend.weeks_to_threshold:
            base += f"，按当前增速预计 {trend.weeks_to_threshold:.0f} 周后触及告警阈值，建议关注。"
        else:
            base += "。"
        return base
    elif trend.slope_per_week < -0.5:
        return f"本期{label}有所下降（均值 {trend.avg}{unit}），运行平稳。"
    else:
        return f"本期{label}保持稳定（均值 {trend.avg}{unit}），无异常。"


def _render_html(**kwargs) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template("report.html")
    return template.render(**kwargs)


def _html_to_pdf(html: str) -> bytes:
    from weasyprint import HTML
    return HTML(string=html).write_pdf()


def _save_pdf(pdf_bytes: bytes, report_type: str, now: datetime) -> Path:
    subdir = REPORT_DIR / now.strftime("%Y/%m")
    subdir.mkdir(parents=True, exist_ok=True)
    filename = f"{report_type}_{now.strftime('%Y%m%d_%H%M%S')}.pdf"
    filepath = subdir / filename
    filepath.write_bytes(pdf_bytes)
    return filepath


def _format_bytes(bytes_val: float) -> str:
    kb = bytes_val / 1024
    if kb >= 1e6:
        return f"{kb / 1e6:.1f} GB"
    if kb >= 1e3:
        return f"{kb / 1e3:.1f} MB"
    return f"{kb:.0f} KB"
