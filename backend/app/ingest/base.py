"""Shared plumbing for every ingestion source.

Design rule that follows from the PRD: parsing is a *pure* function from a raw
payload (JSON text or HTML text) to a list of `NormalizedAdvisory`. Nothing in a
parser touches the network or the database. That is what lets every source be
tested against saved fixtures instead of a live endpoint.

The other rule is that a source whose structure has drifted must fail loudly.
Parsers raise `SourceStructureError` *before* emitting any rows, so a changed
upstream page can never turn into partial or malformed data in the table.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime

logger = logging.getLogger(__name__)


class SourceStructureError(Exception):
    """A source no longer matches the structure this parser was written against.

    Raised before any rows are produced. The runner turns this into a loud log
    line and a non-zero exit code.
    """


class SourceUnavailableError(Exception):
    """A source could not be fetched at all.

    Deliberately distinct from `SourceStructureError`. A page that cannot be
    reached is an availability problem; a page whose shape has changed is a data
    integrity problem. Only the second means the mapper can no longer be
    trusted, and only the second should page someone.

    In practice this is mostly IP reputation: fsis.usda.gov and cdc.gov answer
    403 to datacenter ranges, and fda.gov bounces them to a bot-detection page.
    All three serve the same content happily to a residential connection.
    """


# Sent by the HTML scrapers. A bare user-agent is enough to get bounced by the
# bot detection in front of several of these sites; this is the full set a real
# Chrome navigation sends.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# Paths agencies redirect to when they decide the caller is a bot. Following
# one of these produces a 404 on a URL nobody asked for, which buries the real
# cause; recognising them lets the error say what actually happened.
_BOT_WALL_MARKERS = ("abuse-detection", "apology_objects", "access-denied", "distil")


def check_not_bot_walled(response, source: str) -> None:
    """Raise a legible error when a request was diverted to a bot wall."""
    trail = [str(r.url) for r in response.history] + [str(response.url)]
    for url in trail:
        if any(marker in url.lower() for marker in _BOT_WALL_MARKERS):
            raise SourceUnavailableError(
                f"{source}: request was redirected to a bot-detection page "
                f"({url}). The site is up but is refusing this network. Agency "
                f"sites commonly block datacenter IP ranges, so this is expected "
                f"from CI runners and cloud hosts, and does not indicate a "
                f"problem with the mapper."
            )


@dataclass
class NormalizedAdvisory:
    """One advisory in the shape the `advisories` table expects."""

    source_uid: str
    type: str
    source_agency: str
    brand_or_chain: str
    description: str
    reason: str
    status: str
    started_at: str
    updated_at: str
    source_url: str
    severity: str | None = None
    states_affected: list[str] = field(default_factory=list)
    # Filled in by the category tagger after parsing.
    category: str = ""


US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "VI", "GU", "AS", "MP",
}

_STATE_NAME_TO_CODE = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "puerto rico": "PR",
}

# Phrases that mean "everywhere", which the data model represents as an empty list.
_NATIONWIDE = re.compile(r"nationwide|national distribution|all 50 states|nationally", re.I)


def parse_states(text: str | None) -> list[str]:
    """Pull US state codes out of a free-text distribution description.

    Returns an empty list for nationwide scope, matching the data model's
    "nullable/empty for national scope" rule.

    Only uppercase two-letter tokens are considered, so ordinary words like
    "in", "or" and "me" cannot be mistaken for Indiana, Oregon or Maine.
    """
    if not text:
        return []
    if _NATIONWIDE.search(text):
        return []

    found: set[str] = set()
    for token in re.findall(r"\b[A-Z]{2}\b", text):
        if token in US_STATES:
            found.add(token)

    lowered = text.lower()
    for name, code in _STATE_NAME_TO_CODE.items():
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            found.add(code)

    return sorted(found)


def iso_from_compact(value: str | int | None) -> str | None:
    """Convert openFDA's YYYYMMDD dates to ISO-8601. Returns None if unparseable."""
    if value is None:
        return None
    raw = str(value).strip()
    if not re.fullmatch(r"\d{8}", raw):
        return None
    try:
        return datetime.strptime(raw, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def iso_from_loose(value: str | None) -> str | None:
    """Parse the several date shapes the HTML sources and FSIS use.

    Handles ISO-8601 (with or without a time part), Unix timestamps, and the
    M/D/YYYY format the FDA investigations table renders.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    # FSIS returns some dates as Unix epoch seconds.
    if re.fullmatch(r"\d{9,10}", raw):
        try:
            return datetime.utcfromtimestamp(int(raw)).date().isoformat()
        except (ValueError, OSError):
            return None

    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue

    # ISO-8601 with a time component, e.g. "2026-07-22T00:00:00".
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def today_iso() -> str:
    return date.today().isoformat()


def collapse(text: str | None) -> str:
    """Normalize whitespace in text pulled out of HTML."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def require(condition: bool, message: str) -> None:
    """Assert a structural expectation about a source, loudly."""
    if not condition:
        raise SourceStructureError(message)


def fetch_url(client, url: str, source: str):
    """GET a URL, turning any refusal into a SourceUnavailableError.

    Keeps availability failures from masquerading as bugs: an httpx status error
    surfacing raw from a fetch reads like something broke, when the ordinary
    cause is an agency declining to serve this IP.
    """
    import httpx

    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        raise SourceUnavailableError(f"{source}: could not reach {url} — {exc}") from exc

    check_not_bot_walled(response, source)

    if response.status_code in (401, 403, 406, 429) or response.status_code >= 500:
        raise SourceUnavailableError(
            f"{source}: {url} returned HTTP {response.status_code}. The mapper is "
            f"untouched; the site is refusing this request. 403 from an agency "
            f"site is normally IP-based blocking of datacenter ranges."
        )

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise SourceUnavailableError(f"{source}: {url} — {exc}") from exc

    return response
