"""Application settings, loaded from environment variables (12-factor).

Every setting has a local-development default so the stack boots with no
.env file. `Settings.validate_for_production` refuses to start a production
process that still uses one of those insecure defaults.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_JWT_SECRET = "local-dev-jwt-secret-change-me-0123456789abcdef"  # noqa: S105
_DEV_ADMIN_KEY = "local-admin-key"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "flash-sale"
    app_env: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"

    # --- PostgreSQL -----------------------------------------------------------
    database_url: str = "postgresql+asyncpg://flash:flash@localhost:55432/flashsale"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout_seconds: float = 5.0
    db_statement_timeout_ms: int = 5000

    # --- Redis ------------------------------------------------------------------
    redis_url: str = "redis://localhost:56379/0"
    redis_max_connections: int = 200
    redis_socket_timeout_seconds: float = 2.0

    # --- RabbitMQ ---------------------------------------------------------------
    rabbitmq_url: str = "amqp://flash:flash@localhost:55672/"
    rabbitmq_namespace: str = "flashsale"
    rabbitmq_queue_type: Literal["classic", "quorum"] = "classic"
    rabbitmq_publish_timeout_seconds: float = 5.0
    rabbitmq_connect_attempts: int = 30

    # --- Auth -------------------------------------------------------------------
    jwt_secret: SecretStr = SecretStr(_DEV_JWT_SECRET)
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 720
    bcrypt_rounds: int = Field(default=12, ge=4, le=16)
    admin_api_key: SecretStr = SecretStr(_DEV_ADMIN_KEY)

    # --- HTTP -------------------------------------------------------------------
    cors_origins: str = ""
    # Number of trusted proxies that append to X-Forwarded-For in front of the
    # API: 1 locally (NGINX), 2 on AWS (CloudFront -> ALB).
    client_ip_trusted_hops: int = Field(default=1, ge=0)

    # --- Rate limiting (sliding window, per window) -----------------------------
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = 10
    rate_limit_checkout_per_user: int = 5
    rate_limit_checkout_per_ip: int = 200
    rate_limit_auth_per_ip: int = 30

    # --- Sale status fan-out ----------------------------------------------------
    broadcaster_interval_ms: int = 500
    sse_heartbeat_seconds: int = 15
    sse_max_connections_per_process: int = 5000
    sale_cache_ttl_seconds: float = 5.0
    order_poll_after_ms: int = 1000
    order_status_ttl_seconds: int = 86_400

    # --- Worker -----------------------------------------------------------------
    worker_prefetch: int = Field(default=16, ge=1)
    worker_max_retries: int = 5
    worker_retry_delay_ms: int = 2000
    worker_metrics_port: int = 9100
    worker_shutdown_grace_seconds: float = 25.0

    # --- Seed -------------------------------------------------------------------
    seed_sale_stock: int = 500
    seed_sale_starts_in_seconds: int = 120
    seed_sale_duration_minutes: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @model_validator(mode="after")
    def validate_for_production(self) -> "Settings":
        if self.is_production:
            if self.jwt_secret.get_secret_value() == _DEV_JWT_SECRET:
                raise ValueError("JWT_SECRET must be set in production")
            if self.admin_api_key.get_secret_value() == _DEV_ADMIN_KEY:
                raise ValueError("ADMIN_API_KEY must be set in production")
            if len(self.jwt_secret.get_secret_value()) < 32:
                raise ValueError("JWT_SECRET must be at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
