# Deploying RecallRadar

The whole stack runs on free tiers. Nothing here requires a card.

| Piece | Where | Why |
|---|---|---|
| Postgres | [Neon](https://neon.tech) free tier | Persistent. Render's free Postgres is **deleted after 30 days**, which would take the feed down monthly. Dataset is ~11 MB against a 0.5 GB allowance. |
| API | Render free web service | Defined in `render.yaml`. |
| Frontend | Render static site | Free, no sleep. Also in `render.yaml`. |
| Daily ingest | GitHub Actions | `.github/workflows/ingest.yml`, already written. Free on public repos. Render cron is a paid feature. |
| Email | [Brevo](https://brevo.com) free tier | 300/day, and it accepts a single verified sender address without owning a domain. |

**The one real cost of free:** the API sleeps after 15 minutes idle, so the first
request after a quiet spell waits ~50 seconds. The static page paints instantly
and the advisories arrive late. Render's Starter plan removes it.

---

## I can't do these parts

Creating accounts and entering credentials is yours. Everything below the line
in each step is already committed.

## 1. Database (Neon)

1. Create a project at neon.tech. Any region; match Render's for lower latency.
   Say **no** to Neon Auth — this app has no user accounts.
2. Copy the connection string. Paste it as-is; the app pins the psycopg 3 driver
   onto `postgresql://` and `postgres://` itself, so you do not need to edit the
   scheme.

## 2. Services (Render)

1. New → Blueprint, point it at this repo. Render reads `render.yaml` and creates
   both services.
2. On **recallradar-api**, set `DATABASE_URL` to the Neon string from step 1.
   It is marked `sync: false`, so Render will prompt for it.
3. Deploy. `alembic upgrade head` runs on boot, so the schema is created on the
   first start.

`CORS_ORIGINS`, `APP_BASE_URL` and `VITE_API_BASE_URL` are wired between the two
services in the blueprint — you don't set them by hand.

> `VITE_API_BASE_URL` is baked into the bundle at build time. If the API URL ever
> changes, redeploy the static site or it will keep calling the old one.

## 3. Scheduled ingestion (GitHub Actions)

Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `DATABASE_URL` | Same Neon string as Render |
| `APP_BASE_URL` | The static site URL |
| `OPENFDA_API_KEY` | Optional — only if you hit rate limits |
| `SMTP_*`, `EMAIL_FROM` | Step 4, if enabling email |

Run it once by hand: Actions → Scheduled ingestion → Run workflow. After that it
runs daily at 09:17 UTC.

### Which sources actually work from CI

Measured, not assumed — this is the result of a real run on a GitHub runner:

| Source | From a CI runner | Why |
|---|---|---|
| FDA recalls (`api.fda.gov`) | ✅ works | A real API, no bot protection |
| FDA outbreaks (`www.fda.gov`) | ❌ blocked | Redirects datacenter IPs to a bot-detection page |
| USDA/FSIS (`www.fsis.usda.gov`) | ❌ 403 | Akamai blocks datacenter ranges |
| CDC (`www.cdc.gov`) | ❌ 403 | Same |

The three HTML sources serve the same content happily to a home connection and
refuse cloud IPs. There is nothing to fix in the repo for this.

So the job **does not fail when a source is merely unreachable**. It fails when a
source's *structure* has drifted, or when nothing could be reached at all. That
distinction is deliberate: blocked sites would otherwise leave the daily run
permanently red, and a job that is always red is one nobody reads — which is
exactly when a genuine structure break slips past.

Expect the run to be green with warnings naming the blocked sources.

**To get all four sources**, run the ingest from a residential connection
instead of CI:

```bash
cd backend
DATABASE_URL='<your neon string>' python -m app.ingest.run --source all
```

That writes to the same Neon database the deployed site reads, so the feed fills
in immediately. A laptop cron entry or a one-off run whenever you want the
outbreak data refreshed is enough.

## 4. Email — optional, and the site is honest without it

Notifications are **off by default and the app says so**. With `SMTP_HOST` unset:

- `GET /api/config` reports `notifications_enabled: false`
- the frontend hides the subscribe form entirely
- `POST /api/subscriptions` returns **503** and stores nothing

So an un-configured deployment is a working read-only feed that never asks for
an address it cannot write to. Setting the SMTP variables below is all it takes
to turn the feature on — no code change, no redeploy of the frontend.

Brevo, free, no domain required:

1. Sign up, then Senders → add a sender and verify it with the 6-digit code sent
   to that address. A personal address works; you do **not** need to own a
   domain. (Domain authentication is the alternative, not a prerequisite.)
2. SMTP & API → generate an SMTP key.
3. Set these in **both** places — Render (so the form appears) and GitHub Actions
   (so the ingest job can actually send):

   ```
   SMTP_HOST=smtp-relay.brevo.com
   SMTP_PORT=587
   SMTP_USER=<your brevo login>
   SMTP_PASSWORD=<the SMTP key, not your account password>
   EMAIL_FROM=RecallRadar <your-verified-sender@example.com>
   ```

   Add `APP_BASE_URL` to GitHub Actions too — it is the "browse the full feed"
   link inside the email, and it is the one variable Render wires up on its own
   but Actions does not:

   ```
   APP_BASE_URL=https://recallradar-web.onrender.com
   ```

   Setting SMTP on Render but not on Actions produces a subscribe form that
   accepts signups while no mail is ever sent — the exact dishonesty the 503
   guard exists to prevent, reintroduced by half-configuring it.

Restart the API afterwards so it picks up the new environment; the form appears
on its own once `/api/config` flips.

Two things to know about the free plan:

- **300 emails a day, and it is a hard daily wall** — not a monthly pool. Fine
  for this: mail only goes out when a genuinely new or newly-active advisory
  matches a subscription.
- **Free-plan messages carry a "Sent with Brevo" footer.** Removing it is a paid
  add-on.

Sending from an address on a domain you don't control also hurts deliverability —
expect spam folders. A ~$10/year domain with SPF and DKIM fixes that properly.

Mail only goes out from the **ingest** job. The web service never sends.

## 5. Check it

This deployment:

- Frontend — https://recallradar-web.onrender.com
- API — https://recallradar-api-amis.onrender.com

```bash
curl https://recallradar-api-amis.onrender.com/api/health   # {"status":"ok"}
curl https://recallradar-api-amis.onrender.com/api/stats    # counts per type
curl https://recallradar-api-amis.onrender.com/api/config   # notifications on/off
```

Then load the frontend and confirm the feed renders and a source link opens the
agency's own record. Allow ~50s on the first call while the service wakes.

Verify CORS is scoped to your site rather than open to everyone:

```bash
curl -sD - -o /dev/null -H "Origin: https://evil.example.com" \
  https://recallradar-api-amis.onrender.com/api/stats | grep -i access-control
```

That should print nothing. The same call with your real origin should echo it
back.

---

## Notes

- **Migrations** run on every API boot. `alembic upgrade head` is idempotent.
- **The ingest job is the only writer.** The web service only reads, apart from
  subscription inserts.
- **Rollback** is Render's "Redeploy" on a previous commit. Nothing in the
  current migrations drops data.
