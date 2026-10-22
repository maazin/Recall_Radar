"""Coverage reflects actual fetches; search/detail preserve source information."""
from datetime import UTC, datetime, timedelta

import pytest

from app.ingest import fda_recalls, fsis_recalls
from app.ingest import run as runner
from app.ingest.base import SourceStructureError, SourceUnavailableError
from app.ingest.pipeline import upsert_advisories
from app.models import SourceHealth
from app.sources import coverage_status
from tests.conftest import load_fixture
from tests.test_pipeline import make_advisory


def test_coverage_has_all_four_feeds_without_inventing_history(client):
    body = client.get('/api/sources').json()
    assert body['stale_after_hours'] == 36
    assert len(body['sources']) == 4
    for source in body['sources']:
        assert source['status'] == 'unknown'
        assert source['last_success_at'] is None
        assert source['record_count'] == 0


@pytest.mark.parametrize('outcome,age,expected', [
    ('success', 1, 'current'), ('success', 37, 'delayed'),
    ('unavailable', 1, 'unavailable'), ('invalid', 1, 'error'),
    ('failed', 1, 'error'), ('running', 1, 'updating'), ('running', 40, 'delayed'),
])
def test_freshness_depends_on_fetch_time(outcome, age, expected):
    now = datetime.now(UTC)
    assert coverage_status(now - timedelta(hours=age), outcome, now) == expected


def test_success_records_zero_results_as_a_success(db, monkeypatch):
    monkeypatch.setitem(runner.SOURCES, 'fda-recalls', (lambda: 'raw', lambda raw: []))
    assert runner.run_source('fda-recalls') == (0, 0)
    row = db.get(SourceHealth, 'fda-recalls')
    assert row.outcome == 'success'
    assert row.last_success_at is not None
    assert row.last_attempt_at is not None
    assert row.last_record_count == 0


@pytest.mark.parametrize('failure,outcome', [
    (SourceUnavailableError('403'), 'unavailable'),
    (SourceStructureError('changed'), 'invalid'),
    (ValueError('unexpected'), 'failed'),
])
def test_failed_refresh_preserves_previous_success(db, monkeypatch, failure, outcome):
    success = datetime.now(UTC) - timedelta(days=2)
    db.add(SourceHealth(source_key='fda-recalls', outcome='success',
                        last_success_at=success, last_record_count=4))
    db.commit()

    def fail():
        raise failure

    monkeypatch.setitem(runner.SOURCES, 'fda-recalls', (fail, lambda raw: []))
    with pytest.raises(type(failure)):
        runner.run_source('fda-recalls')
    db.expire_all()
    row = db.get(SourceHealth, 'fda-recalls')
    assert row.outcome == outcome
    assert row.last_success_at == success
    assert row.last_record_count == 4
    assert row.last_attempt_at > success


def test_notification_failure_does_not_hide_successful_ingestion(db, monkeypatch):
    monkeypatch.setitem(runner.SOURCES, 'fda-recalls',
                        (lambda: 'raw', lambda raw: [make_advisory()]))

    def fail(db, rows):
        raise RuntimeError('mail down')

    monkeypatch.setattr(runner, 'notify_subscribers', fail)
    assert runner.run_source('fda-recalls') == (1, 0)
    assert db.get(SourceHealth, 'fda-recalls').outcome == 'success'


def test_product_and_hazard_search_and_detail_round_trip(client, db):
    upsert_advisories(db, [make_advisory(
        product_description='Frozen spinach, 10 oz', lot_codes='LOT ABC-123',
        distribution_pattern='Distributed in CA and NY', recall_number='R-10',
        description='Frozen spinach, 10 oz', reason='Possible Listeria contamination',
    )])
    for query in ['frozen spinach', 'LISTERIA', 'Acme']:
        body = client.get('/api/advisories', params={'q': query, 'status': 'active'}).json()
        assert body['total'] == 1
        assert client.get('/api/advisories/search', params={'q': query}).json()['total'] == 1
    assert client.get('/api/advisories', params={'q': '%'}).json()['total'] == 0
    assert client.get('/api/advisories', params={'q': 'spinach', 'status': 'resolved'}).json()['total'] == 0
    row = client.get('/api/advisories').json()['items'][0]
    detail = client.get(f"/api/advisories/{row['id']}").json()
    assert detail['lot_codes'] == 'LOT ABC-123'
    assert detail['distribution_pattern'] == 'Distributed in CA and NY'
    assert detail['recall_number'] == 'R-10'
    assert client.get('/api/advisories/9999999').status_code == 404
    assert client.get('/api/advisories/search', params={'q': '  '}).status_code == 422
    coverage = client.get('/api/sources').json()['sources']
    assert next(x for x in coverage if x['key'] == 'fda-recalls')['record_count'] == 1


def test_fda_preserves_structured_product_fields():
    import json
    payload = json.loads(load_fixture('fda_enforcement.json'))
    payload['results'][0]['code_info'] = 'LOT: TEST-42'
    row = fda_recalls.parse(payload)[0]
    assert row.lot_codes == 'LOT: TEST-42'
    assert row.product_description == payload['results'][0]['product_description']
    assert row.distribution_pattern == payload['results'][0]['distribution_pattern']
    assert row.recall_number == payload['results'][0]['recall_number']


def test_fsis_preserves_product_information_when_available():
    import json
    payload = json.loads(load_fixture('fsis_recalls.json'))
    rows = fsis_recalls.parse(payload)
    assert all(row.recall_number for row in rows)
    assert any(row.product_description for row in rows)


def test_interrupted_first_ingestion_does_not_show_updating_forever():
    now = datetime.now(UTC)
    assert coverage_status(None, 'running', now, now - timedelta(hours=37)) == 'delayed'


def test_structured_product_field_is_searchable(client, db):
    upsert_advisories(db, [make_advisory(product_description='Special spinach product')])
    assert client.get('/api/advisories', params={'q': 'Special spinach'}).json()['total'] == 1
