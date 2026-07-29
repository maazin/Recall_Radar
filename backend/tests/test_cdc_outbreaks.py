"""CDC weekly investigations scraper, against a saved snapshot.

As with FSIS, www.cdc.gov was unreachable from the build environment, so this
fixture reflects the documented table shape rather than a captured live page.
The parser locates its columns by header wording, so the malformed case below
exercises the same failure path a real column rename would take.
"""

import pytest

from app.ingest import cdc_outbreaks
from app.ingest.base import SourceStructureError
from app.models import AGENCY_CDC, STATUS_ACTIVE, TYPE_OUTBREAK
from tests.conftest import load_fixture


@pytest.fixture
def advisories():
    return cdc_outbreaks.parse(load_fixture("cdc_outbreaks.html"))


def test_skips_pathogens_with_no_active_investigation(advisories):
    # The fixture lists Cyclospora with a count of "None".
    assert len(advisories) == 3
    assert "cyclospora" not in {a.source_uid.split(":")[1] for a in advisories}


def test_normalizes_core_fields(advisories):
    advisory = next(a for a in advisories if a.source_uid == "CDC:salmonella")

    assert advisory.type == TYPE_OUTBREAK
    assert advisory.source_agency == AGENCY_CDC
    assert advisory.status == STATUS_ACTIVE
    assert advisory.reason == "Salmonella"
    assert "3 active investigations" in advisory.description


def test_singular_wording_for_a_single_investigation(advisories):
    advisory = next(a for a in advisories if a.source_uid == "CDC:listeria-monocytogenes")
    assert "1 active investigation for" in advisory.description


def test_notice_title_becomes_the_brand(advisories):
    advisory = next(a for a in advisories if a.source_uid == "CDC:salmonella")
    assert advisory.brand_or_chain == "Salmonella Outbreak Linked to Alfalfa Sprouts"


def test_relative_links_become_absolute(advisories):
    advisory = next(a for a in advisories if a.source_uid == "CDC:e-coli-o157-h7")
    assert advisory.source_url == (
        "https://www.cdc.gov/ecoli/outbreaks/romaine-july-2026.html"
    )


def test_every_advisory_links_to_cdc(advisories):
    assert all(a.source_url.startswith("https://www.cdc.gov/") for a in advisories)


def test_renamed_columns_raise_before_emitting_rows():
    with pytest.raises(SourceStructureError) as excinfo:
        cdc_outbreaks.parse(load_fixture("cdc_outbreaks_malformed.html"))

    message = str(excinfo.value)
    assert "pathogen" in message.lower()
    # The failure names the headers actually seen, so the fix is obvious.
    assert "organismgroup" in message


def test_page_without_a_table_raises():
    with pytest.raises(SourceStructureError) as excinfo:
        cdc_outbreaks.parse("<html><body><h1>Foodborne Outbreaks</h1></body></html>")
    assert "no table" in str(excinfo.value).lower()


def test_header_only_table_raises():
    html = "<html><body><table><tr><th>Pathogen</th><th>Investigations</th></tr></table></body></html>"
    with pytest.raises(SourceStructureError):
        cdc_outbreaks.parse(html)
