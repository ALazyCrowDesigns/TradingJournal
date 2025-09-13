from pydantic_settings import BaseSettings, SettingsConfigDict


class CacheSettings(BaseSettings):
    max_size: int = 1000
    default_ttl: int = 300

    model_config = SettingsConfigDict(env_prefix="CACHE_")


class Settings(BaseSettings):
    polygon_api_key: str | None = None
    fmp_api_key: str | None = None
    app_env: str = "dev"
    db_path: str = "./journal.sqlite3"

    # Nested settings
    cache: CacheSettings = CacheSettings()

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")


settings = Settings()
