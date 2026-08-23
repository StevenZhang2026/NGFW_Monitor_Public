"""API routes for report template management and history viewing."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.models.report import ReportTemplate, ReportHistory, ReportType, ReportStatus
from app.models.user import User
from app.auth.security import get_current_user, require_role

router = APIRouter()


class ReportTemplateCreate(BaseModel):
    name: str
    type: str = "weekly"
    schedule_cron: str | None = None
    metrics: list[dict] = []
    recipients: list[str] = []
    device_ids: list[str] | None = None
    enabled: bool = True


class ReportTemplateUpdate(BaseModel):
    name: str | None = None
    schedule_cron: str | None = None
    metrics: list[dict] | None = None
    recipients: list[str] | None = None
    device_ids: list[str] | None = None
    enabled: bool | None = None


@router.get("/templates")
async def list_templates(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role("admin")),
):
    result = await session.execute(
        select(ReportTemplate).order_by(ReportTemplate.created_at.desc())
    )
    templates = result.scalars().all()
    return {
        "items": [
            {
                "id": t.id,
                "name": t.name,
                "type": t.type.value,
                "schedule_cron": t.schedule_cron,
                "metrics": t.metrics,
                "recipients": t.recipients,
                "device_ids": t.device_ids,
                "enabled": t.enabled,
                "builtin": t.builtin,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in templates
        ]
    }


@router.post("/templates")
async def create_template(
    data: ReportTemplateCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role("admin")),
):
    template = ReportTemplate(
        name=data.name,
        type=ReportType(data.type),
        schedule_cron=data.schedule_cron,
        metrics=data.metrics,
        recipients=data.recipients,
        device_ids=data.device_ids,
        enabled=data.enabled,
    )
    session.add(template)
    await session.commit()
    return {"id": template.id, "name": template.name}


@router.put("/templates/{template_id}")
async def update_template(
    template_id: str,
    data: ReportTemplateUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role("admin")),
):
    template = (await session.execute(
        select(ReportTemplate).where(ReportTemplate.id == template_id)
    )).scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "type":
            setattr(template, field, ReportType(value))
        else:
            setattr(template, field, value)
    await session.commit()
    return {"id": template.id, "name": template.name}


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role("admin")),
):
    template = (await session.execute(
        select(ReportTemplate).where(ReportTemplate.id == template_id)
    )).scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if template.builtin:
        raise HTTPException(status_code=400, detail="Cannot delete builtin template")
    await session.delete(template)
    await session.commit()
    return {"ok": True}


@router.post("/templates/{template_id}/generate")
async def trigger_generate(
    template_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role("admin")),
):
    template = (await session.execute(
        select(ReportTemplate).where(ReportTemplate.id == template_id)
    )).scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    from app.tasks.report import generate_report_task
    generate_report_task.delay(template_id)
    return {"message": "报表生成任务已提交", "template_id": template_id}


@router.get("/history")
async def list_history(
    template_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role("admin", "operator")),
):
    query = select(ReportHistory).order_by(ReportHistory.created_at.desc()).limit(limit)
    if template_id:
        query = query.where(ReportHistory.template_id == template_id)
    result = await session.execute(query)
    history = result.scalars().all()
    return {
        "items": [
            {
                "id": h.id,
                "template_id": h.template_id,
                "title": h.title,
                "period_start": h.period_start.isoformat() if h.period_start else None,
                "period_end": h.period_end.isoformat() if h.period_end else None,
                "file_size": h.file_size,
                "status": h.status.value,
                "error_message": h.error_message,
                "sent_at": h.sent_at.isoformat() if h.sent_at else None,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in history
        ]
    }


@router.get("/history/{history_id}/download")
async def download_report(
    history_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role("admin", "operator")),
):
    history = (await session.execute(
        select(ReportHistory).where(ReportHistory.id == history_id)
    )).scalar_one_or_none()
    if not history:
        raise HTTPException(status_code=404, detail="Report not found")
    if not history.file_path:
        raise HTTPException(status_code=404, detail="Report file not available")

    filepath = Path(history.file_path)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Report file missing from disk")

    return FileResponse(
        path=str(filepath),
        media_type="application/pdf",
        filename=filepath.name,
    )
