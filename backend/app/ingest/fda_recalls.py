"""openFDA Food Enforcement -> advisories (type=recall, source_agency=FDA).

Field names here were confirmed against a live response from
https://api.fda.gov/food/enforcement.json, not from documentation.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote

import httpx

from app.config import settings
from app.ingest.base import (
    NormalizedAdvisory,
    SourceStructureError,
    iso_from_compact,
    parse_states,
    require,
    today_iso,
)
from app.ingest.categorize import categorize
from app.models import AGENCY_FDA, STATUS_ACTIVE, STATUS_RESOLVED, TYPE_RECALL

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.fda.gov/food/enforcement.json"

# Confirmed present on every record in the live response. Absence means the
# payload shape has changed and the mapper can no longer be trusted.
REQUIRED_FIELDS = (
    "recall_number",
    "recalling_firm",
    "product_description",
    "reason_for_recall",
    "status",
    "report_date",
)

# openFDA `status` values -> our two-state model.
_RESOLVED_STATUSES = {"terminated", "completed"}


def _map_status(raw: str) -> str:
    return STATUS_RESOLVED if raw.strip().lower() in _RESOLVED_STATUSES else STATUS_ACTIVE


def _source_url(recall_number: str) -> str:
    """Link to the original FDA record.

    openFDA exposes no per-record HTML permalink, so this is a query against the
    agency's own API that resolves to exactly this enforcement report. It is the
    original agency record, and it is guaranteed to resolve.
    """
    return f'{ENDPOINT}?search=recall_number:"{quote(recall_number)}"'


def parse(payload: str | dict[str, Any]) -> list[NormalizedAdvisory]:
    """Map a raw openFDA enforcement payload to normalized advisories.

    Pure: no network, no database. Raises SourceStructureError before producing
    any rows if the payload does not look like an enforcement response.
    """
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SourceStructureError(f"openFDA payload is not valid JSON: {exc}") from exc
    else:
        data = payload

    require(isinstance(data, dict), "openFDA payload is not a JSON object")
    require("results" in data, "openFDA payload has no 'results' key")

    results = data["results"]
    require(isinstance(results, list), "openFDA 'results' is not a list")

    # Validate every record's shape *before* emitting anything, so a drifted
    # payload cannot produce a partially-good batch.
    for index, record in enumerate(results):
        require(
            isinstance(record, dict),
            f"openFDA result at index {index} is not an object",
        )
        missing = [f for f in REQUIRED_FIELDS if f not in record]
        require(
            not missing,
            f"openFDA result at index {index} is missing required field(s): "
            f"{', '.join(missing)}. The enforcement payload shape has changed.",
        )

    advisories: list[NormalizedAdvisory] = []
    for record in results:
        recall_number = str(record["recall_number"]).strip()
        firm = str(record["recalling_firm"]).strip()
        description = str(record["product_description"]).strip()

        started = (
            iso_from_compact(record.get("recall_initiation_date"))
            or iso_from_compact(record["report_date"])
            or today_iso()
        )
        updated = (
            iso_from_compact(record.get("termination_date"))
            or iso_from_compact(record.get("center_classification_date"))
            or iso_from_compact(record["report_date"])
            or started
        )

        advisories.append(
            NormalizedAdvisory(
                source_uid=f"{AGENCY_FDA}:{recall_number}",
                type=TYPE_RECALL,
                source_agency=AGENCY_FDA,
                category=categorize(firm, description),
                brand_or_chain=firm,
                description=description,
                reason=str(record["reason_for_recall"]).strip(),
                severity=(str(record["classification"]).strip() or None)
                if record.get("classification")
                else None,
                states_affected=parse_states(record.get("distribution_pattern")),
                status=_map_status(str(record["status"])),
                started_at=started,
                updated_at=updated,
                source_url=_source_url(recall_number),
            )
        )

    return advisories


def fetch(lookback_days: int | None = None, page_size: int = 100) -> str:
    """Fetch recent enforcement reports, following limit/skip pagination.

    Returns a single JSON document with the pages concatenated into `results`,
    so the return value can be handed straight to `parse` or saved as a fixture.
    """
    from datetime import date, timedelta

    days = lookback_days if lookback_days is not None else settings.ingest_lookback_days
    end = date.today()
    start = end - timedelta(days=days)
    # openFDA documents this range as `[YYYYMMDD+TO+YYYYMMDD]`, where `+` is the
    # URL encoding of a space. It must be written as a real space here: passing a
    # literal "+" through httpx's encoder yields %2B, which openFDA reads as a
    # plus character rather than a separator and answers with a 500.
    date_filter = (
        f"report_date:[{start.strftime('%Y%m%d')} TO {end.strftime('%Y%m%d')}]"
    )

    collected: list[dict[str, Any]] = []
    skip = 0
    meta: dict[str, Any] = {}

    with httpx.Client(timeout=30.0) as client:
        while True:
            params: dict[str, Any] = {
                "search": date_filter,
                "limit": page_size,
                "skip": skip,
            }
            if settings.openfda_api_key:
                params["api_key"] = settings.openfda_api_key

            response = client.get(ENDPOINT, params=params)

            # openFDA returns 404 with a NOT_FOUND error once skip passes the
            # end of the result set, and for an empty date window.
            if response.status_code == 404:
                logger.info("openFDA returned no further results at skip=%s", skip)
                break
            response.raise_for_status()

            page = response.json()
            meta = page.get("meta", meta)
            batch = page.get("results", [])
            if not batch:
                break

            collected.extend(batch)
            total = page.get("meta", {}).get("results", {}).get("total")
            skip += len(batch)
            logger.info("openFDA: fetched %s/%s records", len(collected), total)

            if total is not None and skip >= total:
                break
            if len(batch) < page_size:
                break

    return json.dumps({"meta": meta, "results": collected})
