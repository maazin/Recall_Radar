"""Shared test setup.

DATABASE_URL is pinned to the test database *before* any app module is imported,
because `app.config.Settings` reads the environment at import time.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://recallradar:recallradar@localhost:5432/recallradar_test",
)
os.environ.setdefault("SMTP_HOST", "")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import Base, SessionLocal, engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.notify.email import EmailSender  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Read a saved source snapshot. Tests never touch a live endpoint."""
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    with SessionLocal() as session:
        session.execute(
            text("TRUNCATE advisories, subscriptions RESTART IDENTITY CASCADE")
        )
        session.commit()
        yield session


@pytest.fixture
def sender() -> EmailSender:
    """A fresh sender whose `sent` list can be asserted against."""
    return EmailSender()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
