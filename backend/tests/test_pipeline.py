"""Upsert diffing and the subscription email trigger."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.ingest.base import NormalizedAdvisory
from app.ingest.pipeline import ingest, notify_subscribers, upsert_advisories
from app.models import (
    AGENCY_FDA,
    CATEGORY_GROCERY,
    CATEGORY_RESTAURANT,
    STATUS_ACTIVE,
    STATUS_RESOLVED,
    TYPE_RECALL,
    Advisory,
    Subscription,
)


def make_advisory(uid: str = "FDA:TEST-1", **overrides) -> NormalizedAdvisory:
    defaults = {
        "source_uid": uid,
        "type": TYPE_RECALL,
        "source_agency": AGENCY_FDA,
        "category": CATEGORY_GROCERY,
        "brand_or_chain": "Acme Foods",
        "description": "Acme peanut butter, 16 oz jars.",
        "reason": "Undeclared allergen: peanuts",
        "severity": "Class I",
        "states_affected": ["CA", "NV"],
        "status": STATUS_ACTIVE,
        "started_at": "2026-07-01",
        "updated_at": "2026-07-01",
        "source_url": "https://api.fda.gov/food/enforcement.json?search=recall_number:%22TEST-1%22",
    }
    defaults.update(overrides)
    return NormalizedAdvisory(**defaults)


def subscribe(db, email="reader@example.com", category=None, keyword=None) -> Subscription:
    subscription = Subscription(
        email=email,
        category_filter=category,
        keyword_filter=keyword,
        created_at="2026-07-01",
    )
    db.add(subscription)
    db.commit()
    return subscription


class TestUpsert:
    def test_inserts_new_advisories(self, db):
        notable = upsert_advisories(db, [make_advisory()])

        assert len(notable) == 1
        assert db.scalar(select(Advisory).where(Advisory.source_uid == "FDA:TEST-1"))

    def test_reingesting_unchanged_records_is_not_notable(self, db):
        upsert_advisories(db, [make_advisory()])
        notable = upsert_advisories(db, [make_advisory()])

        # A weekly re-run must not re-notify the whole feed.
        assert notable == []
        assert db.scalar(select(Advisory).where(Advisory.source_uid == "FDA:TEST-1"))

    def test_upsert_does_not_duplicate_rows(self, db):
        upsert_advisories(db, [make_advisory()])
        upsert_advisories(db, [make_advisory(brand_or_chain="Acme Foods Inc.")])

        rows = db.scalars(select(Advisory)).all()
        assert len(rows) == 1
        assert rows[0].brand_or_chain == "Acme Foods Inc."

    def test_edits_alone_are_not_notable(self, db):
        upsert_advisories(db, [make_advisory()])
        notable = upsert_advisories(db, [make_advisory(description="Corrected text.")])
        assert notable == []

    def test_resolved_to_active_is_notable(self, db):
        upsert_advisories(db, [make_advisory(status=STATUS_RESOLVED)])
        notable = upsert_advisories(db, [make_advisory(status=STATUS_ACTIVE)])

        assert [a.source_uid for a in notable] == ["FDA:TEST-1"]

    def test_active_to_resolved_is_not_notable(self, db):
        upsert_advisories(db, [make_advisory(status=STATUS_ACTIVE)])
        notable = upsert_advisories(db, [make_advisory(status=STATUS_RESOLVED)])
        assert notable == []

    def test_empty_batch_is_a_no_op(self, db):
        assert upsert_advisories(db, []) == []


class TestNotifications:
    def test_seeded_advisory_triggers_an_email(self, db, sender):
        subscribe(db)

        _, sent = ingest(db, [make_advisory()], sender=sender)

        assert sent == 1
        assert len(sender.sent) == 1
        to, subject, body = sender.sent[0]
        assert to == "reader@example.com"
        assert "1 new advisory" in subject
        assert "Acme Foods" in body

    def test_email_attributes_the_agency_and_links_to_the_record(self, db, sender):
        subscribe(db)
        ingest(db, [make_advisory()], sender=sender)

        _, _, body = sender.sent[0]
        assert "Published by FDA:" in body
        assert "https://api.fda.gov/food/enforcement.json" in body
        # Compliance: the digest must not read as RecallRadar issuing an alert.
        assert "does not issue health alerts" in body

    def test_category_filter_excludes_non_matching(self, db, sender):
        subscribe(db, category=CATEGORY_RESTAURANT)

        ingest(db, [make_advisory(category=CATEGORY_GROCERY)], sender=sender)

        assert sender.sent == []

    def test_category_filter_includes_matching(self, db, sender):
        subscribe(db, category=CATEGORY_GROCERY)
        ingest(db, [make_advisory(category=CATEGORY_GROCERY)], sender=sender)
        assert len(sender.sent) == 1

    def test_keyword_filter_matches_brand_case_insensitively(self, db, sender):
        subscribe(db, keyword="acme")
        ingest(db, [make_advisory()], sender=sender)
        assert len(sender.sent) == 1

    def test_keyword_filter_matches_reason(self, db, sender):
        subscribe(db, keyword="peanuts")
        ingest(db, [make_advisory()], sender=sender)
        assert len(sender.sent) == 1

    def test_keyword_filter_excludes_non_matching(self, db, sender):
        subscribe(db, keyword="listeria")
        ingest(db, [make_advisory()], sender=sender)
        assert sender.sent == []

    def test_subscription_with_no_filters_matches_everything(self, db, sender):
        subscribe(db)
        ingest(db, [make_advisory(category=CATEGORY_RESTAURANT)], sender=sender)
        assert len(sender.sent) == 1

    def test_each_subscriber_gets_only_their_matches(self, db, sender):
        subscribe(db, email="grocery@example.com", category=CATEGORY_GROCERY)
        subscribe(db, email="dining@example.com", category=CATEGORY_RESTAURANT)

        ingest(
            db,
            [
                make_advisory("FDA:G-1", category=CATEGORY_GROCERY, brand_or_chain="Acme"),
                make_advisory("FDA:R-1", category=CATEGORY_RESTAURANT, brand_or_chain="Chipotle"),
            ],
            sender=sender,
        )

        by_recipient = {to: body for to, _, body in sender.sent}
        assert set(by_recipient) == {"grocery@example.com", "dining@example.com"}
        assert "Acme" in by_recipient["grocery@example.com"]
        assert "Chipotle" not in by_recipient["grocery@example.com"]
        assert "Chipotle" in by_recipient["dining@example.com"]

    def test_reingest_does_not_resend(self, db, sender):
        subscribe(db)
        ingest(db, [make_advisory()], sender=sender)
        ingest(db, [make_advisory()], sender=sender)

        assert len(sender.sent) == 1

    def test_no_subscribers_means_no_sends(self, db, sender):
        _, sent = ingest(db, [make_advisory()], sender=sender)
        assert sent == 0

    def test_nothing_notable_means_no_sends(self, db, sender):
        subscribe(db)
        assert notify_subscribers(db, [], sender=sender) == 0
        assert sender.sent == []


@pytest.mark.parametrize("count,expected", [(1, "1 new advisory"), (2, "2 new advisories")])
def test_subject_pluralization(db, sender, count, expected):
    subscribe(db)
    batch = [make_advisory(f"FDA:P-{i}") for i in range(count)]
    ingest(db, batch, sender=sender)

    assert expected in sender.sent[0][1]
