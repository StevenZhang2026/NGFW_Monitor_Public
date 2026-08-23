import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings

engine = create_async_engine(settings.database_url, echo=settings.debug)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )


def generate_uuid() -> str:
    return str(uuid.uuid4())


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session


async def init_db():
    from sqlalchemy import text
    from app.models import User, Device, MetricDefinition, MetricData, AlertRule, AlertEvent, NotificationChannel  # noqa: F401
    from app.models.setting import SystemSetting  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("SELECT create_hypertable('metric_data', 'timestamp', if_not_exists => TRUE)")
        )

    # Create initial admin user if not exists
    from app.auth.security import hash_password
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(select(User).where(User.username == settings.admin_username))
        if not result.scalar_one_or_none():
            admin = User(
                username=settings.admin_username,
                email=settings.admin_email,
                hashed_password=hash_password(settings.admin_password),
                role="admin",
                is_active=True,
            )
            session.add(admin)
            await session.commit()

    # Load builtin metrics if not exists
    await _load_builtin_metrics()


async def _load_builtin_metrics():
    import yaml
    import os
    from app.models.metric import MetricDefinition

    builtin_path = os.path.join(os.path.dirname(__file__), "..", "metrics", "builtin.yaml")
    if not os.path.exists(builtin_path):
        return

    with open(builtin_path) as f:
        metrics = yaml.safe_load(f)

    async with async_session() as session:
        from sqlalchemy import select
        for m in metrics:
            result = await session.execute(
                select(MetricDefinition).where(MetricDefinition.name == m["name"])
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.command = m["command"]
                existing.parser = m["parser"]
                existing.collector = m["collector"]
            else:
                metric = MetricDefinition(
                    name=m["name"],
                    display_name=m["display_name"],
                    category=m["category"],
                    collector=m["collector"],
                    command=m["command"],
                    parser=m["parser"],
                    data_type=m.get("data_type", "gauge"),
                    unit=m.get("unit", ""),
                    chart_type=m.get("chart_type", "line"),
                    interval=m.get("interval", 60),
                    interval_min=m.get("interval_min", 10),
                    interval_max=m.get("interval_max", 300),
                    enabled=True,
                    builtin=True,
                )
                session.add(metric)
        await session.commit()
