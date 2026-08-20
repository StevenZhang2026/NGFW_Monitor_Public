from datetime import datetime

from sqlalchemy import String, Integer, Boolean, Float, DateTime, Text, JSON, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
import enum

from app.models.database import Base, TimestampMixin, generate_uuid


class DataType(str, enum.Enum):
    gauge = "gauge"
    counter = "counter"


class ChartType(str, enum.Enum):
    line = "line"
    area = "area"
    bar = "bar"


class MetricDefinition(Base, TimestampMixin):
    __tablename__ = "metric_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50), index=True)

    collector: Mapped[str] = mapped_column(String(50))
    command: Mapped[str] = mapped_column(Text)
    parser: Mapped[dict] = mapped_column(JSON)

    data_type: Mapped[DataType] = mapped_column(SAEnum(DataType), default=DataType.gauge)
    unit: Mapped[str] = mapped_column(String(20), default="")
    chart_type: Mapped[ChartType] = mapped_column(SAEnum(ChartType), default=ChartType.line)

    interval: Mapped[int] = mapped_column(Integer, default=60)
    interval_min: Mapped[int] = mapped_column(Integer, default=10)
    interval_max: Mapped[int] = mapped_column(Integer, default=300)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class MetricData(Base):
    __tablename__ = "metric_data"

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    metric_name: Mapped[str] = mapped_column(String(100), primary_key=True, index=True)
    value: Mapped[float] = mapped_column(Float)
    labels: Mapped[dict | None] = mapped_column(JSON)
