"""Email delivery for subscription notifications.

Wording note (compliance): RecallRadar is an aggregator, not an alerting
authority. Every message says the agency published the record and links to the
original; nothing here is phrased as RecallRadar declaring a health alert.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


class EmailSender:
    """Sends mail over SMTP, or logs it when SMTP is not configured.

    Local dev and CI leave `smtp_host` unset, so the send path is exercised end
    to end without anything leaving the machine. `sent` records every message
    for assertions in tests.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))

        if not settings.smtp_host:
            logger.info(
                "SMTP not configured; would have sent to %s with subject %r", to, subject
            )
            return

        message = EmailMessage()
        message["From"] = settings.email_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_user and settings.smtp_password:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)

        logger.info("Sent notification to %s", to)


default_sender = EmailSender()


def render_digest(advisories: list) -> tuple[str, str]:
    """Build the (subject, body) for a batch of matching advisories."""
    count = len(advisories)
    noun = "advisory" if count == 1 else "advisories"
    subject = f"RecallRadar: {count} new {noun} matching your subscription"

    lines = [
        f"RecallRadar indexed {count} new {noun} from official agency sources "
        "that match your subscription.",
        "",
        "RecallRadar aggregates and links to published agency records. It does "
        "not issue health alerts. Always read the original record linked below "
        "for the authoritative details.",
        "",
    ]

    for advisory in advisories:
        lines.append(f"[{advisory.source_agency}] {advisory.brand_or_chain}")
        lines.append(f"  Type:   {advisory.type}")
        lines.append(f"  Reason: {advisory.reason}")
        if advisory.severity:
            lines.append(f"  Agency classification: {advisory.severity}")
        if advisory.states_affected:
            lines.append(f"  States: {', '.join(advisory.states_affected)}")
        lines.append(f"  Published by {advisory.source_agency}: {advisory.source_url}")
        lines.append("")

    lines.append(f"Browse the full feed: {settings.app_base_url}")
    return subject, "\n".join(lines)
