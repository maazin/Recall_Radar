#!/usr/bin/env python3
"""Check each live source against the parser written for it, and refresh fixtures.

Why this exists: the PRD asks that field names be confirmed against a live
response rather than taken from documentation, and this is what does that
confirmation. All four mappers have since been verified this way — three of
the four sources still block requests from cloud/CI IP ranges, though, so a
"could not fetch" result here usually means you're running this from a
datacenter rather than that the mapper has drifted. See the README's
"blocked-IP problem" section.

Run this whenever you want to re-confirm a source, or after an ingest run logs
a `SourceStructureError`, from a network that can reach all four sources:

    python scripts/verify_sources.py              # report only
    python scripts/verify_sources.py --write      # also refresh the fixtures

For each source it fetches, parses, and reports either the normalized output or
the exact structure mismatch. A mismatch names the fields that *were* present,
so correcting the mapper is a single edit.

Exit codes: 0 if every source verified, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.ingest import cdc_outbreaks, fda_outbreaks, fda_recalls, fsis_recalls  # noqa: E402
from app.ingest.base import SourceStructureError  # noqa: E402

FIXTURES = BACKEND / "tests" / "fixtures"

SOURCES = {
    "fda-recalls": (fda_recalls, "fda_enforcement.json"),
    "fsis-recalls": (fsis_recalls, "fsis_recalls.json"),
    "cdc-outbreaks": (cdc_outbreaks, "cdc_outbreaks.html"),
    "fda-outbreaks": (fda_outbreaks, "fda_outbreaks.html"),
}


def describe_payload(raw: str) -> str:
    """Summarize what the endpoint actually returned, for diagnosis."""
    stripped = raw.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return "malformed JSON"
        records = data if isinstance(data, list) else data.get("results", [])
        if isinstance(records, list) and records and isinstance(records[0], dict):
            return (
                f"{len(records)} record(s); first record fields:\n      "
                + "\n      ".join(sorted(records[0].keys()))
            )
        return f"JSON {type(data).__name__}"
    return f"{len(raw)} bytes of HTML"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Overwrite the saved fixture with the live payload on success.",
    )
    parser.add_argument("--source", choices=[*SOURCES, "all"], default="all")
    args = parser.parse_args()

    names = list(SOURCES) if args.source == "all" else [args.source]
    failed: list[str] = []

    for name in names:
        module, fixture_name = SOURCES[name]
        print(f"\n=== {name} ===")

        try:
            raw = module.fetch()
        except Exception as exc:  # noqa: BLE001 - report and continue to the next source
            print(f"  FETCH FAILED: {type(exc).__name__}: {exc}")
            failed.append(name)
            continue

        print(f"  fetched: {describe_payload(raw)}")

        try:
            advisories = module.parse(raw)
        except SourceStructureError as exc:
            print(f"  STRUCTURE MISMATCH — the mapper needs updating:\n    {exc}")
            failed.append(name)
            continue

        print(f"  parsed OK: {len(advisories)} advisories")
        for advisory in advisories[:3]:
            print(
                f"    - {advisory.source_uid} | {advisory.brand_or_chain[:40]} | "
                f"{advisory.status} | {advisory.started_at} | {advisory.category}"
            )
            print(f"      {advisory.source_url[:100]}")

        if args.write:
            (FIXTURES / fixture_name).write_text(raw, encoding="utf-8")
            print(f"  fixture refreshed: tests/fixtures/{fixture_name}")

    print()
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print(f"All {len(names)} source(s) verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
