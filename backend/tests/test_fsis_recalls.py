"""USDA/FSIS recall parser, against a saved snapshot.

See the module docstring in app/ingest/fsis_recalls.py: the FSIS endpoint could
not be reached from the build environment, so this fixture reflects the field
names FSIS publishes rather than a captured live response. The malformed case
still proves the failure path fires, which is what the acceptance criteria ask
for.
"""

import pytest

from app.ingest import fsis_recalls
from app.ingest.base import SourceStructureError
from app.models import (
    AGENCY_USDA_FSIS,
    CATEGORY_GROCERY,
    CATEGORY_RESTAURANT,
    STATUS_ACTIVE,
    STATUS_RESOLVED,
    TYPE_RECALL,
)
from tests.conftest import load_fixture


@pytest.fixture
def advisories():
    return fsis_recalls.parse(load_fixture("fsis_recalls.json"))


def test_parses_every_record(advisories):
    assert len(advisories) == 3


def test_normalizes_core_fields(advisories):
    advisory = next(a for a in advisories if a.source_uid == "USDA-FSIS:012-2026")

    assert advisory.type == TYPE_RECALL
    assert advisory.source_agency == AGENCY_USDA_FSIS
    assert advisory.brand_or_chain == "Sunrise Meats"
    assert advisory.severity == "Class I"
    assert advisory.reason == "Product Contamination"
    assert advisory.started_at == "2026-07-18"
    assert advisory.updated_at == "2026-07-20"


def test_summary_html_is_stripped(advisories):
    advisory = next(a for a in advisories if a.source_uid == "USDA-FSIS:012-2026")
    assert "<p>" not in advisory.description
    assert advisory.description.startswith("Sunrise Meats, a Nebraska establishment")


def test_state_names_resolve_to_codes(advisories):
    advisory = next(a for a in advisories if a.source_uid == "USDA-FSIS:012-2026")
    assert advisory.states_affected == ["IA", "KS", "NE"]


def test_nationwide_scope_is_empty(advisories):
    # The data model represents national scope as an empty list, not a 50-item one.
    advisory = next(a for a in advisories if a.source_uid == "USDA-FSIS:015-2026")
    assert advisory.states_affected == []


def test_active_notice_drives_status(advisories):
    by_uid = {a.source_uid: a for a in advisories}
    assert by_uid["USDA-FSIS:012-2026"].status == STATUS_ACTIVE
    assert by_uid["USDA-FSIS:009-2026"].status == STATUS_RESOLVED


def test_category_tagging(advisories):
    by_uid = {a.source_uid: a for a in advisories}
    assert by_uid["USDA-FSIS:012-2026"].category == CATEGORY_GROCERY
    assert by_uid["USDA-FSIS:009-2026"].category == CATEGORY_RESTAURANT


def test_relative_press_release_becomes_absolute(advisories):
    by_uid = {a.source_uid: a for a in advisories}
    assert by_uid["USDA-FSIS:012-2026"].source_url == (
        "https://www.fsis.usda.gov/recalls-alerts/sunrise-meats-recalls-ground-beef-products"
    )
    # Already-absolute URLs are left alone.
    assert by_uid["USDA-FSIS:015-2026"].source_url.startswith("https://www.fsis.usda.gov/")


def test_malformed_payload_raises_before_emitting_rows():
    with pytest.raises(SourceStructureError) as excinfo:
        fsis_recalls.parse(load_fixture("fsis_recalls_malformed.json"))

    message = str(excinfo.value)
    assert "field_recall_number" in message
    # The error names what *was* present, so a drifted payload is self-diagnosing.
    assert "field_title" in message


def test_wrong_top_level_shape_raises():
    with pytest.raises(SourceStructureError):
        fsis_recalls.parse('{"unexpected": "object"}')


def test_non_json_payload_raises():
    with pytest.raises(SourceStructureError):
        fsis_recalls.parse("<html>Access Denied</html>")
