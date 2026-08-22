from sqlalchemy import String, Boolean, Text, Enum as SAEnum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
import enum

from app.models.database import Base, TimestampMixin, generate_uuid


class AuthType(str, enum.Enum):
    api_key = "api_key"
    ssh = "ssh"
    both = "both"


class DeviceStatus(str, enum.Enum):
    online = "online"
    offline = "offline"
    unknown = "unknown"


class Device(Base, TimestampMixin):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    hostname: Mapped[str] = mapped_column(String(255))
    model: Mapped[str | None] = mapped_column(String(50))
    serial: Mapped[str | None] = mapped_column(String(50))
    panos_version: Mapped[str | None] = mapped_column(String(20))
    ha_state: Mapped[str | None] = mapped_column(String(20))

    auth_type: Mapped[AuthType] = mapped_column(SAEnum(AuthType), default=AuthType.api_key)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    ssh_username: Mapped[str | None] = mapped_column(String(50))
    ssh_password_encrypted: Mapped[str | None] = mapped_column(Text)

    group_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("device_groups.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[DeviceStatus] = mapped_column(SAEnum(DeviceStatus), default=DeviceStatus.unknown)
    collect_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen: Mapped[str | None] = mapped_column(String(30))

    @property
    def api_key_decrypted(self) -> str | None:
        # TODO: implement real encryption/decryption
        return self.api_key_encrypted

    @property
    def ssh_password_decrypted(self) -> str | None:
        # TODO: implement real encryption/decryption
        return self.ssh_password_encrypted
