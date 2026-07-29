"""USDA/FSIS recall parser, against real records.

www.fsis.usda.gov answers 403 from this build environment, so the fixture was
cut from a real 2012-record response retrieved through the Wayback Machine.
Records were chosen to cover the cases the mapper actually has to handle:
list-valued fields, HTML-escaped establishment names, agency-issued public
health alerts with no company in the headline, every classification, and
English/Spanish pairs that share one recall number.
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


@pytest.fixture
def by_number(advisories):
    return {a.source_uid.split(":", 1)[1]: a for a in advisories}


# --------------------------------------------------------------------------
# Language handling — the payload carries each recall twice
# --------------------------------------------------------------------------


def test_only_english_records_are_emitted(advisories):
    # The fixture holds 29 records, 26 of them English.
    assert len(advisories) == 26


def test_recall_numbers_are_unique_despite_translated_duplicates(advisories):
    uids = [a.source_uid for a in advisories]
    assert len(set(uids)) == len(uids)


def test_payload_with_no_english_records_raises():
    payload = (
        '[{"field_title": "t", "field_recall_number": "1", '
        '"field_recall_date": "2026-01-01", "field_recall_reason": [], '
        '"langcode": "Spanish"}]'
    )
    with pytest.raises(SourceStructureError) as excinfo:
        fsis_recalls.parse(payload)
    assert "langcode" in str(excinfo.value)


# --------------------------------------------------------------------------
# List-valued fields
# --------------------------------------------------------------------------


def test_reason_list_is_joined_not_stringified(by_number):
    # field_recall_reason arrives as ["Misbranding", "Unreported Allergens"].
    assert by_number["010-2026"].reason == "Import Violation"


def test_no_advisory_carries_a_stringified_list(advisories):
    for advisory in advisories:
        assert not advisory.brand_or_chain.startswith("[")
        assert not advisory.reason.startswith("[")


def test_state_names_become_codes(by_number):
    # field_states is a list of full names: ["Oklahoma"].
    assert by_number["010-2026"].states_affected == ["OK"]


def test_many_states_are_all_captured(by_number):
    states = by_number["PHA-06252026-02"].states_affected
    assert "AK" in states and "WA" in states
    assert len(states) == 9


def test_missing_states_is_an_empty_list(by_number):
    assert by_number["006-2025"].states_affected == []


# --------------------------------------------------------------------------
# Brand extraction — there is no company field
# --------------------------------------------------------------------------


def test_establishment_is_preferred_for_the_brand(by_number):
    assert by_number["PHA-07032026-01"].brand_or_chain == "GoodTimes Beef Jerky"


def test_brand_falls_back_to_the_headline_subject(by_number):
    # 010-2026 has an empty field_establishment; the title reads
    # "BCI Foods, Inc. Recalls Chicken Noodle Soup Product ...".
    assert by_number["010-2026"].brand_or_chain == "BCI Foods, Inc."


def test_html_entities_are_unescaped_in_the_brand(by_number):
    assert by_number["009-2026"].brand_or_chain == "Reser's Fine Foods"


def test_brand_is_never_the_whole_headline_for_a_company_recall(by_number):
    brand = by_number["010-2026"].brand_or_chain
    assert "Recalls" not in brand
    assert len(brand) < 40


# --------------------------------------------------------------------------
# Core normalization
# --------------------------------------------------------------------------


def test_normalizes_core_fields(by_number):
    advisory = by_number["010-2026"]
    assert advisory.type == TYPE_RECALL
    assert advisory.source_agency == AGENCY_USDA_FSIS
    assert advisory.severity == "Class I"
    assert advisory.started_at == "2026-07-23"
    assert advisory.status == STATUS_ACTIVE


def test_closed_recalls_are_resolved(by_number):
    assert by_number["009-2026"].status == STATUS_RESOLVED


def test_classifications_are_carried_through(advisories):
    severities = {a.severity for a in advisories}
    assert {"Class I", "Class II", "Class III"} <= severities


def test_source_urls_are_https_and_point_at_fsis(advisories):
    for advisory in advisories:
        assert advisory.source_url.startswith("https://www.fsis.usda.gov/")


# --------------------------------------------------------------------------
# Category tagging
# --------------------------------------------------------------------------


def test_a_named_restaurant_is_tagged_restaurant(advisories):
    brands = {a.brand_or_chain for a in advisories if a.category == CATEGORY_RESTAURANT}
    assert any("Restaurant" in b for b in brands)


def test_chipotle_the_pepper_does_not_make_a_recall_a_restaurant(by_number):
    """"Smokey Chipotle Dry Rub" is a seasoning, not Chipotle Mexican Grill."""
    assert by_number["028-2014"].category == CATEGORY_GROCERY


def test_chains_named_only_in_the_press_release_do_not_flip_the_category(advisories):
    """FSIS summaries list the chains a product shipped to.

    Those name the customer, not the recalled firm, so they must not drag a
    meat processor into the restaurant bucket.
    """
    processors = {
        "Bellisio Foods, Inc.",
        "West Liberty Foods LLC",
        "Kenosha Beef International, Ltd.",
        "Clemens Food Group, LLC",
    }
    for advisory in advisories:
        if advisory.brand_or_chain in processors:
            assert advisory.category == CATEGORY_GROCERY


# --------------------------------------------------------------------------
# Failure paths
# --------------------------------------------------------------------------


def test_missing_required_field_raises_before_emitting_rows():
    with pytest.raises(SourceStructureError) as excinfo:
        fsis_recalls.parse(load_fixture("fsis_recalls_malformed.json"))

    message = str(excinfo.value)
    assert "field_recall_number" in message
    # The failure lists what was present, so the fix is obvious.
    assert "field_title" in message


def test_non_json_payload_raises():
    with pytest.raises(SourceStructureError) as excinfo:
        fsis_recalls.parse("<html>403 Forbidden</html>")
    assert "not valid JSON" in str(excinfo.value)


def test_non_array_payload_raises():
    with pytest.raises(SourceStructureError) as excinfo:
        fsis_recalls.parse('{"unexpected": "shape"}')
    assert "expected a JSON array" in str(excinfo.value)


def test_empty_array_raises():
    with pytest.raises(SourceStructureError) as excinfo:
        fsis_recalls.parse("[]")
    assert "empty array" in str(excinfo.value)
