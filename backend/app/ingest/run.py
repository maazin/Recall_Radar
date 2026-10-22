"""Ingestion entrypoint.

    python -m app.ingest.run --source all
    python -m app.ingest.run --source fda-recalls

Exit codes:
    0  at least one source ingested, and none had drifted
    1  a source's structure changed, and a human needs to look at the mapper
    2  nothing could be reached this run

1 and 2 are deliberately different. Drift is deterministic: running again gets
the same answer, so the caller should stop and fail. Being refused by every
source is transient, and because each run re-reads a rolling window rather than
only yesterday's records, a skipped run costs nothing. The next successful run
backfills whatever was missed. So 2 is worth retrying before it becomes a
failure, which is what the scheduled workflow does with it.

A structure failure is loud and fatal by design: a source whose shape has drifted
produces no rows at all rather than partial ones.

A source that simply cannot be reached is treated differently, and deliberately.
fsis.usda.gov and cdc.gov answer 403 to datacenter IP ranges, and fda.gov
redirects them to a bot-detection page; all three serve the same content to a
residential connection. That is an availability fact about where the job runs,
not a defect, and there is nothing in the repo to fix. Failing the run for it
would leave the daily job permanently red — and a job that is always red is one
nobody reads, which is precisely when a genuine structure break slips past.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.ingest import cdc_outbreaks, fda_outbreaks, fda_recalls, fsis_recalls
from app.ingest.base import (
    NormalizedAdvisory,
    SourceStructureError,
    SourceUnavailableError,
)
from app.ingest.pipeline import ingest
from app.models import NotificationDelivery, SourceHealth
from app.notify.outbox import deliver_pending

logger = logging.getLogger("app.ingest.run")

# See the module docstring: drift and unreachability are not the same failure.
EXIT_DRIFT = 1
EXIT_NOTHING_REACHABLE = 2

# name -> (fetch raw payload, parse raw payload)
SOURCES: dict[str, tuple[Callable[[], str], Callable[[str], list[NormalizedAdvisory]]]] = {
    "fda-recalls": (fda_recalls.fetch, fda_recalls.parse),
    "fsis-recalls": (fsis_recalls.fetch, fsis_recalls.parse),
    "cdc-outbreaks": (cdc_outbreaks.fetch, cdc_outbreaks.parse),
    "fda-outbreaks": (fda_outbreaks.fetch, fda_outbreaks.parse),
}


def _record_health(db, name, outcome, count=None):
    health = db.get(SourceHealth, name)
    if health is None:
        health = SourceHealth(source_key=name, outcome=outcome)
        db.add(health)
    health.outcome = outcome
    if outcome == "running":
        health.last_attempt_at = datetime.now(UTC)
    if outcome == "success":
        health.last_success_at = datetime.now(UTC)
        health.last_record_count = count
    db.commit()


def run_source(name: str) -> tuple[int, int]:
    """Record attempts and outcomes, preserving the previous successful fetch."""
    fetch, parse = SOURCES[name]
    with SessionLocal() as db:
        _record_health(db, name, "running")
    try:
        logger.info("[%s] fetching", name)
        raw = fetch()
        advisories = parse(raw)
        with SessionLocal() as db:
            count, sent = ingest(db, advisories, defer_notifications=True)
            _record_health(db, name, "success", count)
        return len(advisories), sent
    except Exception as exc:
        outcome = (
            "unavailable" if isinstance(exc, SourceUnavailableError)
            else "invalid" if isinstance(exc, SourceStructureError) else "failed"
        )
        with SessionLocal() as db:
            _record_health(db, name, outcome)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest advisories from agency sources.")
    parser.add_argument(
        "--source",
        default="all",
        choices=[*SOURCES.keys(), "all"],
        help="Which source to ingest (default: all).",
    )
    parser.add_argument(
        "--defer-notifications", action="store_true",
        help="Save digests for a later run without contacting SMTP (diagnostic runs).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    names = list(SOURCES) if args.source == "all" else [args.source]
    succeeded: list[str] = []
    unreachable: list[str] = []
    broken: list[str] = []

    for name in names:
        try:
            run_source(name)
            succeeded.append(name)
        except SourceStructureError as exc:
            # The source changed shape. Nothing was written for it, and the
            # mapper needs a human.
            logger.error(
                "[%s] SOURCE STRUCTURE CHANGED — no data ingested from this source. %s",
                name,
                exc,
            )
            broken.append(name)
        except SourceUnavailableError as exc:
            # The site refused us. Nothing is wrong with the code, and there is
            # nothing to fix in the repo, so this must not read like a defect.
            logger.warning("[%s] source unavailable, skipped: %s", name, exc)
            unreachable.append(name)
        except Exception as exc:  # noqa: BLE001 - one bad source must not stop the rest
            logger.exception("[%s] ingestion failed: %s", name, exc)
            broken.append(name)

    with SessionLocal() as db:
        sent = 0 if args.defer_notifications else deliver_pending(db)
        pending = db.scalar(select(func.count()).select_from(NotificationDelivery).where(
            NotificationDelivery.sent_at.is_(None)
        )) or 0
        last_error = db.scalar(select(NotificationDelivery.last_error).where(
            NotificationDelivery.sent_at.is_(None), NotificationDelivery.last_error.is_not(None)
        ).order_by(NotificationDelivery.id.desc()).limit(1))
    logger.info("Notification delivery: %s sent; %s pending", sent, pending)
    if pending and not args.defer_notifications:
        message = last_error or "Pending digests will be attempted on the next ingestion run"
        logger.warning("%s (%s pending)", message, pending)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::warning::{message}. {pending} notification(s) retained for retry.")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a") as report:
            report.write(
                "## Ingestion result\n\n"
                f"- Refreshed sources: {len(succeeded)}\n"
                f"- Unavailable sources: {len(unreachable)}\n"
                f"- Failed sources: {len(broken)}\n"
                f"- Notifications sent: {sent}\n"
                f"- Notifications pending: {pending}\n"
                f"- Delivery deferred for this run: {args.defer_notifications}\n"
            )
            if last_error:
                report.write(f"- Mail provider: {last_error}\n")

    if succeeded:
        logger.info("Ingested: %s", ", ".join(succeeded))
    if unreachable:
        logger.warning(
            "Unreachable this run (agency sites block datacenter IP ranges; "
            "expected from CI runners and cloud hosts): %s",
            ", ".join(unreachable),
        )

    # A drifted source is a data integrity problem and always fails the run.
    if broken:
        logger.error("Ingestion failed for: %s", ", ".join(broken))
        return EXIT_DRIFT

    # Blocked sources alone do not fail the run, as long as something got in.
    # Failing on them would mean a permanently red daily job, and a job that is
    # always red is one nobody reads, which is exactly when a real structure
    # break would slip past.
    #
    # Reaching nothing at all gets its own code rather than sharing 1 with
    # drift. From a cloud runner only openFDA is reachable, so any hiccup there
    # means zero sources succeed; that was turning ordinary upstream flakiness
    # into a failed job. Nothing is lost by it, because the next run re-reads
    # the same window, so the caller should retry before treating it as broken.
    if unreachable and not succeeded:
        logger.error(
            "No source could be reached; nothing was ingested. This run is "
            "recoverable: the next one re-reads the same window."
        )
        return EXIT_NOTHING_REACHABLE

    return 0


if __name__ == "__main__":
    sys.exit(main())
