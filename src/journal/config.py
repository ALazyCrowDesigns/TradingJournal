from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    polygon_api_key: str | None = None
    fmp_api_key: str | None = None
    app_env: str = "dev"
    db_path: str = "./journal.sqlite3"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")


settings = Settings()
