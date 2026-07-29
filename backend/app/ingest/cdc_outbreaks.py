"""CDC current outbreaks -> advisories (type=outbreak, source_agency=CDC).

Source: https://www.cdc.gov/foodborne-outbreaks/outbreaks/index.html

The page carries two different things, and this module ingests both:

1. **Active investigations.** A small static block listing each germ CDC is
   currently running multistate investigations for, and how many. No product is
   named — these are the "we know something is happening, we don't know the food
   yet" cases. Ingested as active advisories with the product unidentified.

2. **Outbreak notices.** A table of notices CDC has issued since 2006, each
   naming the implicated food *or venue* and linking to the notice. This is the
   only source in the project that names restaurant chains ("McDonald's Quarter
   Pounders", "Mexican Style Restaurant Chain"), so it is what makes the
   grocery/restaurant split meaningful.

An earlier version of this module scraped `<table><tr>` out of the page and was
wrong: that table is rendered client-side and ships empty in the HTML, so the
parser could only ever have raised. The notices are actually served as a CSV
whose path sits in the table module's `data-file` attribute, which is what this
version reads.

Dates: the notices CSV carries only a year. Where the notice URL encodes a month
(".../blueberries-07-26/index.html") that month is used, giving "2026-07";
otherwise the value is the bare year. Both are valid truncated ISO-8601, both
sort correctly against full dates, and the UI renders them at the precision
actually known rather than inventing a day.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import date
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.ingest.base import (
    BROWSER_HEADERS,
    NormalizedAdvisory,
    SourceStructureError,
    collapse,
    fetch_url,
    iso_from_loose,
    require,
    today_iso,
)
from app.ingest.categorize import categorize
from app.models import AGENCY_CDC, STATUS_ACTIVE, STATUS_RESOLVED, TYPE_OUTBREAK

logger = logging.getLogger(__name__)

PAGE_URL = "https://www.cdc.gov/foodborne-outbreaks/outbreaks/index.html"
_BASE = "https://www.cdc.gov"

# Columns the notices CSV must have. Anything else means the export changed.
NOTICE_COLUMNS = ("Contaminated Food", "Germ", "Year")

# CDC writes "Unknown" in the food column while an investigation is open.
_UNIDENTIFIED = re.compile(r"^(unknown|not identified|tbd|pending)$", re.I)

_COUNT_ITEM = re.compile(r"^(?P<germ>.+?)\s*:\s*(?P<count>\d+)\s*$")
_LAST_UPDATED = re.compile(r"last updated:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})", re.I)
# Notice slugs encode month and 2-digit year, e.g. "blueberries-07-26".
_SLUG_MONTH = re.compile(r"-(?P<month>0[1-9]|1[0-2])-(?P<year>\d{2})(?:/|$)")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _strip_html(value: str) -> str:
    """The CSV's food column contains an anchor tag; take its text."""
    return collapse(BeautifulSoup(value or "", "lxml").get_text(" "))


def _first_href(value: str) -> str | None:
    anchor = BeautifulSoup(value or "", "lxml").find("a", href=True)
    return anchor["href"] if anchor else None


def find_notices_csv_url(page_html: str) -> str:
    """Read the notices CSV path out of the datatable module's data-file."""
    soup = BeautifulSoup(page_html, "lxml")
    module = soup.select_one("[data-file]")
    require(
        module is not None,
        "CDC outbreaks page: no element carrying a data-file attribute. The "
        "notices table is normally a datatable module whose data-file points at "
        "the CSV export; that module is gone or renamed.",
    )
    data_file = (module.get("data-file") or "").strip()
    require(
        bool(data_file),
        "CDC outbreaks page: the datatable module's data-file attribute is empty.",
    )
    return urljoin(_BASE, data_file)


def parse_active_investigations(page_html: str) -> list[NormalizedAdvisory]:
    """Advisories for germs CDC currently has open multistate investigations for."""
    soup = BeautifulSoup(page_html, "lxml")

    block = None
    for header in soup.find_all(attrs={"role": "rowheader"}):
        if "active investigations" in collapse(header.get_text(" ")).lower():
            block = header.find_parent(attrs={"role": "row"}) or header.parent
            break

    require(
        block is not None,
        "CDC outbreaks page: no 'Active investigations by germ' row found. The "
        "investigations block has moved or been relabelled.",
    )

    items = [collapse(li.get_text(" ")) for li in block.find_all("li")]
    require(
        bool(items),
        "CDC outbreaks page: the active-investigations block contains no list "
        "items. Its markup has changed.",
    )

    parsed: list[tuple[str, int]] = []
    for item in items:
        match = _COUNT_ITEM.match(item)
        require(
            match is not None,
            f"CDC outbreaks page: active-investigation entry {item!r} is not in "
            f"the expected '<germ>: <count>' form.",
        )
        parsed.append((collapse(match.group("germ")), int(match.group("count"))))

    updated = _last_updated(soup) or today_iso()

    advisories: list[NormalizedAdvisory] = []
    for germ, count in parsed:
        # A germ with no open investigation this week is not a live advisory.
        if count == 0:
            continue
        description = (
            f"CDC reports {count} active multistate investigation"
            f"{'s' if count != 1 else ''} for {germ}. "
            f"The implicated food has not been identified."
        )
        advisories.append(
            NormalizedAdvisory(
                source_uid=f"{AGENCY_CDC}:active:{_slug(germ)}",
                type=TYPE_OUTBREAK,
                source_agency=AGENCY_CDC,
                category=categorize("Not identified", description),
                brand_or_chain="Not identified",
                description=description,
                reason=germ,
                severity=None,
                states_affected=[],
                status=STATUS_ACTIVE,
                started_at=updated,
                updated_at=updated,
                source_url=PAGE_URL,
            )
        )
    return advisories


def _last_updated(soup: BeautifulSoup) -> str | None:
    match = _LAST_UPDATED.search(soup.get_text(" "))
    return iso_from_loose(match.group(1)) if match else None


def _notice_date(url: str | None, year: str) -> str:
    """Best available precision: YYYY-MM from the notice slug, else YYYY."""
    if url:
        match = _SLUG_MONTH.search(url)
        if match and match.group("year") == year[-2:]:
            return f"{year}-{match.group('month')}"
    return year


def parse_notices(csv_text: str) -> list[NormalizedAdvisory]:
    """Advisories for the outbreak notices CDC has published."""
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = [collapse(f) for f in (reader.fieldnames or [])]

    missing = [c for c in NOTICE_COLUMNS if c not in fieldnames]
    require(
        not missing,
        f"CDC notices CSV is missing column(s): {', '.join(missing)}. Found "
        f"{fieldnames}. The export format has changed.",
    )

    rows = list(reader)
    require(
        bool(rows),
        "CDC notices CSV has a header but no rows.",
    )

    this_year = str(date.today().year)
    advisories: list[NormalizedAdvisory] = []
    seen: set[str] = set()

    for row in rows:
        raw_food = row.get("Contaminated Food") or ""
        food = _strip_html(raw_food)
        germ = _strip_html(row.get("Germ") or "")
        year = collapse(row.get("Year") or "")

        # A row with no food or no germ carries no advisory.
        if not food or not germ:
            continue
        require(
            bool(re.fullmatch(r"\d{4}", year)),
            f"CDC notices CSV: row for {food!r} has Year={year!r}, expected a "
            f"four-digit year.",
        )

        href = _first_href(raw_food)
        url = urljoin(_BASE, href) if href else PAGE_URL

        identified = not _UNIDENTIFIED.match(food)
        brand = food if identified else "Not identified"

        started = _notice_date(href, year)
        # The CSV has no status column. Notices from the current year are
        # treated as still active; earlier ones as resolved. Anything older is
        # historical context for search rather than a live advisory.
        status = STATUS_ACTIVE if year == this_year else STATUS_RESOLVED

        if identified:
            description = f"CDC outbreak notice: {food} linked to {germ}."
        else:
            description = (
                f"CDC outbreak notice: {germ} investigation with no food "
                f"identified yet."
            )

        uid = f"{AGENCY_CDC}:notice:{_slug(href) if href else _slug(f'{food}-{germ}-{year}')}"
        if uid in seen:
            # CDC occasionally lists the same notice twice; keep the first.
            continue
        seen.add(uid)

        advisories.append(
            NormalizedAdvisory(
                source_uid=uid,
                type=TYPE_OUTBREAK,
                source_agency=AGENCY_CDC,
                category=categorize(brand, description),
                brand_or_chain=brand,
                description=description,
                reason=germ,
                severity=None,
                states_affected=[],
                status=status,
                started_at=started,
                updated_at=started,
                source_url=url,
            )
        )

    return advisories


def parse(payload: str | dict[str, Any]) -> list[NormalizedAdvisory]:
    """Parse the bundle produced by `fetch`.

    Accepts the JSON envelope `fetch` returns (or the equivalent dict), so the
    runner's single-payload contract still holds for a source that needs two
    documents.
    """
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SourceStructureError(
                f"CDC payload is not the expected JSON bundle: {exc}"
            ) from exc
    else:
        data = payload

    require(
        isinstance(data, dict) and "page_html" in data and "notices_csv" in data,
        "CDC payload must carry both 'page_html' and 'notices_csv'.",
    )

    advisories = parse_active_investigations(data["page_html"])
    advisories.extend(parse_notices(data["notices_csv"]))
    return advisories


def fetch() -> str:
    """Download the outbreaks page and the notices CSV it points at."""
    import httpx

    with httpx.Client(
        timeout=45.0, follow_redirects=True, headers=BROWSER_HEADERS
    ) as client:
        page_html = fetch_url(client, PAGE_URL, "CDC outbreaks").text

        csv_url = find_notices_csv_url(page_html)
        logger.info("CDC notices CSV: %s", csv_url)
        notices = fetch_url(client, csv_url, "CDC notices CSV")

    return json.dumps(
        {"page_html": page_html, "notices_csv": notices.text, "notices_csv_url": csv_url}
    )
