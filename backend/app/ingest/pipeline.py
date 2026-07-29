"""Upsert normalized advisories and notify matching subscribers.

The notification trigger lives here rather than in the API because the PRD wants
sends driven by the ingestion diff: only genuinely new advisories, or ones that
have flipped from resolved back to active, are worth emailing about. A routine
re-ingest of an unchanged record must stay silent, otherwise every weekly run
would re-notify the entire feed.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.base import NormalizedAdvisory
from app.models import STATUS_ACTIVE, Advisory, Subscription
from app.notify.email import EmailSender, default_sender, render_digest

logger = logging.getLogger(__name__)

# Fields refreshed on every run when a record already exists.
_MUTABLE_FIELDS = (
    "type",
    "source_agency",
    "category",
    "brand_or_chain",
    "description",
    "reason",
    "severity",
    "states_affected",
    "status",
    "started_at",
    "updated_at",
    "source_url",
)


def upsert_advisories(
    db: Session, advisories: list[NormalizedAdvisory]
) -> list[Advisory]:
    """Insert or update advisories, returning the ones worth notifying about.

    "Worth notifying about" means either newly inserted, or transitioned from
    resolved back to active. Unchanged and merely-edited records are not
    returned.
    """
    if not advisories:
        return []

    uids = [a.source_uid for a in advisories]
    existing = {
        row.source_uid: row
        for row in db.scalars(select(Advisory).where(Advisory.source_uid.in_(uids)))
    }

    notable: list[Advisory] = []

    for incoming in advisories:
        current = existing.get(incoming.source_uid)

        if current is None:
            record = Advisory(
                source_uid=incoming.source_uid,
                **{field: getattr(incoming, field) for field in _MUTABLE_FIELDS},
            )
            db.add(record)
            notable.append(record)
            continue

        became_active = (
            current.status != STATUS_ACTIVE and incoming.status == STATUS_ACTIVE
        )
        for field in _MUTABLE_FIELDS:
            setattr(current, field, getattr(incoming, field))
        if became_active:
            notable.append(current)

    db.commit()

    logger.info(
        "Upserted %s advisories (%s new or newly active)", len(advisories), len(notable)
    )
    return notable


def _matches(advisory: Advisory, subscription: Subscription) -> bool:
    """Does this advisory satisfy the subscription's filters?

    A null filter means "no constraint", so a subscription with neither filter
    set matches everything.
    """
    if subscription.category_filter and advisory.category != subscription.category_filter:
        return False

    if subscription.keyword_filter:
        needle = subscription.keyword_filter.strip().lower()
        haystack = " ".join(
            filter(
                None,
                [advisory.brand_or_chain, advisory.description, advisory.reason],
            )
        ).lower()
        if needle not in haystack:
            return False

    return True


def notify_subscribers(
    db: Session,
    advisories: list[Advisory],
    sender: EmailSender | None = None,
) -> int:
    """Email each subscriber the subset of `advisories` matching their filters.

    Returns the number of messages sent.
    """
    if not advisories:
        return 0

    sender = sender or default_sender
    subscriptions = list(db.scalars(select(Subscription)))
    sent = 0

    for subscription in subscriptions:
        matches = [a for a in advisories if _matches(a, subscription)]
        if not matches:
            continue
        subject, body = render_digest(matches)
        sender.send(subscription.email, subject, body)
        sent += 1

    logger.info("Sent %s subscription notification(s)", sent)
    return sent


def ingest(
    db: Session,
    advisories: list[NormalizedAdvisory],
    sender: EmailSender | None = None,
) -> tuple[int, int]:
    """Upsert a parsed batch and notify on the diff.

    Returns (advisories upserted, notification emails sent).
    """
    notable = upsert_advisories(db, advisories)
    sent = notify_subscribers(db, notable, sender=sender)
    return len(advisories), sent
