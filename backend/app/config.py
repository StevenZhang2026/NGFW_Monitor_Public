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
