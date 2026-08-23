import enum

from sqlalchemy import String, Boolean, Text, Integer, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base, TimestampMixin, generate_uuid


class ReportType(str, enum.Enum):
    weekly = "weekly"
    monthly = "monthly"
    custom = "custom"


class ReportStatus(str, enum.Enum):
    generating = "generating"
    success = "success"
    failed = "failed"


class ReportTemplate(Base, TimestampMixin):
    __tablename__ = "report_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[ReportType] = mapped_column(SAEnum(ReportType), default=ReportType.weekly)
    schedule_cron: Mapped[str | None] = mapped_column(String(50), nullable=True)
    metrics: Mapped[dict] = mapped_column(JSONB, default=list)
    recipients: Mapped[dict] = mapped_column(JSONB, default=list)
    device_ids: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class ReportHistory(Base):
    __tablename__ = "report_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("report_templates.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    period_start: Mapped[str] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[str] = mapped_column(DateTime(timezone=True))
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[ReportStatus] = mapped_column(SAEnum(ReportStatus), default=ReportStatus.generating)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        default=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        server_default=__import__("sqlalchemy").func.now(),
    )
