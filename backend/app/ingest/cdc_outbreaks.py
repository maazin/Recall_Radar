"""CDC weekly active investigations -> advisories (type=outbreak, source_agency=CDC).

Scrapes https://www.cdc.gov/foodborne-outbreaks/outbreaks/index.html, which CDC
refreshes every Wednesday with a table of pathogens and their active
investigation counts, each linking to the current notice.

!! VERIFICATION STATUS !!
As with FSIS, the live page could not be reached from the build environment:
www.cdc.gov returns HTTP 403 from its edge for every request made here. The
parser is therefore written to locate its columns *by header semantics* rather
than by fixed position — it looks for a column mentioning "pathogen" and one
mentioning "investigation" — and asserts loudly, listing the headers it actually
found, when it cannot. One run from an unblocked network via
`python -m scripts.verify_sources` will confirm the shape and write a real
fixture.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from app.ingest.base import (
    NormalizedAdvisory,
    collapse,
    iso_from_loose,
    require,
    today_iso,
)
from app.ingest.categorize import categorize
from app.models import AGENCY_CDC, STATUS_ACTIVE, TYPE_OUTBREAK

logger = logging.getLogger(__name__)

PAGE_URL = "https://www.cdc.gov/foodborne-outbreaks/outbreaks/index.html"
_BASE = "https://www.cdc.gov"


def _canon(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _cell_text(cell) -> str:
    return collapse(cell.get_text(" "))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _find_columns(headers: list[str]) -> tuple[int, int]:
    """Locate the pathogen and investigation-count columns by header wording.

    Returns (pathogen_index, count_index). Raises if either is absent.
    """
    pathogen_index = next(
        (i for i, h in enumerate(headers) if "pathogen" in h or "germ" in h), -1
    )
    count_index = next(
        (i for i, h in enumerate(headers) if "investigation" in h or "outbreak" in h),
        -1,
    )

    require(
        pathogen_index >= 0,
        f"CDC outbreaks page: no column mentioning 'pathogen' found. "
        f"Headers were: {headers}. The table structure has changed.",
    )
    require(
        count_index >= 0,
        f"CDC outbreaks page: no column mentioning 'investigation' found. "
        f"Headers were: {headers}. The table structure has changed.",
    )
    require(
        pathogen_index != count_index,
        f"CDC outbreaks page: pathogen and investigation columns resolved to the "
        f"same index ({pathogen_index}). Headers were: {headers}.",
    )
    return pathogen_index, count_index


def parse(html: str) -> list[NormalizedAdvisory]:
    """Map the CDC weekly investigations page to normalized outbreak advisories.

    Pure: no network, no database. Raises SourceStructureError before producing
    any rows if the table is missing or its columns have changed.
    """
    soup = BeautifulSoup(html, "lxml")

    table = soup.find("table")
    require(
        table is not None,
        "CDC outbreaks page: no table found on the page. The layout has changed.",
    )

    rows = table.find_all("tr")
    require(
        len(rows) >= 2,
        f"CDC outbreaks page: table has {len(rows)} row(s); expected a header row "
        f"plus at least one data row.",
    )

    header_cells = rows[0].find_all(["th", "td"])
    require(
        len(header_cells) >= 2,
        f"CDC outbreaks page: header row has {len(header_cells)} cell(s), "
        f"expected at least 2.",
    )
    headers = [_canon(_cell_text(c)) for c in header_cells]
    pathogen_index, count_index = _find_columns(headers)
    width = len(header_cells)

    advisories: list[NormalizedAdvisory] = []
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        require(
            len(cells) >= width,
            f"CDC outbreaks page: data row has {len(cells)} cells but the header "
            f"declares {width}. Refusing to parse a malformed row.",
        )

        pathogen = _cell_text(cells[pathogen_index])
        if not pathogen:
            continue

        count_text = _cell_text(cells[count_index])
        count = _extract_count(count_text)
        # A pathogen with no active investigation this week is not a live advisory.
        if count == 0:
            continue

        link_text, link_url = _row_link(row)
        names_a_food = link_text and _canon(link_text) != _canon(pathogen)
        brand = link_text if names_a_food else "Not identified"

        description = (
            f"CDC lists {count} active investigation"
            f"{'s' if count != 1 else ''} for {pathogen}."
        )
        if link_text and link_text != brand:
            description += f" Current notice: {link_text}."

        posted = _row_date(row) or today_iso()

        advisories.append(
            NormalizedAdvisory(
                source_uid=f"{AGENCY_CDC}:{_slug(pathogen)}",
                type=TYPE_OUTBREAK,
                source_agency=AGENCY_CDC,
                category=categorize(brand, description),
                brand_or_chain=brand,
                description=description,
                reason=pathogen,
                severity=None,
                states_affected=[],
                status=STATUS_ACTIVE,
                started_at=posted,
                updated_at=posted,
                source_url=link_url,
            )
        )

    return advisories


def _extract_count(text: str) -> int:
    """Read the active-investigation count out of a cell.

    Cells may read "3", "3 investigations", or "None". Anything without a digit
    and without an explicit zero-word is treated as one investigation, since the
    pathogen is listed on a page of active investigations.
    """
    match = re.search(r"\d+", text)
    if match:
        return int(match.group())
    if _canon(text) in {"none", "no", "zero", ""}:
        return 0
    return 1


def _row_link(row) -> tuple[str, str]:
    """Return (link text, absolute URL) for the row's notice link."""
    for anchor in row.find_all("a", href=True):
        href = anchor["href"]
        if href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        text = collapse(anchor.get_text(" "))
        if href.startswith("http"):
            url = href
        else:
            url = f"{_BASE}{href if href.startswith('/') else '/' + href}"
        return text, url
    return "", PAGE_URL


def _row_date(row) -> str | None:
    """Some CDC rows carry a posted/updated date; use it when present."""
    for cell in row.find_all(["td", "th"]):
        parsed = iso_from_loose(_cell_text(cell))
        if parsed:
            return parsed
    return None


def fetch() -> str:
    """Download the CDC weekly investigations page."""
    import httpx

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }
    with httpx.Client(timeout=45.0, follow_redirects=True, headers=headers) as client:
        response = client.get(PAGE_URL)
        response.raise_for_status()
        return response.text
