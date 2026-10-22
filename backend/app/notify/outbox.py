"""Persistent SMTP retries; delivery errors never discard committed digests."""
import logging
import smtplib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import NotificationDelivery
from app.notify.email import default_sender, notifications_enabled

logger = logging.getLogger(__name__)


def enqueue_digest(db, subscription, subject, body):
    db.add(NotificationDelivery(
        subscription_id=subscription.id, recipient=subscription.email,
        subject=subject, body=body,
    ))


def delivery_error(exc):
    # Do not persist/log SMTP response text: it may include private addresses.
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return (f"SMTP authorization rejected ({exc.smtp_code}); "
                "check credentials and allowed sender IPs")
    if isinstance(exc, smtplib.SMTPException):
        return "SMTP delivery rejected; check mail provider configuration"
    return "Mail transport failed; delivery will be retried"


def deliver_pending(db, sender=None, *, now=None, limit=100):
    """Try due digests under row locks; skip delivered rows on subsequent runs.

    Authentication failures back off for six hours and stop this batch. Other
    transport failures back off for 15 minutes. A process dying after SMTP
    acceptance but before commit can cause a duplicate (at-least-once delivery).
    """
    if sender is None and not notifications_enabled():
        return 0
    sender = sender or default_sender
    now = now or datetime.now(UTC)
    sent = 0
    for _ in range(limit):
        delivery = db.scalar(
            select(NotificationDelivery)
            .where(NotificationDelivery.sent_at.is_(None),
                   NotificationDelivery.next_attempt_at <= now)
            .order_by(NotificationDelivery.id)
            .limit(1).with_for_update(skip_locked=True)
        )
        if delivery is None:
            db.rollback()
            break
        delivery.attempts += 1
        try:
            sender.send(delivery.recipient, delivery.subject, delivery.body)
        except Exception as exc:
            delivery.last_error = delivery_error(exc)
            auth_failure = isinstance(exc, smtplib.SMTPAuthenticationError)
            delivery.next_attempt_at = now + (
                timedelta(hours=6) if auth_failure else timedelta(minutes=15)
            )
            logger.warning("Notification retained for retry: %s", delivery.last_error)
            db.commit()
            if auth_failure:
                break
        else:
            delivery.sent_at = now
            delivery.last_error = None
            db.commit()
            sent += 1
    return sent
