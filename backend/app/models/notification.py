from sqlalchemy import String, Boolean, JSON, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
import enum

from app.models.database import Base, TimestampMixin, generate_uuid


class ChannelType(str, enum.Enum):
    feishu = "feishu"
    wechat = "wechat"
    email = "email"
    webhook = "webhook"


class NotificationChannel(Base, TimestampMixin):
    __tablename__ = "notification_channels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[ChannelType] = mapped_column(SAEnum(ChannelType))
    config: Mapped[dict] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
