from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://recallradar:recallradar@localhost:5432/recallradar"

    # openFDA works without a key at low volume; set one if you hit rate limits.
    openfda_api_key: str | None = None

    # How far back each ingestion run looks, in days.
    ingest_lookback_days: int = 120

    # Email delivery. When smtp_host is unset the notifier logs instead of sending,
    # which is what local dev and CI use.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    email_from: str = "RecallRadar <notifications@recallradar.example>"

    # Used to build links back into the app from emails.
    app_base_url: str = "http://localhost:5173"

    cors_origins: str = "http://localhost:5173"

    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
