# RecallRadar

Food recalls and foodborne-illness outbreak investigations from the FDA, USDA/FSIS and CDC, in
one searchable feed. Search a brand or chain, filter by grocery or restaurant, and subscribe by
email for new matches.

**Live:** [recallradar-web.onrender.com](https://recallradar-web.onrender.com)
**API:** [recallradar-api-amis.onrender.com](https://recallradar-api-amis.onrender.com/docs)

**Stack:** React (Vite) · FastAPI · PostgreSQL

---

## What this is, and what it isn't

RecallRadar is an aggregator. It indexes records the agencies have already published and links
back to the original for every entry. It does not issue health alerts and is not an authoritative
source.

That constraint comes from openFDA's terms, which say its data should not be used to issue public
alerts. It shows up in the code, not only in the copy:

- `advisories.source_url` is `NOT NULL`, and every API response carries it.
- Every card shows its source agency and links to that agency's own record.
- The masthead, the API root and every notification email carry the disclaimer.
- No user-facing string phrases RecallRadar as declaring an alert.

---

## Running it locally

```bash
docker compose up --build
```

Feed at http://localhost:5173, API docs at http://localhost:8000/docs. Compose brings up Postgres,
applies migrations, serves both halves, and runs an `ingest` service that fetches on boot and then
once a day.

To fill the database immediately:

```bash
docker compose run --rm backend python -m app.ingest.run --source all
```

Without Docker:

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
```

---

## Where the data comes from

All four ingesters are written against real responses, captured and checked field by field. None
of them were written from documentation alone.

| Source | Type | Module |
|---|---|---|
| [openFDA Food Enforcement](https://api.fda.gov/food/enforcement.json) | JSON API | `app/ingest/fda_recalls.py` |
| [USDA/FSIS Recall API](https://www.fsis.usda.gov/fsis/api/recall/v/1) | JSON API | `app/ingest/fsis_recalls.py` |
| [CDC current outbreaks](https://www.cdc.gov/foodborne-outbreaks/outbreaks/index.html) | HTML + CSV | `app/ingest/cdc_outbreaks.py` |
| [FDA outbreak investigations](https://www.fda.gov/food/outbreaks-foodborne-illness/investigations-foodborne-illness-outbreaks) | HTML scrape | `app/ingest/fda_outbreaks.py` |

CDC NORS is deliberately left out. It is historical reference data, not a live feed.

Roughly 2,000 advisories are indexed at the moment, of which about 380 are active.

### Two things worth knowing about these sources

**The CDC page hides its real data.** The obvious approach, scraping the table of outbreak
notices, does not work: that table is rendered client-side and ships empty in the HTML. The notices
are actually served as a CSV whose path sits in a `data-file` attribute on the table module. The
ingester reads that CSV, and separately parses the small static block listing how many multistate
investigations are open per germ. Those are different kinds of record and both end up in the feed.

**The CDC notices are the only source that names restaurant chains.** FDA and FSIS recalls are
overwhelmingly packaged retail products. Chains like McDonald's, and the "Mexican Style Restaurant
Chain" entries going back to 2006, come from the CDC notices, which is what makes the
grocery/restaurant filter mean anything.

---

## The blocked-IP problem

This is the one operational quirk that will confuse you if nobody mentions it.

Three of the four sources refuse cloud IP addresses:

| Source | From a datacenter | Reason |
|---|---|---|
| `api.fda.gov` | works | A real API, no bot protection |
| `www.fda.gov` | blocked | Redirects datacenter IPs to a bot-detection page |
| `www.fsis.usda.gov` | 403 | Akamai blocks datacenter ranges |
| `www.cdc.gov` | 403 | Same |

All three serve the same content without complaint to a home connection. There is nothing in this
repo to fix.

So the ingester draws a line between two kinds of failure:

- `SourceStructureError` means a source's shape has drifted and the mapper can no longer be
  trusted. The run fails, loudly, and writes nothing for that source.
- `SourceUnavailableError` means the site refused us. It logs a warning and moves on.

That distinction is the whole point. If blocked sites failed the run, the daily job would be
permanently red, and a job that is always red is one nobody reads, which is exactly when a real
structure break slips past.

**Practically:** the scheduled GitHub Actions run keeps FDA recalls fresh on its own. To refresh
the other three, run the ingest from a residential connection:

```bash
cd backend
DATABASE_URL='<your neon string>' python -m app.ingest.run --source all
```

That writes to the same database the live site reads.

---

## Ingestion

```bash
python -m app.ingest.run --source all
python -m app.ingest.run --source fda-recalls
```

Exit `0` means at least one source ingested and none had drifted. Exit `1` means a structure check
failed and a human should look at the mapper. Exit `2` means nothing could be reached this run.
One bad source never stops the others.

`1` and `2` are separate on purpose. Drift is deterministic, so running again gets the same answer
and the caller should stop. Being refused by every source is transient, and costs nothing, because
each run re-reads a rolling window rather than only yesterday's records. The scheduled workflow
retries `2` up to three times before treating it as a failure.

Two ways to schedule it, both already set up:

- `.github/workflows/ingest.yml`, daily at 09:17 UTC plus manual dispatch. Needs `DATABASE_URL` in
  the repository's Actions secrets.
- the `ingest` service in `docker-compose.yml`, for self-hosted or local running.

Worth a calendar note: GitHub disables scheduled workflows after 60 days without repository
activity, and it does so quietly.

### Why re-running doesn't re-notify everyone

Sends are driven by the ingestion diff, not by the feed. `upsert_advisories` returns only records
that were newly inserted or that flipped from resolved back to active. A routine re-ingest of
unchanged records returns nothing and sends nothing. Without that, every scheduled run would email
the entire feed to every subscriber.

---

## Notifications

Email is optional, and the app is honest about it either way. With `SMTP_HOST` unset:

- `GET /api/config` reports `notifications_enabled: false`
- the frontend hides the subscribe form completely
- `POST /api/subscriptions` returns `503` and stores nothing

An unconfigured deployment is a working read-only feed that never asks for an address it has no
way to write to. Setting the SMTP variables turns the feature on with no code change and no
frontend rebuild, because the flag is read at call time rather than at import.

Setup instructions, including a free provider that works without owning a domain, are in
[DEPLOY.md](DEPLOY.md).

---

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/advisories` | The feed, newest first. Filters: `category`, `type`, `status`, `q`, `limit`, `offset`. |
| `GET /api/advisories/search?q=` | Brand or chain lookup. Composes with the same filters. |
| `GET /api/stats` | Counts for the feed header. |
| `GET /api/config` | Whether notifications are enabled on this deployment. |
| `POST /api/subscriptions` | Subscribe an email, with optional `category_filter` and `keyword_filter`. |
| `GET /api/health` | Liveness. |

---

## Data model

**advisories**: `id`, `source_uid`, `type` (`recall`/`outbreak`), `source_agency`
(`FDA`/`USDA-FSIS`/`CDC`), `category` (`grocery`/`restaurant`), `brand_or_chain`, `description`,
`reason`, `severity`, `states_affected` (`text[]`), `status` (`active`/`resolved`), `started_at`,
`updated_at`, `source_url`.

**subscriptions**: `id`, `email`, `category_filter`, `keyword_filter`, `created_at`.

A few implementation notes:

- **`source_uid`** is not in the original spec, but the spec needs it. Upserting and diffing
  against the previous state both require stable per-record identity. It is `"<AGENCY>:<agency's
  record id>"`, for example `FDA:F-0276-2017`, with a unique constraint.
- **Dates are text**, as specified, normalized to ISO-8601. That sorts correctly, so ordering the
  feed on `started_at` works.
- **Some dates are deliberately imprecise.** CDC's notices carry only a year, plus a month when the
  notice URL encodes one. Those are stored as `2024` or `2026-07`, which are valid truncated
  ISO-8601 and still sort correctly. The UI renders each at the precision actually known instead of
  inventing a day.
- **`states_affected`** is stored but not exposed as a filter. State-level filtering was an
  explicit non-goal.

### FDA recall links

openFDA publishes no per-record HTML permalink, so each FDA recall links to a query against the
agency's own API that resolves to exactly that enforcement report:

```
https://api.fda.gov/food/enforcement.json?search=recall_number:"F-0276-2017"
```

It is the original agency record and it always resolves. FSIS, CDC and FDA outbreak entries link to
ordinary agency pages.

---

## Category tagging

`app/ingest/categorize.py` tags each advisory `grocery` or `restaurant` from the entity name, using
a chain list plus a few generic foodservice terms. No model. Two choices drive it:

**Grocery is the default.** Most FDA and FSIS recalls are packaged retail products, so an unmatched
entity is far more likely to be a grocery brand than a restaurant.

**The lists favour precision over recall.** Real examples from live data shaped this:

- "chipotle" is a pepper. It turns up constantly in product names like "Smokey Chipotle Dry Rub",
  so only the full company name "Chipotle Mexican Grill" counts.
- "Deli Meats" and "Frozen Pizza" are supermarket products, not foodservice, and stay grocery.
  A test guards this, because loosening the keywords until they match would mistag a large part of
  the grocery set.
- FSIS press releases routinely name the chains a product was distributed to. Matching those would
  tag the manufacturer as a restaurant, so only the headline feeds the tagger, not the full release
  body.

One known miss: an FSIS recall headlined "Papa John's Salads and Produce" is tagged restaurant,
though the company is a Taylor Farms facility. That is 1 row in 1,223, and the headline genuinely
reads that way.

---

## Tests

```bash
cd backend && pytest -q     # 186 tests, needs Postgres running
```

Every ingester is tested against saved fixtures, never a live endpoint, and every source has a
deliberately malformed fixture proving the failure path fires.

| Source | Fixture | Malformed variant breaks it by |
|---|---|---|
| FDA recalls | `fda_enforcement.json` | removing a required field |
| FDA outbreaks | `fda_outbreaks.html` | renaming a column |
| FSIS recalls | `fsis_recalls.json` | removing a required field |
| CDC investigations | `cdc_outbreaks.html` | relabelling the investigations block |
| CDC notices | `cdc_notices.csv` | renaming the food column |

All fixtures are captures of real agency output. The CDC ones came via the Wayback Machine, since
the origin blocks datacenter IPs, with the archive's URL rewriting undone. The FSIS fixture is a
hand-picked subset chosen to cover the awkward cases: HTML entities in company names, empty
establishment fields, list-valued fields, every recall class, and the Spanish-language duplicates
that share a recall number with their English originals.

CI runs ruff, applies migrations, runs the suite against a Postgres service, and lints and builds
the frontend on every push.

---

## Deploying

Everything runs on free tiers. [DEPLOY.md](DEPLOY.md) has the full walkthrough. The short version:

- **Postgres on Neon**, not Render, because Render deletes free Postgres databases after 30 days.
- **API and frontend on Render**, both defined in `render.yaml`.
- **Daily ingest on GitHub Actions**, because Render's cron is a paid feature.

Two deployment footguns are handled in code rather than left in the docs:

- Managed Postgres providers hand out `postgresql://` URLs that name no driver, and SQLAlchemy then
  reaches for psycopg2, which isn't installed. The config pins psycopg 3 onto whatever you paste.
- GitHub Actions substitutes an unset secret as an empty string rather than omitting it, so
  forwarding an optional secret exports `SMTP_PORT=""` and pydantic dies trying to parse it as an
  int. Blank environment values are treated as absent.

---

## Known limits

- **This is a daily poll, not a live feed.** Nothing pushes; none of these agencies offer webhooks.
  Upstream is slower than the poll anyway, since openFDA refreshes weekly and CDC updates on
  Wednesdays.
- **Three sources need a residential IP**, as described above. The daily cloud job keeps FDA
  recalls current and skips the rest.
- **Case counts are parsed back out of prose.** The outbreak ingesters write "Total case count: 72"
  into the description and the card reads it back with a regex. It should be a real column.
- **`GET /api/advisories?status=` returns 422** on an empty value. The frontend omits empty params
  so it never hits this, but another client would.
- **No frontend tests.** The filter logic has grown enough to deserve some.
