"""SMTP failures must preserve notices without failing successful ingestion."""
import smtplib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.ingest import pipeline, run
from app.models import Advisory, NotificationDelivery
from app.notify.outbox import deliver_pending
from tests.test_pipeline import make_advisory, subscribe


class RejectedSender:
    def send(self, *args):
        raise smtplib.SMTPAuthenticationError(525, b'Unauthorized IP address private@example.test')


def test_smtp_ip_rejection_preserves_committed_digest(db, sender):
    subscribe(db)
    count, sent = pipeline.ingest(db, [make_advisory()], sender=RejectedSender())
    assert (count, sent) == (1, 0)
    assert db.scalar(select(func.count()).select_from(Advisory)) == 1
    row = db.scalar(select(NotificationDelivery))
    assert row.sent_at is None
    assert row.attempts == 1
    assert '525' in row.last_error
    assert 'private@example.test' not in row.last_error
    assert row.next_attempt_at > datetime.now(UTC) + timedelta(hours=5)
    assert deliver_pending(db, sender=sender) == 0  # Respect backoff.
    assert deliver_pending(db, sender=sender, now=datetime.now(UTC) + timedelta(hours=7)) == 1
    assert deliver_pending(db, sender=sender, now=datetime.now(UTC) + timedelta(hours=8)) == 0
    assert len(sender.sent) == 1
    db.refresh(row)
    assert row.sent_at is not None and row.last_error is None


def test_deferred_ingestion_never_sends_and_unchanged_rerun_does_not_duplicate(db, sender):
    subscribe(db)
    assert pipeline.ingest(db, [make_advisory()], sender=sender, defer_notifications=True) == (1, 0)
    assert not sender.sent
    assert pipeline.ingest(db, [make_advisory()], sender=sender) == (1, 1)
    assert db.scalar(select(func.count()).select_from(NotificationDelivery)) == 1
    assert pipeline.ingest(db, [make_advisory()], sender=sender) == (1, 0)
    assert len(sender.sent) == 1


def test_queue_and_advisories_are_atomic(db, monkeypatch):
    subscribe(db)

    def fail(*args):
        raise ValueError('Cannot stage a digest')

    monkeypatch.setattr(pipeline, 'enqueue_digest', fail)
    with pytest.raises(ValueError):
        pipeline.ingest(db, [make_advisory()], defer_notifications=True)
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Advisory)) == 0
    assert db.scalar(select(func.count()).select_from(NotificationDelivery)) == 0


def test_auth_failure_stops_batch_without_dropping_other_recipients(db, sender):
    subscribe(db, email='one@example.com')
    subscribe(db, email='two@example.com')
    pipeline.ingest(db, [make_advisory()], sender=RejectedSender())
    rows = list(db.scalars(select(NotificationDelivery).order_by(NotificationDelivery.id)))
    assert [row.attempts for row in rows] == [1, 0]
    assert all(row.sent_at is None for row in rows)
    assert deliver_pending(db, sender=sender, now=datetime.now(UTC) + timedelta(hours=7)) == 2


def test_no_smtp_does_not_mark_queued_notices_delivered(db, monkeypatch):
    subscribe(db)
    monkeypatch.setattr('app.notify.outbox.notifications_enabled', lambda: False)
    assert pipeline.ingest(db, [make_advisory()]) == (1, 0)
    assert db.scalar(select(NotificationDelivery)).sent_at is None


def test_main_reports_delivery_warning_while_ingestion_succeeds(db, monkeypatch, tmp_path, capsys):
    subscribe(db)
    monkeypatch.setattr(run, 'SOURCES', {
        'fda-recalls': (lambda: 'raw', lambda raw: [make_advisory()]),
    })
    monkeypatch.setattr(run, 'deliver_pending', lambda db: deliver_pending(db, RejectedSender()))
    summary = tmp_path / 'summary.md'
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    assert run.main(['--source', 'all']) == 0
    assert '::warning::SMTP authorization rejected (525)' in capsys.readouterr().out
    assert '- Refreshed sources: 1' in summary.read_text()
    assert '- Notifications pending: 1' in summary.read_text()
    assert 'private@example.test' not in summary.read_text()


def test_main_diagnostic_mode_never_contacts_mail_server(db, monkeypatch):
    subscribe(db)
    monkeypatch.setattr(run, 'SOURCES', {
        'fda-recalls': (lambda: 'raw', lambda raw: [make_advisory()]),
    })

    def forbidden(*args):
        pytest.fail('Diagnostic mode must not contact SMTP')

    monkeypatch.setattr(run, 'deliver_pending', forbidden)
    assert run.main(['--source', 'all', '--defer-notifications']) == 0
    assert db.scalar(select(NotificationDelivery)).sent_at is None
