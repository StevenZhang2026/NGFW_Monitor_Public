"""Initialize builtin report templates on first startup."""

from sqlalchemy import select

from app.models.database import async_session
from app.models.report import ReportTemplate, ReportType

BUILTIN_REPORTS = [
    {
        "name": "防火墙周报",
        "type": ReportType.weekly,
        "schedule_cron": "0 8 * * 1",
        "metrics": [
            {"metric": "cpu_usage", "analysis": ["trend", "predict", "avg", "max"]},
            {"metric": "memory_usage", "analysis": ["trend", "predict", "avg", "max"]},
            {"metric": "session_count", "analysis": ["trend", "avg", "max"]},
            {"metric": "acc_application", "analysis": ["trend", "top10"]},
            {"metric": "acc_threat", "analysis": ["trend", "top10", "severity_breakdown"]},
        ],
        "recipients": [],
    },
    {
        "name": "防火墙月报",
        "type": ReportType.monthly,
        "schedule_cron": "0 8 1 * *",
        "metrics": [
            {"metric": "cpu_usage", "analysis": ["trend", "predict", "avg", "max"]},
            {"metric": "memory_usage", "analysis": ["trend", "predict", "avg", "max"]},
            {"metric": "session_count", "analysis": ["trend", "predict", "avg", "max"]},
            {"metric": "packet_descriptor", "analysis": ["trend", "predict", "avg", "max"]},
            {"metric": "acc_application", "analysis": ["trend", "top10"]},
            {"metric": "acc_threat", "analysis": ["trend", "top10", "severity_breakdown"]},
        ],
        "recipients": [],
    },
]


async def init_builtin_reports():
    async with async_session() as session:
        for report_def in BUILTIN_REPORTS:
            existing = (await session.execute(
                select(ReportTemplate).where(
                    ReportTemplate.name == report_def["name"],
                    ReportTemplate.builtin == True,
                )
            )).scalar_one_or_none()

            if existing:
                existing.metrics = report_def["metrics"]
                existing.schedule_cron = report_def["schedule_cron"]
            else:
                template = ReportTemplate(
                    name=report_def["name"],
                    type=report_def["type"],
                    schedule_cron=report_def["schedule_cron"],
                    metrics=report_def["metrics"],
                    recipients=report_def["recipients"],
                    builtin=True,
                    enabled=True,
                )
                session.add(template)

        await session.commit()
