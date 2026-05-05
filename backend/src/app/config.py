import secrets

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    audio_storage_root: str = "/data/audio"
    processor_enabled: bool = True
    processor_poll_interval_seconds: float = 2.0
    processor_batch_size: int = 1
    processor_lease_seconds: int = 30
    processor_heartbeat_interval_seconds: int = 10
    processor_max_attempts: int = 3
    auth_token_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    auth_token_ttl_seconds: int = 86400
    storysync_admin_email: str = "admin@mail.com"
    storysync_admin_password: str = ""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
