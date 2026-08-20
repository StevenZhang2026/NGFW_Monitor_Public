from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, Text, JSON, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
import enum

from app.models.database import Base, TimestampMixin, generate_uuid


class AlertType(str, enum.Enum):
    threshold = "threshold"
    anomaly = "anomaly"
    prediction = "prediction"


class Severity(str, enum.Enum):
    critical = "critical"
    warning = "warning"
    info = "info"


class AlertStatus(str, enum.Enum):
    firing = "firing"
    resolved = "resolved"
    acknowledged = "acknowledged"


class AlertRule(Base, TimestampMixin):
    __tablename__ = "alert_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(200))
    metric_name: Mapped[str] = mapped_column(String(100), index=True)
    device_ids: Mapped[list] = mapped_column(JSON, default=list)
    type: Mapped[AlertType] = mapped_column(SAEnum(AlertType))
    condition: Mapped[dict] = mapped_column(JSON)
    severity: Mapped[Severity] = mapped_column(SAEnum(Severity), default=Severity.warning)
    notification_channel_ids: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    rule_id: Mapped[str] = mapped_column(String(36), index=True)
    device_id: Mapped[str] = mapped_column(String(36), index=True)
    metric_name: Mapped[str] = mapped_column(String(100))
    severity: Mapped[Severity] = mapped_column(SAEnum(Severity))
    status: Mapped[AlertStatus] = mapped_column(SAEnum(AlertStatus), default=AlertStatus.firing)
    message: Mapped[str] = mapped_column(Text)
    value: Mapped[str | None] = mapped_column(String(50))
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
