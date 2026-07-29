"""USDA/FSIS Recall API -> advisories (type=recall, source_agency=USDA-FSIS).

!! VERIFICATION STATUS !!
The PRD asks that these field names be confirmed against a live response rather
than taken from documentation. That confirmation could not be completed from the
build environment: www.fsis.usda.gov returns HTTP 403 from its Akamai edge for
every request made here (curl, browser, and cloud fetchers alike), for the API,
the docs PDF, and the site root.

So the mapper is written against the field names published by FSIS, and the
structure check below is deliberately self-diagnosing: if a required field is
absent it raises with the field names that *were* present in the payload, so a
single run from an unblocked network tells you exactly what to correct.

Run `python -m scripts.verify_sources` (repo root) from a network that can reach
FSIS to confirm the mapping and regenerate the fixture from real data.
"""

from __future__ import annotations

import json
import logging
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

# The identity and content fields the mapper cannot work without. All six are
# named in the PRD's source table.
REQUIRED_FIELDS = (
    "field_title",
    "field_recall_number",
    "field_recall_date",
    "field_recall_reason",
)


def _first(record: dict[str, Any], *keys: str) -> str:
    """Return the first key with a non-empty value, as trimmed text."""
    for key in keys:
        value = record.get(key)
        if value is None:
            continue
        text = collapse(str(value))
        if text and text.lower() not in {"none", "null"}:
            return text
    return ""


def _strip_html(value: str) -> str:
    """FSIS summary/product fields carry embedded markup."""
    if not value:
        return ""
    if "<" not in value:
        return collapse(value)
    return collapse(BeautifulSoup(value, "lxml").get_text(" "))


def _map_status(record: dict[str, Any]) -> str:
    """Active unless FSIS marks the notice inactive or gives it a closed date."""
    active_notice = _first(record, "field_active_notice").lower()
    if active_notice in {"true", "1", "yes"}:
        return STATUS_ACTIVE
    if active_notice in {"false", "0", "no"}:
        return STATUS_RESOLVED
    if _first(record, "field_closed_date", "field_closed_year"):
        return STATUS_RESOLVED
    return STATUS_ACTIVE


def _source_url(record: dict[str, Any]) -> str:
    """Link to the FSIS press release for this recall."""
    link = _first(record, "field_press_release", "field_en_press_release", "field_recall_url")
    if link.startswith("http"):
        return link
    if link.startswith("/"):
        return f"{_BASE}{link}"
    number = _first(record, "field_recall_number")
    if number:
        return f"{_RECALLS_PAGE}?field_recall_number={number}"
    return _RECALLS_PAGE


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

    advisories: list[NormalizedAdvisory] = []
    for record in data:
        number = _first(record, "field_recall_number")
        if not number:
            # Identity field present but empty: cannot key an upsert on it.
            raise SourceStructureError(
                f"FSIS record has an empty field_recall_number: "
                f"{_first(record, 'field_title')!r}"
            )

        title = _strip_html(_first(record, "field_title"))
        establishment = _strip_html(_first(record, "field_establishment")) or title
        summary = _strip_html(
            _first(record, "field_summary", "field_product_items")
        ) or title

        started = iso_from_loose(_first(record, "field_recall_date")) or today_iso()
        updated = (
            iso_from_loose(_first(record, "field_last_modified_date"))
            or iso_from_loose(_first(record, "field_closed_date"))
            or started
        )

        advisories.append(
            NormalizedAdvisory(
                source_uid=f"{AGENCY_USDA_FSIS}:{number}",
                type=TYPE_RECALL,
                source_agency=AGENCY_USDA_FSIS,
                category=categorize(establishment, summary),
                brand_or_chain=establishment,
                description=summary,
                reason=_strip_html(_first(record, "field_recall_reason")),
                severity=_first(
                    record, "field_recall_classification", "field_risk_level"
                )
                or None,
                states_affected=parse_states(
                    _first(record, "field_states", "field_distro_list")
                ),
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
    with httpx.Client(timeout=45.0, follow_redirects=True, headers=headers) as client:
        response = client.get(ENDPOINT)
        response.raise_for_status()
        return response.text
