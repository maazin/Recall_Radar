"""openFDA enforcement parser, against a saved snapshot of the live API."""

import pytest

from app.ingest import fda_recalls
from app.ingest.base import SourceStructureError
from app.models import AGENCY_FDA, STATUS_ACTIVE, STATUS_RESOLVED, TYPE_RECALL
from tests.conftest import load_fixture


@pytest.fixture
def advisories():
    return fda_recalls.parse(load_fixture("fda_enforcement.json"))


def test_parses_every_record(advisories):
    assert len(advisories) == 6


def test_normalizes_core_fields(advisories):
    advisory = next(a for a in advisories if a.source_uid == "FDA:F-0276-2017")

    assert advisory.type == TYPE_RECALL
    assert advisory.source_agency == AGENCY_FDA
    assert advisory.brand_or_chain == "Pharmatech LLC"
    assert advisory.severity == "Class II"
    assert "contamination" in advisory.reason.lower()


def test_dates_are_iso_8601(advisories):
    # The API serves YYYYMMDD; the table stores sortable ISO-8601 text.
    advisory = next(a for a in advisories if a.source_uid == "FDA:F-0276-2017")
    assert advisory.started_at == "2016-08-08"
    assert all(len(a.started_at) == 10 and a.started_at[4] == "-" for a in advisories)


def test_status_maps_to_two_states(advisories):
    by_uid = {a.source_uid: a for a in advisories}
    assert by_uid["FDA:F-0276-2017"].status == STATUS_RESOLVED  # "Terminated"
    assert by_uid["FDA:F-1170-2024"].status == STATUS_ACTIVE  # "Ongoing"


def test_states_parsed_from_distribution_pattern(advisories):
    by_uid = {a.source_uid: a for a in advisories}
    assert by_uid["FDA:F-0276-2017"].states_affected == ["FL", "MI", "MS", "OH"]
    # Single-state distribution.
    assert by_uid["FDA:H-0914-2026"].states_affected == ["WI"]


def test_every_advisory_links_to_the_original_record(advisories):
    for advisory in advisories:
        assert advisory.source_url.startswith("https://api.fda.gov/food/enforcement.json")
        assert "recall_number" in advisory.source_url


def test_malformed_payload_raises_before_emitting_rows():
    with pytest.raises(SourceStructureError) as excinfo:
        fda_recalls.parse(load_fixture("fda_enforcement_malformed.json"))

    message = str(excinfo.value)
    assert "reason_for_recall" in message
    assert "index 1" in message


def test_non_json_payload_raises():
    with pytest.raises(SourceStructureError):
        fda_recalls.parse("<html>gateway timeout</html>")


def test_missing_results_key_raises():
    with pytest.raises(SourceStructureError):
        fda_recalls.parse('{"meta": {}}')
