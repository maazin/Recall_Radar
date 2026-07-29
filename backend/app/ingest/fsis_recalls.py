"""USDA/FSIS Recall API -> advisories (type=recall, source_agency=USDA-FSIS).

Field names and value shapes here were confirmed against a real response from
https://www.fsis.usda.gov/fsis/api/recall/v/1 (2012 records), retrieved through
the Wayback Machine because the origin answers 403 from this network.

Three things about the payload drive the code below:

* **Several fields are JSON arrays, not strings.** `field_states`,
  `field_recall_reason`, `field_establishment` and `field_product_items` all
  arrive as lists. Passing them through `str()` yields "['Import Violation']",
  brackets and quotes included, which is what a previous version of this mapper
  did.
* **Every recall is published twice, once per language.** 1223 English records
  and 789 Spanish ones share the same `field_recall_number`, so ingesting both
  makes the Spanish copy fight the English one for the same `source_uid`. Only
  `langcode == "English"` is emitted.
* **There is no company field.** The recalling firm lives in
  `field_establishment` where FSIS filled it in (1320 of 2012), and otherwise
  has to come out of the headline, which follows a stable
  "<Company> Recalls <product> Due to <reason>" pattern.
"""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.ingest.base import (
    NormalizedAdvisory,
    SourceStructureError,
    collapse,
    iso_from_loose,
    parse_states,
    require,
    today_iso,
)
from app.ingest.categorize import categorize
from app.models import AGENCY_USDA_FSIS, STATUS_ACTIVE, STATUS_RESOLVED, TYPE_RECALL

logger = logging.getLogger(__name__)

ENDPOINT = "https://www.fsis.usda.gov/fsis/api/recall/v/1"
_BASE = "https://www.fsis.usda.gov"
_RECALLS_PAGE = f"{_BASE}/recalls"

# Confirmed present on all 2012 records in the live response.
REQUIRED_FIELDS = (
    "field_title",
    "field_recall_number",
    "field_recall_date",
    "field_recall_reason",
    "langcode",
)

# FSIS publishes each recall in English and Spanish under one recall number.
LANGUAGE = "English"

# "<Company> Recalls ..." / "FSIS Issues Public Health Alert for ..."
_TITLE_SUBJECT = re.compile(
    r"^\s*(?P<subject>.{2,90}?)\s+"
    r"(?:Recalls|Recall|Recalled|Issues|Expands|Retracts|Announces|Updates)\b"
)
# Agency-issued alerts name no company; the product follows "Alert for".
_ALERT_PRODUCT = re.compile(
    r"(?:Alert|Notice)\s+for\s+(?P<product>.+?)"
    r"(?:\s+Due\s+to\b|\s+That\s+May\b|\s+Because\b|$)",
    re.I,
)
# A handful of alerts name the venue the food was served at.
_SERVED_AT = re.compile(r"Served\s+at\s+(?P<venue>.+?)(?:\s+Due\s+to\b|$)", re.I)

_CLOSED_TYPE = "closed recall"


def _as_text(value: Any) -> str:
    """Flatten an FSIS field to display text.

    Handles the list-valued fields, unescapes HTML entities (FSIS double-encodes
    apostrophes as &#039;) and strips any embedded markup.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, list | tuple):
        parts = [_as_text(item) for item in value]
        return ", ".join(p for p in parts if p)

    text = str(value)
    if not text:
        return ""
    text = html.unescape(html.unescape(text))
    if "<" in text:
        text = BeautifulSoup(text, "lxml").get_text(" ")
    text = collapse(text)
    return "" if text.lower() in {"none", "null"} else text


def _field(record: dict[str, Any], *keys: str) -> str:
    for key in keys:
        text = _as_text(record.get(key))
        if text:
            return text
    return ""


def _brand(record: dict[str, Any], title: str) -> str:
    """Best available name for the entity a reader would recognise.

    Where the headline says the food was "Served at <venue>", the venue wins
    over `field_establishment`. FSIS records the manufacturer there — for the
    Kebab Shop alert that is "Olympia Food Industries, Inc." — but the food
    reached people through the restaurant, so the restaurant is what someone
    searching this feed is looking for. The manufacturer stays in the summary.

    Otherwise: `field_establishment` where FSIS filled it in, then the subject
    of the headline. Agency-issued alerts have no company as their subject, so
    they fall back to the product named in the alert.
    """
    venue = _SERVED_AT.search(title)
    if venue:
        return collapse(venue.group("venue"))

    establishment = _field(record, "field_establishment")
    if establishment:
        return establishment

    match = _TITLE_SUBJECT.match(title)
    subject = match.group("subject").strip(" ,") if match else ""

    if subject and not subject.upper().startswith("FSIS"):
        return subject

    product = _ALERT_PRODUCT.search(title)
    if product:
        return collapse(product.group("product"))

    return subject or title


def _map_status(record: dict[str, Any]) -> str:
    """Closed unless FSIS still lists the notice as live.

    `field_recall_type` is the clearest signal: 1840 of 2012 records are
    "Closed Recall". `field_active_notice` is blank on 189 records, so it is
    only consulted as a secondary check.
    """
    if _field(record, "field_recall_type").lower() == _CLOSED_TYPE:
        return STATUS_RESOLVED
    if _field(record, "field_active_notice").lower() in {"false", "0", "no"}:
        return STATUS_RESOLVED
    return STATUS_ACTIVE


def _source_url(record: dict[str, Any]) -> str:
    """Link to the FSIS notice. Recall URLs are served as http; upgrade them."""
    link = _field(record, "field_recall_url", "field_press_release", "field_en_press_release")
    if link.startswith("http://"):
        link = "https://" + link[len("http://") :]
    if link.startswith("https://"):
        return link
    if link.startswith("/"):
        return f"{_BASE}{link}"
    number = _field(record, "field_recall_number")
    return f"{_RECALLS_PAGE}?field_recall_number={number}" if number else _RECALLS_PAGE


def parse(payload: str | list[Any] | dict[str, Any]) -> list[NormalizedAdvisory]:
    """Map a raw FSIS recall payload to normalized advisories.

    Pure: no network, no database. Raises SourceStructureError before producing
    any rows if the payload does not match the expected shape.
    """
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SourceStructureError(f"FSIS payload is not valid JSON: {exc}") from exc
    else:
        data = payload

    # FSIS serves a bare JSON array; tolerate a {"results": [...]} envelope too.
    if isinstance(data, dict):
        for key in ("results", "data", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break

    require(
        isinstance(data, list),
        f"FSIS payload is {type(data).__name__}, expected a JSON array of recalls.",
    )
    require(bool(data), "FSIS payload is an empty array.")

    # Validate every record before emitting anything.
    for index, record in enumerate(data):
        require(
            isinstance(record, dict),
            f"FSIS record at index {index} is not an object.",
        )
        missing = [f for f in REQUIRED_FIELDS if f not in record]
        require(
            not missing,
            f"FSIS record at index {index} is missing required field(s): "
            f"{', '.join(missing)}. Fields present were: "
            f"{', '.join(sorted(record.keys()))}. "
            f"The FSIS recall payload shape has changed — update the mapper in "
            f"app/ingest/fsis_recalls.py.",
        )

    english = [r for r in data if _as_text(r.get("langcode")) == LANGUAGE]
    require(
        bool(english),
        f"FSIS payload has {len(data)} record(s) but none with "
        f"langcode={LANGUAGE!r}. Language tagging has changed.",
    )

    advisories: list[NormalizedAdvisory] = []
    for record in english:
        number = _field(record, "field_recall_number")
        if not number:
            # Identity field present but empty: cannot key an upsert on it.
            raise SourceStructureError(
                f"FSIS record has an empty field_recall_number: "
                f"{_field(record, 'field_title')!r}"
            )

        title = _field(record, "field_title")
        brand = _brand(record, title)
        summary = _field(record, "field_summary", "field_product_items") or title
        reason = _field(record, "field_recall_reason") or title

        started = iso_from_loose(_field(record, "field_recall_date")) or today_iso()
        updated = iso_from_loose(_field(record, "field_last_modified_date")) or started

        advisories.append(
            NormalizedAdvisory(
                source_uid=f"{AGENCY_USDA_FSIS}:{number}",
                type=TYPE_RECALL,
                source_agency=AGENCY_USDA_FSIS,
                # Only the headline is offered as the secondary signal. The
                # summary is a full press release, and these routinely name the
                # chains a product was distributed to ("shipped to Boston
                # Market"), which says nothing about who was recalled.
                category=categorize(brand, title),
                brand_or_chain=brand,
                description=summary,
                reason=reason,
                severity=_field(record, "field_recall_classification", "field_risk_level")
                or None,
                states_affected=parse_states(_field(record, "field_states")),
                status=_map_status(record),
                started_at=started,
                updated_at=updated,
                source_url=_source_url(record),
            )
        )

    return advisories


def fetch() -> str:
    """Download the FSIS recall feed."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
    }
    with httpx.Client(timeout=90.0, follow_redirects=True, headers=headers) as client:
        response = client.get(ENDPOINT)
        response.raise_for_status()
        return response.text
