"""Public source definitions and ingestion freshness (separate from agency dates)."""
from datetime import UTC, datetime, timedelta

# Ingestion runs daily. Allow 12 hours of scheduling/retry headroom.
STALE_AFTER_HOURS = 36
SOURCES = {
    "fda-recalls": {
        "label": "FDA food recalls", "agency": "FDA", "type": "recall",
        "url": "https://open.fda.gov/apis/food/enforcement/",
    },
    "fsis-recalls": {
        "label": "USDA / FSIS recalls", "agency": "USDA-FSIS", "type": "recall",
        "url": "https://www.fsis.usda.gov/recalls",
    },
    "cdc-outbreaks": {
        "label": "CDC outbreaks", "agency": "CDC", "type": "outbreak",
        "url": "https://www.cdc.gov/foodborne-outbreaks/outbreaks/index.html",
    },
    "fda-outbreaks": {
        "label": "FDA outbreak investigations", "agency": "FDA", "type": "outbreak",
        "url": (
            "https://www.fda.gov/food/outbreaks-foodborne-illness/"
            "investigations-foodborne-illness-outbreaks"
        ),
    },
}


def coverage_status(last_success_at, outcome, now=None, last_attempt_at=None):
    """Never infer successful ingestion from an agency publication date."""
    now = now or datetime.now(UTC)
    if last_success_at is not None and last_success_at.tzinfo is None:
        last_success_at = last_success_at.replace(tzinfo=UTC)
    stale = last_success_at is None or now - last_success_at > timedelta(hours=STALE_AFTER_HOURS)
    if outcome == "unavailable":
        return "unavailable"
    if outcome in {"invalid", "failed"}:
        return "error"
    if last_success_at is None:
        if last_attempt_at is not None:
            if last_attempt_at.tzinfo is None:
                last_attempt_at = last_attempt_at.replace(tzinfo=UTC)
            if now - last_attempt_at > timedelta(hours=STALE_AFTER_HOURS):
                return "delayed"
        return "unknown" if outcome != "running" else "updating"
    if stale:
        return "delayed"
    return "updating" if outcome == "running" else "current"
