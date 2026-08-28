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

    # How often collections are dispatched. This is the finest cadence the
    # system can achieve regardless of a metric's configured interval, so the
    # collection-health check measures a device's headroom against it.
    collect_beat_interval: int = 60

    # How often the collection pipeline checks itself for falling behind.
    collection_health_interval: int = 120

    # JWT
    jwt_secret_key: str = "change-me"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 7

    # Initial admin
    admin_username: str = "admin"
    admin_password: str = "change-me"
    admin_email: str = "admin@example.com"

    # Outbound TLS, for internet destinations only (LLM provider, chat webhooks).
    # Device-side calls are a separate matter and stay unverified on purpose —
    # a PA appliance on a management LAN presents a self-signed certificate.
    # Defaults are correct for a real deployment; outbound_ca_bundle exists only
    # for a dev machine on GlobalProtect, where a TLS-inspecting proxy re-signs
    # the chain with a private root CA.
    outbound_tls_verify: bool = True
    outbound_ca_bundle: str | None = None

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
