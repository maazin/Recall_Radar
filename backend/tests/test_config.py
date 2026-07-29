"""Connection-string handling.

The driverless-scheme case is not hypothetical: it took the first Render deploy
down. Neon hands out `postgresql://`, SQLAlchemy defaults that to psycopg2,
psycopg2 is not installed, and the process dies at import time with a missing
module rather than anything that points at the URL.
"""

import pytest

from app.config import Settings


@pytest.mark.parametrize(
    "given",
    [
        "postgresql://user:pw@host/db?sslmode=require",
        # Heroku still issues the older scheme.
        "postgres://user:pw@host/db?sslmode=require",
    ],
)
def test_driverless_scheme_gets_the_psycopg_driver(given):
    settings = Settings(database_url=given)
    assert settings.database_url.startswith("postgresql+psycopg://")
    # Everything after the scheme survives untouched.
    assert settings.database_url.endswith("user:pw@host/db?sslmode=require")


def test_explicit_psycopg_url_is_unchanged():
    url = "postgresql+psycopg://user:pw@host/db?sslmode=require"
    assert Settings(database_url=url).database_url == url


def test_another_named_driver_is_left_alone():
    """Only the driverless forms are rewritten; a deliberate choice is honoured."""
    url = "postgresql+asyncpg://user:pw@host/db"
    assert Settings(database_url=url).database_url == url


def test_surrounding_whitespace_is_trimmed():
    """Pasting into a dashboard field routinely picks up a trailing newline."""
    settings = Settings(database_url="  postgresql://user:pw@host/db\n")
    assert settings.database_url == "postgresql+psycopg://user:pw@host/db"


def test_default_is_already_driver_qualified():
    assert Settings().database_url.startswith("postgresql+psycopg://")


class TestBlankEnvironmentValues:
    """An unset GitHub Actions secret arrives as "", not as an absent variable.

    `SMTP_PORT: ${{ secrets.SMTP_PORT }}` in a workflow exports SMTP_PORT="" when
    the secret does not exist. That took down the first scheduled ingest run:
    pydantic could not parse "" as an int and the process died at import.
    """

    def test_blank_int_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv("SMTP_PORT", "")
        assert Settings().smtp_port == 587

    def test_blank_optional_string_reads_as_unset(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "")
        assert Settings().smtp_host is None

    def test_whitespace_only_is_also_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("SMTP_PORT", "   ")
        assert Settings().smtp_port == 587

    def test_blank_bool_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv("SMTP_USE_TLS", "")
        assert Settings().smtp_use_tls is True

    def test_blank_database_url_falls_back_rather_than_erroring(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "")
        assert Settings().database_url.startswith("postgresql+psycopg://")

    def test_a_whole_workflow_of_unset_secrets_still_boots(self, monkeypatch):
        """Every optional secret the ingest workflow forwards, all unset."""
        for name in (
            "OPENFDA_API_KEY",
            "SMTP_HOST",
            "SMTP_PORT",
            "SMTP_USER",
            "SMTP_PASSWORD",
            "EMAIL_FROM",
            "APP_BASE_URL",
        ):
            monkeypatch.setenv(name, "")

        settings = Settings()
        assert settings.smtp_port == 587
        assert settings.smtp_host is None
        assert settings.openfda_api_key is None
        assert settings.app_base_url.startswith("http")

    def test_real_values_are_still_read(self, monkeypatch):
        monkeypatch.setenv("SMTP_PORT", "2525")
        monkeypatch.setenv("SMTP_HOST", "smtp-relay.brevo.com")
        settings = Settings()
        assert settings.smtp_port == 2525
        assert settings.smtp_host == "smtp-relay.brevo.com"
