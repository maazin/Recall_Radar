from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Schemes that managed Postgres providers hand out, mapped to the driver this
# app actually installs. Neon, Render, Supabase and Heroku all give you one of
# these, and none of them name a driver — SQLAlchemy then defaults to psycopg2,
# which is not in requirements.txt, and the process dies at import with
# "No module named 'psycopg2'".
_DRIVERLESS_SCHEMES = ("postgresql://", "postgres://")
_DRIVER_SCHEME = "postgresql+psycopg://"


class Settings(BaseSettings):
    """Runtime configuration, read from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _ignore_blank_env_values(cls, data: Any) -> Any:
        """Treat an empty environment variable as absent.

        GitHub Actions substitutes an unset secret as the empty string rather
        than omitting the variable, so a workflow that forwards optional
        secrets — `SMTP_PORT: ${{ secrets.SMTP_PORT }}` — exports `SMTP_PORT=""`
        when you have not configured mail. Pydantic then tries to parse "" as an
        int and the process dies at import, nowhere near the actual cause. The
        same thing happens with a key left blank in a dashboard or a `.env`.

        Dropping blanks here lets the field default apply, which is what an
        unset variable is supposed to mean.
        """
        if isinstance(data, dict):
            return {
                key: value
                for key, value in data.items()
                if not (isinstance(value, str) and not value.strip())
            }
        return data

    database_url: str = "postgresql+psycopg://recallradar:recallradar@localhost:5432/recallradar"

    @field_validator("database_url")
    @classmethod
    def _ensure_psycopg_driver(cls, value: str) -> str:
        """Pin the psycopg 3 driver onto a provider-supplied connection string.

        Requiring operators to hand-edit the scheme was a deployment footgun:
        the paste is correct in every other respect and the failure surfaces as
        a missing module rather than a bad URL. A URL that already names a
        driver is left alone, so `postgresql+asyncpg://` or similar still works.
        """
        url = value.strip()
        for scheme in _DRIVERLESS_SCHEMES:
            if url.startswith(scheme):
                return _DRIVER_SCHEME + url[len(scheme) :]
        return url

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
