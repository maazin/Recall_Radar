from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Column vocabularies, kept here so ingesters and the API agree on them.
TYPE_RECALL = "recall"
TYPE_OUTBREAK = "outbreak"

AGENCY_FDA = "FDA"
AGENCY_USDA_FSIS = "USDA-FSIS"
AGENCY_CDC = "CDC"

CATEGORY_GROCERY = "grocery"
CATEGORY_RESTAURANT = "restaurant"

STATUS_ACTIVE = "active"
STATUS_RESOLVED = "resolved"


class Advisory(Base):
    """A single recall or outbreak investigation, normalized across agencies.

    Dates are stored as ISO-8601 text (YYYY-MM-DD) per the data model spec. ISO-8601
    sorts correctly lexicographically, so ordering the feed on `started_at` is valid.
    """

    __tablename__ = "advisories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Stable per-record identity used to upsert and to diff runs against each other.
    # Format: "<AGENCY>:<agency's own record id>", e.g. "FDA:F-0276-2017".
    # Not in the published data model, but required to make step 3's "upsert" and
    # step 10's "diff against the previous state" possible.
    source_uid: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    type: Mapped[str] = mapped_column(Text, nullable=False)
    source_agency: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    brand_or_chain: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str | None] = mapped_column(Text, nullable=True)
    states_affected: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)

    product_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    lot_codes: Mapped[str | None] = mapped_column(Text, nullable=True)
    distribution_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    recall_number: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_advisories_started_at", "started_at"),
        Index("ix_advisories_category", "category"),
        Index("ix_advisories_type", "type"),
        Index("ix_advisories_status", "status"),
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    category_filter: Mapped[str | None] = mapped_column(Text, nullable=True)
    keyword_filter: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("ix_subscriptions_email", "email"),)


class SourceHealth(Base):
    """One row per feed; timestamps describe our ingestion, not the agency."""

    __tablename__ = "source_health"

    source_key: Mapped[str] = mapped_column(Text, primary_key=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    last_record_count: Mapped[int | None] = mapped_column(Integer)


class NotificationDelivery(Base):
    """A committed digest stays pending until SMTP accepts it."""

    __tablename__ = "notification_deliveries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    recipient: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_notification_deliveries_pending", "sent_at", "next_attempt_at"),)
