from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base, TimestampMixin, generate_uuid


class DeviceGroup(Base, TimestampMixin):
    __tablename__ = "device_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserGroupScope(Base):
    __tablename__ = "user_group_scopes"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("device_groups.id", ondelete="CASCADE"), primary_key=True
    )
