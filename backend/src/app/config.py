from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    audio_storage_root: str = "/data/audio"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
