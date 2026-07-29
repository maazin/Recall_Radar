"""FDA CORE outbreak investigations -> advisories (type=outbreak, source_agency=FDA).

Scrapes https://www.fda.gov/food/outbreaks-foodborne-illness/investigations-foodborne-illness-outbreaks

The page carries one table per year plus an "Active Investigations" table at the
top. Only the active table feeds the live feed, so the parser anchors on that
heading rather than on table position — position would silently start reading a
historical year if FDA reorders the page.

Structure was confirmed against a live copy of the page.
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from app.ingest.base import (
    BROWSER_HEADERS,
    NormalizedAdvisory,
    collapse,
    fetch_url,
    iso_from_loose,
    require,
    today_iso,
)
from app.ingest.categorize import categorize
from app.models import AGENCY_FDA, STATUS_ACTIVE, STATUS_RESOLVED, TYPE_OUTBREAK

logger = logging.getLogger(__name__)

PAGE_URL = (
    "https://www.fda.gov/food/outbreaks-foodborne-illness/"
    "investigations-foodborne-illness-outbreaks"
)
_BASE = "https://www.fda.gov"

_ACTIVE_HEADING = "activeinvestigations"

# Canonical forms of the columns this parser reads, in order. Canonicalizing to
# alphanumerics makes the check immune to the <br> and nbsp noise in the markup
# while still catching a genuine column rename or reorder.
EXPECTED_HEADERS = (
    "dateposted",
    "reference",
    "pathogenorcauseofillness",
    "productslinkedtoillnessesifany",
    "totalcasecount",
    "investigationstatus",
)

_COL_DATE, _COL_REF, _COL_PATHOGEN, _COL_PRODUCT, _COL_CASES, _COL_STATUS = range(6)


def _canon(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _cell_text(cell) -> str:
    # Separator matters: FDA splits "Salmonella<br>Javiana" across lines, and
    # joining without one would yield "SalmonellaJaviana".
    return collapse(cell.get_text(" "))


def parse(html: str) -> list[NormalizedAdvisory]:
    """Map the FDA investigations page to normalized outbreak advisories.

    Pure: no network, no database. Raises SourceStructureError before producing
    any rows if the active table is missing or its columns have changed.
    """
    soup = BeautifulSoup(html, "lxml")

    heading = next(
        (
            h
            for h in soup.find_all(["h2", "h3"])
            if _canon(h.get_text(" ")) == _ACTIVE_HEADING
        ),
        None,
    )
    require(
        heading is not None,
        "FDA outbreaks page: no 'Active Investigations' heading found. "
        "The page layout has changed.",
    )

    table = heading.find_next("table")
    require(
        table is not None,
        "FDA outbreaks page: no table follows the 'Active Investigations' heading.",
    )

    rows = table.find_all("tr")
    require(
        len(rows) >= 1,
        "FDA outbreaks page: active investigations table has no rows at all.",
    )

    header_cells = rows[0].find_all(["th", "td"])
    actual = [_canon(_cell_text(c)) for c in header_cells]
    require(
        len(actual) >= len(EXPECTED_HEADERS),
        f"FDA outbreaks page: expected at least {len(EXPECTED_HEADERS)} columns, "
        f"found {len(actual)}: {actual}",
    )
    for position, expected in enumerate(EXPECTED_HEADERS):
        require(
            actual[position] == expected,
            f"FDA outbreaks page: column {position} is '{actual[position]}', "
            f"expected '{expected}'. The table structure has changed.",
        )

    advisories: list[NormalizedAdvisory] = []
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        require(
            len(cells) >= len(EXPECTED_HEADERS),
            f"FDA outbreaks page: data row has {len(cells)} cells, expected at "
            f"least {len(EXPECTED_HEADERS)}. Refusing to parse a malformed row.",
        )

        reference = _cell_text(cells[_COL_REF])
        if not reference:
            continue

        pathogen = _cell_text(cells[_COL_PATHOGEN]) or "Not identified"
        product = _cell_text(cells[_COL_PRODUCT]) or "Not yet identified"
        cases = _cell_text(cells[_COL_CASES])
        posted = iso_from_loose(_cell_text(cells[_COL_DATE])) or today_iso()
        raw_status = _cell_text(cells[_COL_STATUS])

        description = f"Product linked to illnesses: {product}."
        if cases:
            description += f" Total case count: {cases}."

        advisories.append(
            NormalizedAdvisory(
                source_uid=f"{AGENCY_FDA}-CORE:{reference}",
                type=TYPE_OUTBREAK,
                source_agency=AGENCY_FDA,
                category=categorize(product, description),
                brand_or_chain=product,
                description=description,
                reason=pathogen,
                severity=None,
                states_affected=[],
                status=STATUS_ACTIVE
                if raw_status.strip().lower().startswith("active")
                else STATUS_RESOLVED,
                started_at=posted,
                updated_at=posted,
                source_url=_row_source_url(row),
            )
        )

    return advisories


def _row_source_url(row) -> str:
    """Prefer the row's link to its own investigation page.

    Rows also link to generic pathogen and food-safety pages; those are not the
    record, so they are skipped in favour of an outbreak-investigation URL.
    """
    for anchor in row.find_all("a", href=True):
        href = anchor["href"]
        if "outbreaks-foodborne-illness/" in href and "investigation" in href:
            return href if href.startswith("http") else f"{_BASE}{href}"
    return PAGE_URL


def fetch() -> str:
    """Download the investigations page."""
    import httpx

    with httpx.Client(
        timeout=45.0, follow_redirects=True, headers=BROWSER_HEADERS
    ) as client:
        return fetch_url(client, PAGE_URL, "FDA outbreak investigations").text
