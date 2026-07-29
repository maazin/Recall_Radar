"""Ingestion entrypoint.

    python -m app.ingest.run --source all
    python -m app.ingest.run --source fda-recalls

Exit codes:
    0  every requested source ingested cleanly
    1  at least one source failed a structure check or could not be fetched

A structure failure is loud and fatal by design: a source whose shape has drifted
produces no rows at all rather than partial ones.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable

from app.config import settings
from app.db import SessionLocal
from app.ingest import cdc_outbreaks, fda_outbreaks, fda_recalls, fsis_recalls
from app.ingest.base import NormalizedAdvisory, SourceStructureError
from app.ingest.pipeline import ingest

logger = logging.getLogger("app.ingest.run")

# name -> (fetch raw payload, parse raw payload)
SOURCES: dict[str, tuple[Callable[[], str], Callable[[str], list[NormalizedAdvisory]]]] = {
    "fda-recalls": (fda_recalls.fetch, fda_recalls.parse),
    "fsis-recalls": (fsis_recalls.fetch, fsis_recalls.parse),
    "cdc-outbreaks": (cdc_outbreaks.fetch, cdc_outbreaks.parse),
    "fda-outbreaks": (fda_outbreaks.fetch, fda_outbreaks.parse),
}


def run_source(name: str) -> tuple[int, int]:
    """Fetch, parse, upsert and notify for one source."""
    fetch, parse = SOURCES[name]

    logger.info("[%s] fetching", name)
    raw = fetch()

    logger.info("[%s] parsing %s bytes", name, len(raw))
    advisories = parse(raw)
    logger.info("[%s] parsed %s advisories", name, len(advisories))

    with SessionLocal() as db:
        count, sent = ingest(db, advisories)

    logger.info("[%s] upserted %s advisories, sent %s notification(s)", name, count, sent)
    return count, sent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest advisories from agency sources.")
    parser.add_argument(
        "--source",
        default="all",
        choices=[*SOURCES.keys(), "all"],
        help="Which source to ingest (default: all).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    names = list(SOURCES) if args.source == "all" else [args.source]
    failures: list[str] = []

    for name in names:
        try:
            run_source(name)
        except SourceStructureError as exc:
            # The source changed shape. Nothing was written for it.
            logger.error(
                "[%s] SOURCE STRUCTURE CHANGED — no data ingested from this source. %s",
                name,
                exc,
            )
            failures.append(name)
        except Exception as exc:  # noqa: BLE001 - one bad source must not stop the rest
            logger.exception("[%s] ingestion failed: %s", name, exc)
            failures.append(name)

    if failures:
        logger.error("Ingestion finished with failures: %s", ", ".join(failures))
        return 1

    logger.info("Ingestion finished cleanly for: %s", ", ".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
