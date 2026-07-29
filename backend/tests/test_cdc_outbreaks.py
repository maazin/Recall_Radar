"""CDC outbreaks ingester, against a real captured snapshot.

www.cdc.gov is unreachable from this build environment (its edge answers 403),
so the fixtures were captured from the Wayback Machine's copy of the live page
of 26 July 2026 and the notices CSV it links to, with the archive's URL
rewriting undone. They are real CDC output, not a hand-written approximation.
"""

import json

import pytest

from app.ingest import cdc_outbreaks
from app.ingest.base import SourceStructureError
from app.models import (
    AGENCY_CDC,
    CATEGORY_GROCERY,
    CATEGORY_RESTAURANT,
    STATUS_ACTIVE,
    STATUS_RESOLVED,
    TYPE_OUTBREAK,
)
from tests.conftest import load_fixture


@pytest.fixture
def page():
    return load_fixture("cdc_outbreaks.html")


@pytest.fixture
def notices_csv():
    return load_fixture("cdc_notices.csv")


@pytest.fixture
def investigations(page):
    return cdc_outbreaks.parse_active_investigations(page)


@pytest.fixture
def notices(notices_csv):
    return cdc_outbreaks.parse_notices(notices_csv)


# --------------------------------------------------------------------------
# Locating the notices CSV
# --------------------------------------------------------------------------


def test_finds_the_notices_csv_url(page):
    assert cdc_outbreaks.find_notices_csv_url(page) == (
        "https://www.cdc.gov/foodborne-outbreaks/media/files/2024/04/full-outbreak-list.csv"
    )


def test_missing_datatable_module_raises():
    with pytest.raises(SourceStructureError) as excinfo:
        cdc_outbreaks.find_notices_csv_url(
            "<html><body><h1>Current Outbreaks</h1></body></html>"
        )
    assert "data-file" in str(excinfo.value)


# --------------------------------------------------------------------------
# Active investigations
# --------------------------------------------------------------------------


def test_parses_the_active_investigation_counts(investigations):
    # The captured page lists Campylobacter 0, E. coli 6, Listeria 6,
    # Salmonella 13. The zero is not a live advisory.
    assert {a.reason for a in investigations} == {"E. coli", "Listeria", "Salmonella"}


def test_zero_count_germ_is_skipped(investigations):
    assert not any("campylobacter" in a.source_uid for a in investigations)


def test_investigation_uses_the_pages_last_updated_date(investigations):
    assert all(a.started_at == "2026-07-22" for a in investigations)


def test_investigations_are_active_with_no_product_identified(investigations):
    for advisory in investigations:
        assert advisory.type == TYPE_OUTBREAK
        assert advisory.source_agency == AGENCY_CDC
        assert advisory.status == STATUS_ACTIVE
        assert advisory.brand_or_chain == "Not identified"
        assert advisory.source_url == cdc_outbreaks.PAGE_URL


def test_investigation_count_wording(investigations):
    salmonella = next(a for a in investigations if a.reason == "Salmonella")
    assert "13 active multistate investigations" in salmonella.description


def test_relabelled_investigations_block_raises():
    with pytest.raises(SourceStructureError) as excinfo:
        cdc_outbreaks.parse_active_investigations(
            load_fixture("cdc_outbreaks_malformed.html")
        )
    assert "active investigations" in str(excinfo.value).lower()


def test_unparseable_count_entry_raises():
    html = """
    <div role="row">
      <div role="rowheader">Active investigations by germ</div>
      <div role="cell"><ul><li>Salmonella &mdash; lots</li></ul></div>
    </div>
    """
    with pytest.raises(SourceStructureError) as excinfo:
        cdc_outbreaks.parse_active_investigations(html)
    assert "expected" in str(excinfo.value).lower()


# --------------------------------------------------------------------------
# Outbreak notices — the only source that names restaurant chains
# --------------------------------------------------------------------------


def test_parses_every_notice(notices):
    assert len(notices) == 230


def test_restaurant_chains_are_tagged_restaurant(notices):
    restaurants = {a.brand_or_chain for a in notices if a.category == CATEGORY_RESTAURANT}
    assert "McDonald's Quarter Pounders" in restaurants
    assert "Mexican Style Restaurant Chain" in restaurants


def test_retail_deli_and_pizza_stay_grocery(notices):
    """Guard the tagger's precision bias.

    "Deli Meats" and "Frozen Pizza" are supermarket products, not foodservice.
    Loosening the keyword list until they match would wrongly reclassify a large
    part of the grocery set.
    """
    by_brand = {a.brand_or_chain: a for a in notices}
    for brand in ("Deli Meats", "Deli Ham", "Frozen Pizza", "Deli Meat and Cheese"):
        assert by_brand[brand].category == CATEGORY_GROCERY


def test_month_precision_taken_from_the_notice_slug(notices):
    blueberries = next(a for a in notices if a.brand_or_chain == "Frozen Blueberries")
    # .../ecoli/outbreaks/blueberries-07-26/index.html
    assert blueberries.started_at == "2026-07"


def test_year_only_when_the_slug_carries_no_month(notices):
    mcdonalds = next(
        a for a in notices if a.brand_or_chain == "McDonald's Quarter Pounders"
    )
    assert mcdonalds.started_at == "2024"


def test_current_year_notices_are_active_and_older_ones_resolved(notices):
    for advisory in notices:
        expected = (
            STATUS_ACTIVE if advisory.started_at.startswith("2026") else STATUS_RESOLVED
        )
        assert advisory.status == expected


def test_unknown_food_is_not_identified(notices):
    # CDC writes "Unknown" while an investigation is still open.
    unknown = [a for a in notices if a.brand_or_chain == "Not identified"]
    assert unknown, "expected at least one notice with no food identified"
    assert all("no food identified" in a.description for a in unknown)


def test_notice_links_are_absolute_cdc_urls(notices):
    assert all(a.source_url.startswith("https://www.cdc.gov/") for a in notices)


def test_source_uids_are_unique(notices):
    uids = [a.source_uid for a in notices]
    assert len(set(uids)) == len(uids)


def test_renamed_csv_column_raises_before_emitting_rows():
    with pytest.raises(SourceStructureError) as excinfo:
        cdc_outbreaks.parse_notices(load_fixture("cdc_notices_malformed.csv"))

    message = str(excinfo.value)
    assert "Contaminated Food" in message
    # The failure names the columns actually seen, so the fix is obvious.
    assert "Implicated Product" in message


def test_non_numeric_year_raises():
    csv_text = 'Contaminated Food,Germ,Year\n"Onions","Salmonella","last year"\n'
    with pytest.raises(SourceStructureError) as excinfo:
        cdc_outbreaks.parse_notices(csv_text)
    assert "four-digit year" in str(excinfo.value)


def test_header_only_csv_raises():
    with pytest.raises(SourceStructureError):
        cdc_outbreaks.parse_notices("Contaminated Food,Germ,Year\n")


# --------------------------------------------------------------------------
# The combined payload the runner sees
# --------------------------------------------------------------------------


def test_parse_bundles_both_sources(page, notices_csv):
    advisories = cdc_outbreaks.parse(
        json.dumps({"page_html": page, "notices_csv": notices_csv})
    )
    assert len(advisories) == 233  # 3 open investigations + 230 notices
    assert any(a.category == CATEGORY_RESTAURANT for a in advisories)


def test_parse_rejects_a_payload_missing_either_document(page):
    with pytest.raises(SourceStructureError) as excinfo:
        cdc_outbreaks.parse(json.dumps({"page_html": page}))
    assert "notices_csv" in str(excinfo.value)


def test_parse_rejects_non_json_payload():
    with pytest.raises(SourceStructureError) as excinfo:
        cdc_outbreaks.parse("<html>not the bundle</html>")
    assert "JSON bundle" in str(excinfo.value)
