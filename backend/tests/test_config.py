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
