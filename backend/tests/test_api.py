"""Feed, search and subscription endpoints."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import (
    AGENCY_CDC,
    AGENCY_FDA,
    AGENCY_USDA_FSIS,
    CATEGORY_GROCERY,
    CATEGORY_RESTAURANT,
    STATUS_ACTIVE,
    STATUS_RESOLVED,
    TYPE_OUTBREAK,
    TYPE_RECALL,
    Advisory,
    Subscription,
)


@pytest.fixture
def seeded(db):
    rows = [
        Advisory(
            source_uid="FDA:R-1",
            type=TYPE_RECALL,
            source_agency=AGENCY_FDA,
            category=CATEGORY_GROCERY,
            brand_or_chain="Acme Foods",
            description="Peanut butter, 16 oz jars.",
            reason="Undeclared allergen: peanuts",
            severity="Class I",
            states_affected=["CA", "NV"],
            status=STATUS_ACTIVE,
            started_at="2026-07-20",
            updated_at="2026-07-20",
            source_url="https://api.fda.gov/food/enforcement.json?search=recall_number:%22R-1%22",
        ),
        Advisory(
            source_uid="USDA-FSIS:R-2",
            type=TYPE_RECALL,
            source_agency=AGENCY_USDA_FSIS,
            category=CATEGORY_RESTAURANT,
            brand_or_chain="Harbor Grill Restaurant Group",
            description="Chicken salad tubs.",
            reason="Misbranding",
            severity="Class II",
            states_affected=["CA"],
            status=STATUS_RESOLVED,
            started_at="2026-07-10",
            updated_at="2026-07-15",
            source_url="https://www.fsis.usda.gov/recalls-alerts/harbor-grill",
        ),
        Advisory(
            source_uid="CDC:listeria",
            type=TYPE_OUTBREAK,
            source_agency=AGENCY_CDC,
            category=CATEGORY_GROCERY,
            brand_or_chain="Sliced Deli Meat",
            description="CDC lists 1 active investigation for Listeria monocytogenes.",
            reason="Listeria monocytogenes",
            severity=None,
            states_affected=[],
            status=STATUS_ACTIVE,
            started_at="2026-07-25",
            updated_at="2026-07-25",
            source_url="https://www.cdc.gov/listeria/outbreaks/deli-meat.html",
        ),
    ]
    db.add_all(rows)
    db.commit()
    return rows


class TestFeed:
    def test_returns_recalls_and_outbreaks_together(self, client, seeded):
        body = client.get("/api/advisories").json()

        assert body["total"] == 3
        assert {i["type"] for i in body["items"]} == {TYPE_RECALL, TYPE_OUTBREAK}

    def test_sorted_most_recent_first(self, client, seeded):
        items = client.get("/api/advisories").json()["items"]
        dates = [i["started_at"] for i in items]

        assert dates == sorted(dates, reverse=True)
        assert dates[0] == "2026-07-25"

    def test_every_item_carries_agency_and_source_link(self, client, seeded):
        for item in client.get("/api/advisories").json()["items"]:
            assert item["source_agency"]
            assert item["source_url"].startswith("https://")

    def test_category_filter(self, client, seeded):
        body = client.get("/api/advisories", params={"category": CATEGORY_RESTAURANT}).json()

        assert body["total"] == 1
        assert body["items"][0]["brand_or_chain"] == "Harbor Grill Restaurant Group"

    def test_grocery_category_filter(self, client, seeded):
        body = client.get("/api/advisories", params={"category": CATEGORY_GROCERY}).json()
        assert body["total"] == 2

    def test_type_filter(self, client, seeded):
        body = client.get("/api/advisories", params={"type": TYPE_OUTBREAK}).json()
        assert body["total"] == 1

    def test_status_filter(self, client, seeded):
        body = client.get("/api/advisories", params={"status": STATUS_ACTIVE}).json()
        assert body["total"] == 2

    def test_free_text_query_spans_reason(self, client, seeded):
        body = client.get("/api/advisories", params={"q": "listeria"}).json()
        assert body["total"] == 1

    def test_invalid_category_is_rejected(self, client, seeded):
        assert client.get("/api/advisories", params={"category": "bakery"}).status_code == 422

    def test_pagination(self, client, seeded):
        body = client.get("/api/advisories", params={"limit": 2, "offset": 0}).json()
        assert body["total"] == 3
        assert len(body["items"]) == 2

        page_two = client.get("/api/advisories", params={"limit": 2, "offset": 2}).json()
        assert len(page_two["items"]) == 1


class TestSearch:
    def test_finds_brand_by_partial_name(self, client, seeded):
        body = client.get("/api/advisories/search", params={"q": "acme"}).json()

        assert body["total"] == 1
        assert body["items"][0]["brand_or_chain"] == "Acme Foods"

    def test_is_case_insensitive(self, client, seeded):
        assert client.get("/api/advisories/search", params={"q": "HARBOR"}).json()["total"] == 1

    def test_matches_chain_names(self, client, seeded):
        body = client.get("/api/advisories/search", params={"q": "Harbor Grill"}).json()
        assert body["items"][0]["category"] == CATEGORY_RESTAURANT

    def test_matches_description_text(self, client, seeded):
        # Product text is searchable alongside brands and hazards.
        assert client.get("/api/advisories/search", params={"q": "peanut butter"}).json()["total"] == 1

    def test_unknown_brand_returns_empty(self, client, seeded):
        assert client.get("/api/advisories/search", params={"q": "nonesuch"}).json()["total"] == 0

    def test_status_filter_narrows_results(self, client, seeded):
        body = client.get(
            "/api/advisories/search", params={"q": "harbor", "status": STATUS_ACTIVE}
        ).json()
        assert body["total"] == 0

    def test_empty_query_is_rejected(self, client, seeded):
        assert client.get("/api/advisories/search", params={"q": ""}).status_code == 422


@pytest.fixture
def notifications_on(monkeypatch):
    """Pretend a mail provider is configured.

    Tests otherwise run with smtp_host unset, which is the state where the API
    declines subscriptions outright.
    """
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")


class TestConfig:
    def test_reports_notifications_off_when_no_mail_host(self, client):
        body = client.get("/api/config").json()
        assert body["notifications_enabled"] is False

    def test_reports_notifications_on_once_configured(self, client, notifications_on):
        body = client.get("/api/config").json()
        assert body["notifications_enabled"] is True


class TestSubscriptionsWithoutMailConfigured:
    """The deployment must not collect addresses it cannot write to."""

    def test_subscribing_is_refused(self, client):
        response = client.post("/api/subscriptions", json={"email": "reader@example.com"})
        assert response.status_code == 503

    def test_refusal_says_nothing_was_stored(self, client):
        detail = client.post(
            "/api/subscriptions", json={"email": "reader@example.com"}
        ).json()["detail"]
        assert "No address was stored" in detail

    def test_no_row_is_written(self, client, db):
        client.post("/api/subscriptions", json={"email": "ghost@example.com"})
        assert not db.scalar(
            select(Subscription).where(Subscription.email == "ghost@example.com")
        )

    def test_a_malformed_address_is_still_rejected_first(self, client):
        # Validation runs before the availability check, so a bad request stays
        # a 422 rather than being masked as a 503.
        assert client.post("/api/subscriptions", json={"email": "nope"}).status_code == 422


@pytest.mark.usefixtures("notifications_on")
class TestSubscriptions:
    def test_creates_a_subscription(self, client, db):
        response = client.post(
            "/api/subscriptions",
            json={"email": "reader@example.com", "category_filter": CATEGORY_GROCERY},
        )

        assert response.status_code == 201
        assert response.json()["email"] == "reader@example.com"
        assert db.scalar(select(Subscription).where(Subscription.email == "reader@example.com"))

    def test_accepts_a_bare_email(self, client):
        response = client.post("/api/subscriptions", json={"email": "plain@example.com"})
        assert response.status_code == 201
        assert response.json()["category_filter"] is None

    def test_rejects_an_invalid_email(self, client):
        assert client.post("/api/subscriptions", json={"email": "not-an-email"}).status_code == 422

    def test_rejects_an_unknown_category(self, client):
        response = client.post(
            "/api/subscriptions", json={"email": "a@example.com", "category_filter": "bakery"}
        )
        assert response.status_code == 422

    def test_resubscribing_does_not_duplicate(self, client, db):
        payload = {"email": "dupe@example.com", "keyword_filter": "acme"}
        first = client.post("/api/subscriptions", json=payload).json()
        second = client.post("/api/subscriptions", json=payload).json()

        assert first["id"] == second["id"]
        assert len(db.scalars(select(Subscription)).all()) == 1

    def test_blank_keyword_is_stored_as_null(self, client):
        response = client.post(
            "/api/subscriptions", json={"email": "blank@example.com", "keyword_filter": "   "}
        )
        assert response.json()["keyword_filter"] is None


def test_stats(client, seeded):
    body = client.get("/api/stats").json()

    assert body == {
        "total": 3,
        "active": 2,
        "recalls": 2,
        "outbreaks": 1,
        "grocery": 2,
        "restaurant": 1,
    }


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_root_carries_the_aggregator_disclaimer(client):
    body = client.get("/").json()
    assert "Not an alerting authority" in body["disclaimer"]
