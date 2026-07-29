# RecallRadar

A public feed that unifies FDA/USDA food recalls and CDC/FDA outbreak investigations into one
searchable, plain-language page: what to avoid, why, and where — grocery brands and restaurants
both. Search a brand or chain, and subscribe by email for new matches.

**Stack:** React (Vite) · FastAPI · PostgreSQL

---

## What RecallRadar is, and is not

RecallRadar is an **aggregator**. It indexes records published by the FDA, USDA/FSIS and CDC and
links back to the original agency record for every entry. It does not issue health alerts and is
not an authoritative source.

This is a design constraint, not just copy. openFDA's terms state its data should not be used to
issue public alerts, so:

- `advisories.source_url` is `NOT NULL` and every response carries it.
- Every card in the UI shows its source agency and links to that agency's record.
- The masthead, the API root, and every notification email state the aggregator disclaimer.
- No user-facing string phrases RecallRadar as declaring a health alert.

---

## Quick start

```bash
docker compose up --build
```

- Feed — http://localhost:5173
- API docs — http://localhost:8000/docs

Compose starts Postgres, applies migrations, serves the API and the frontend, and runs an
`ingest` service that ingests on boot and then once a day.

To populate the feed immediately in a shell:

```bash
docker compose run --rm backend python -m app.ingest.run --source all
```

### Running the backend without Docker

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
```

---

## Data sources

| Source | Type | Ingester | Live-verified |
|---|---|---|---|
| [openFDA Food Enforcement](https://api.fda.gov/food/enforcement.json) | JSON API | `app/ingest/fda_recalls.py` | ✅ yes |
| [FDA outbreak investigations](https://www.fda.gov/food/outbreaks-foodborne-illness/investigations-foodborne-illness-outbreaks) | HTML scrape | `app/ingest/fda_outbreaks.py` | ✅ yes |
| [USDA/FSIS Recall API](https://www.fsis.usda.gov/fsis/api/recall/v/1) | JSON API | `app/ingest/fsis_recalls.py` | ⚠️ **no — see below** |
| [CDC weekly investigations](https://www.cdc.gov/foodborne-outbreaks/outbreaks/index.html) | HTML scrape | `app/ingest/cdc_outbreaks.py` | ⚠️ **no — see below** |

CDC NORS is intentionally not integrated; it is reference-only and out of scope for the MVP.

### ⚠️ FSIS and CDC mappers are not yet confirmed against a live response

The build environment could not reach either host — `www.fsis.usda.gov` and `www.cdc.gov` both
return **HTTP 403** from their CDN edge for every request, including the API endpoint, the FSIS
API documentation PDF, and the site roots. That block was consistent across direct requests, a
headless browser, and a third-party cloud fetcher, so it is a network-level restriction rather
than anything about the client.

So those two mappers are written from the field names and table shape the agencies publish, and
**have not been validated against real payloads**. They are built to fail safely rather than
guess:

- FSIS asserts its required fields and, on a mismatch, raises an error naming **the fields that
  were actually present**.
- CDC locates its columns by header *wording* ("pathogen", "investigation") rather than by fixed
  position, and on a mismatch reports **the headers it actually saw**.

Either way a drifted or mis-assumed structure produces zero rows and a loud failure, never
silent bad data.

**To confirm them, run this once from an unblocked network:**

```bash
python scripts/verify_sources.py --write
```

It fetches each source, prints the live field names, runs the real parser against them, and with
`--write` refreshes the test fixtures from the live payloads. If FSIS or CDC differ from what the
mappers assume, the output names the exact discrepancy — the fix is a single edit in the
corresponding `app/ingest/` module, and `pytest` then re-validates against the refreshed fixtures.

---

## Ingestion

```bash
python -m app.ingest.run --source all
python -m app.ingest.run --source fda-recalls
```

Exit code `0` means every requested source ingested cleanly; `1` means at least one failed a
structure check or could not be fetched. One failing source does not stop the others.

**Scheduling** is set up two ways — use whichever fits the deployment:

- `.github/workflows/ingest.yml` — daily cron, plus manual dispatch. Needs `DATABASE_URL` (and
  optionally the SMTP secrets) in the repository's Actions secrets.
- the `ingest` service in `docker-compose.yml` — for self-hosted or local running.

### How notifications avoid re-sending

Notification sends are driven by the ingestion diff, not by the feed. `upsert_advisories`
returns only advisories that are **newly inserted** or that **transitioned from resolved back to
active**; routine re-ingests of unchanged records return nothing and send nothing. Without this,
every scheduled run would re-notify the entire feed.

With `SMTP_HOST` unset — the default in local dev and CI — the sender logs each message instead
of delivering it, so the whole path is exercised without anything leaving the machine.

---

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/advisories` | Unified feed, newest first. Filters: `category`, `type`, `status`, `q`, `limit`, `offset`. |
| `GET /api/advisories/search?q=` | Brand/chain lookup against `advisories.brand_or_chain`. Composes with the same filters. |
| `GET /api/stats` | Counts used by the feed header. |
| `POST /api/subscriptions` | Subscribe an email with optional `category_filter` and `keyword_filter`. |
| `GET /api/health` | Liveness. |

---

## Data model

**advisories** — `id`, `source_uid`, `type` (`recall`|`outbreak`), `source_agency`
(`FDA`|`USDA-FSIS`|`CDC`), `category` (`grocery`|`restaurant`), `brand_or_chain`, `description`,
`reason`, `severity`, `states_affected` (`text[]`), `status` (`active`|`resolved`), `started_at`,
`updated_at`, `source_url`.

**subscriptions** — `id`, `email`, `category_filter`, `keyword_filter`, `created_at`.

Two notes on the implementation:

- **`source_uid`** is not in the published data model but is required by it: step 3 asks for an
  upsert and step 10 asks for a diff against the previous state, and both need stable per-record
  identity. It is `"<AGENCY>:<agency's own record id>"`, e.g. `FDA:F-0276-2017`, with a unique
  constraint.
- **Dates are `text`**, per the spec. Everything is normalized to ISO-8601 (`YYYY-MM-DD`), which
  sorts correctly lexicographically, so ordering the feed on `started_at` is valid.

`states_affected` is stored but deliberately not exposed as a filter — state-level filtering is
an explicit non-goal for this build.

### About FDA recall `source_url`

openFDA publishes no per-record HTML permalink. Each FDA recall therefore links to a query
against the agency's own API that resolves to exactly that enforcement report:

```
https://api.fda.gov/food/enforcement.json?search=recall_number:"F-0276-2017"
```

That is the original agency record and it is guaranteed to resolve. FSIS, CDC and FDA outbreak
entries link to their agency's own page.

---

## Category tagging

`app/ingest/categorize.py` tags each advisory `grocery` or `restaurant` from the entity name
using a chain list plus generic foodservice terms — no model. Two deliberate choices:

- **`grocery` is the default.** Most FDA and FSIS recalls are packaged retail products, so an
  unmatched entity is far more likely to be a grocery brand.
- **The term list favours precision.** "kitchen", "cafe" and a bare "grill" are excluded, because
  "Kitchen Basics" broth and "Cafe Bustelo" coffee are grocery brands. A restaurant named only
  "Joe's Grill" falls through to `grocery` — an acceptable trade for not mistagging the much
  larger grocery set.

---

## Tests

```bash
cd backend && pytest -q          # 121 tests
```

Every ingestion source is tested against **saved fixture files, never a live endpoint**, and each
source has a deliberately malformed fixture proving the failure path fires:

| Source | Good fixture | Malformed fixture | What breaks it |
|---|---|---|---|
| FDA recalls | `fda_enforcement.json` (real) | `fda_enforcement_malformed.json` | required field removed |
| FDA outbreaks | `fda_outbreaks.html` (real) | `fda_outbreaks_malformed.html` | column renamed |
| FSIS recalls | `fsis_recalls.json` (documented shape) | `fsis_recalls_malformed.json` | required field removed |
| CDC outbreaks | `cdc_outbreaks.html` (documented shape) | `cdc_outbreaks_malformed.html` | columns renamed |

The FDA fixtures are trimmed captures of real live responses. The FDA outbreak fixture keeps both
the active table and a historical-year table, so the parser's heading-anchored table selection is
genuinely exercised rather than relying on table position.

CI (`.github/workflows/ci.yml`) runs ruff, applies migrations, and runs the suite against a
Postgres service on every push, plus a frontend production build.

---

## Deploying

1. Provision Postgres and set `DATABASE_URL`.
2. Backend: `alembic upgrade head`, then serve `app.main:app` (the included `backend/Dockerfile`
   does both under Compose). Set `CORS_ORIGINS` to the frontend's origin.
3. Frontend: `npm run build` and serve `frontend/dist` statically, with `VITE_API_BASE_URL`
   pointed at the API.
4. Add the Actions secrets listed in `.github/workflows/ingest.yml` so scheduled ingestion runs
   against the deployed database, or run the Compose `ingest` service alongside the app.
5. Run `python scripts/verify_sources.py --write` from the deploy environment to confirm all four
   sources — in particular FSIS and CDC — before relying on the feed.

---

## Status against the acceptance criteria

| Criterion | Status |
|---|---|
| FDA and USDA recalls ingest and normalize correctly | FDA ✅ verified on live data (564 records). USDA ⚠️ mapper written and tested against fixtures, unverified against a live response — see above. |
| CDC and FDA outbreak investigations ingest, tagged `outbreak` | FDA ✅ verified on live data (16 active). CDC ⚠️ same caveat as USDA. |
| A malformed source fails loudly, not silently | ✅ one malformed fixture per source, all four proven to raise |
| Feed shows both types together, distinguishable, each linking to source | ✅ |
| Category filter works | ✅ |
| Brand/chain search returns correct advisories | ✅ |
| A seeded advisory matching a subscription triggers an email in tests | ✅ |
| Deployed live, ingestion scheduled | ⚠️ not deployed — scheduling is configured for both GitHub Actions and Compose, but no hosting target was provisioned |
