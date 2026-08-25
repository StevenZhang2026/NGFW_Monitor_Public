from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "ngfw-monitor"
    debug: bool = False
    secret_key: str = "change-me"

    # Database
    database_url: str = "postgresql+asyncpg://ngfw:changeme@db:5432/ngfw_monitor"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Data retention
    retention_raw_days: int = 365
    compress_after_days: int = 7

    # Collector
    collector_concurrency: int = 5
    collector_timeout: int = 30

    # Collection task guard rails. A per-device lock stops the next beat tick
    # from starting a second collection of a device that is still busy.
    # Ordering matters: soft < hard < lock TTL, so the task always releases its
    # own lock and the TTL is only a crash backstop. `expires` is shorter than
    # the beat interval — a task still queued when its replacement is dispatched
    # is stale, and running it would only add load.
    collect_soft_time_limit: int = 240
    collect_time_limit: int = 280
    collect_lock_ttl: int = 300
    collect_task_expires: int = 55

    # JWT
    jwt_secret_key: str = "change-me"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 7

    # Initial admin
    admin_username: str = "admin"
    admin_password: str = "change-me"
    admin_email: str = "admin@example.com"

    # Feishu (optional)
    feishu_webhook_url: str | None = None
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None

    # Email (optional)
    smtp_host: str | None = None
    smtp_port: int = 465
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_use_ssl: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
