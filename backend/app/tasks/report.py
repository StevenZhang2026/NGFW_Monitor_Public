"""Celery tasks for report generation and email delivery."""

import asyncio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path

import aiosmtplib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.tasks import celery_app
from app.config import settings
from app.models.report import ReportTemplate, ReportHistory, ReportStatus


@celery_app.task(name="tasks.generate_report")
def generate_report_task(template_id: str):
    """Generate a report from template and send via email."""
    asyncio.run(_generate_and_send(template_id))


@celery_app.task(name="tasks.check_report_schedules")
def check_report_schedules():
    """Periodic task: check if any report templates are due for generation."""
    asyncio.run(_check_schedules())


async def _generate_and_send(template_id: str):
    from app.reports.generator import generate_report

    engine = create_async_engine(
        settings.database_url, echo=False, pool_size=1, max_overflow=0, pool_pre_ping=True
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with factory() as session:
            template = (await session.execute(
                select(ReportTemplate).where(ReportTemplate.id == template_id)
            )).scalar_one_or_none()

            if not template:
                return

            history = await generate_report(template, session)

            if history.status == ReportStatus.success and template.recipients:
                await _send_report_email(template, history, session)
    finally:
        await engine.dispose()


async def _check_schedules():
    """Check cron schedules and trigger due reports."""
    from datetime import datetime, timezone
    from celery.schedules import crontab

    engine = create_async_engine(
        settings.database_url, echo=False, pool_size=1, max_overflow=0, pool_pre_ping=True
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with factory() as session:
            templates = (await session.execute(
                select(ReportTemplate).where(
                    ReportTemplate.enabled == True,
                    ReportTemplate.schedule_cron.isnot(None),
                )
            )).scalars().all()

            now = datetime.now(timezone.utc)

            for template in templates:
                last_report = (await session.execute(
                    select(ReportHistory)
                    .where(ReportHistory.template_id == template.id)
                    .order_by(ReportHistory.created_at.desc())
                    .limit(1)
                )).scalar_one_or_none()

                should_run = False
                if last_report is None:
                    should_run = True
                else:
                    if template.type.value == "weekly":
                        should_run = (now - last_report.created_at).total_seconds() > 6 * 86400
                    elif template.type.value == "monthly":
                        should_run = (now - last_report.created_at).total_seconds() > 27 * 86400

                if should_run:
                    generate_report_task.delay(template.id)
    finally:
        await engine.dispose()


async def _send_report_email(template: ReportTemplate, history: ReportHistory, session: AsyncSession):
    """Send generated PDF report via email."""
    from datetime import datetime, timezone

    recipients = template.recipients
    if not recipients or not settings.smtp_host:
        return

    pdf_path = Path(history.file_path)
    if not pdf_path.exists():
        return

    pdf_bytes = pdf_path.read_bytes()

    msg = MIMEMultipart()
    msg["Subject"] = f"防火墙监控{history.title}"
    msg["From"] = settings.smtp_from or settings.smtp_username
    msg["To"] = ", ".join(recipients)

    body_html = f"""
    <p>您好，</p>
    <p>附件为自动生成的防火墙监控报表：<strong>{history.title}</strong></p>
    <p>报表周期：{history.period_start.strftime('%Y-%m-%d')} ~ {history.period_end.strftime('%Y-%m-%d')}</p>
    <p>如需查看更多详情，请登录监控系统 Web 界面。</p>
    <p style="color:#999;font-size:12px">— 防火墙集中监控系统自动发送</p>
    """
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
    filename = pdf_path.name
    pdf_part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(pdf_part)

    try:
        smtp_kwargs = {
            "hostname": settings.smtp_host,
            "port": settings.smtp_port,
            "use_tls": settings.smtp_use_ssl,
            "username": settings.smtp_username,
            "password": settings.smtp_password,
        }
        await aiosmtplib.send(msg, **smtp_kwargs)
        history.sent_at = datetime.now(timezone.utc)
        await session.commit()
    except Exception:
        pass
