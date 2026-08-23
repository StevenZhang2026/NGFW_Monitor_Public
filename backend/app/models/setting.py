from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base, TimestampMixin, generate_uuid


class SystemSetting(Base, TimestampMixin):
    __tablename__ = "system_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")
