"""FDA CORE investigations scraper, against a trimmed snapshot of the live page."""

import pytest

from app.ingest import fda_outbreaks
from app.ingest.base import SourceStructureError
from app.models import AGENCY_FDA, STATUS_ACTIVE, TYPE_OUTBREAK
from tests.conftest import load_fixture


@pytest.fixture
def advisories():
    return fda_outbreaks.parse(load_fixture("fda_outbreaks.html"))


def test_reads_only_the_active_table(advisories):
    # The fixture also contains a closed-investigations table. Anchoring on the
    # "Active Investigations" heading must keep those out of the live feed.
    assert len(advisories) == 16
    assert all(a.status == STATUS_ACTIVE for a in advisories)


def test_normalizes_core_fields(advisories):
    advisory = next(a for a in advisories if a.source_uid == "FDA-CORE:1392")

    assert advisory.type == TYPE_OUTBREAK
    assert advisory.source_agency == AGENCY_FDA
    assert advisory.reason == "Cyclospora"
    assert advisory.started_at == "2026-07-22"
    assert "Total case count: 72" in advisory.description


def test_line_broken_pathogen_names_keep_their_spaces(advisories):
    # The page splits "Salmonella<br>Javiana" across lines; joining without a
    # separator would produce "SalmonellaJaviana".
    advisory = next(a for a in advisories if a.source_uid == "FDA-CORE:1395")
    assert advisory.reason == "Salmonella Javiana"


def test_row_links_to_its_own_investigation_page(advisories):
    advisory = next(a for a in advisories if a.source_uid == "FDA-CORE:1390")
    assert advisory.source_url.startswith("https://www.fda.gov/food/outbreaks-foodborne-illness/")
    assert "investigation" in advisory.source_url


def test_rows_without_a_dedicated_page_fall_back_to_the_index(advisories):
    # Some active investigations have no standalone page yet; the table row on
    # the index page is the record, and that URL still resolves.
    advisory = next(a for a in advisories if a.source_uid == "FDA-CORE:1392")
    assert advisory.source_url == fda_outbreaks.PAGE_URL


def test_every_advisory_has_a_source_url(advisories):
    assert all(a.source_url.startswith("https://www.fda.gov/") for a in advisories)


def test_renamed_column_raises_before_emitting_rows():
    with pytest.raises(SourceStructureError) as excinfo:
        fda_outbreaks.parse(load_fixture("fda_outbreaks_malformed.html"))

    message = str(excinfo.value)
    assert "totalcasecount" in message


def test_missing_active_heading_raises():
    with pytest.raises(SourceStructureError) as excinfo:
        fda_outbreaks.parse("<html><body><h2>Closed Investigations</h2><table></table></body></html>")
    assert "Active Investigations" in str(excinfo.value)


def test_empty_page_raises():
    with pytest.raises(SourceStructureError):
        fda_outbreaks.parse("<html><body><p>Service unavailable</p></body></html>")
