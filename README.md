# SEO Auditor - Monorepo Architecture

A modern, high-performance Technical SEO Auditor built with Next.js, Express, WebSocket, and Python BFS Crawling Engine organized as a clean monorepo.

---

## Workspace Layout

- `apps/frontend`: Next.js 14 Dashboard UI application.
- `apps/backend`: Express REST API + WebSocket Server wrapping the `seo_auditor` Python engine.
- `packages/shared`: Shared TypeScript types, schemas, DTO validations, and constants.
- `docs/`: Comprehensive architecture, API, WebSocket, and Environment variable documentation.
- `scripts/`: Monorepo development and build scripts.

---

## Available Scripts

In the root directory, you can run:

### `npm run dev`
Concurrently starts both frontend and backend development servers.

### `npm run dev:frontend`
Starts only the Next.js frontend application.

### `npm run dev:backend`
Starts only the Express + WebSocket backend server.

### `npm run build`
Builds all packages and applications in proper dependency order (`packages/shared` -> `apps/backend` -> `apps/frontend`).

### `npm run lint`
Runs linter checks across all packages.

### `npm run test`
Runs automated unit and integration tests.

---

## Documentation

- [Folder Structure](docs/folder-structure.md)
- [Architecture Overview](docs/architecture.md)
- [REST API Specification](docs/api.md)
- [WebSocket Events Specification](docs/websocket.md)
- [Environment Variables Guide](docs/env.md)

---

## Projects & history (Phase 1)

Every finished audit is stored in a central database (SQLite by default,
Postgres via `DATABASE_URL`) under a project per domain, so runs can be listed
and compared. See [REST API](docs/api.md#projects--audit-history-central-database)
and [Environment](docs/env.md).

- **Import existing audits once:** `cd apps/backend && python -m app.db.import_sessions`
  (safe to re-run).
- **Scheduled audits:** set a project's `audit_schedule` to `daily`/`weekly`,
  then either set `SCHEDULER_ENABLED=true` or have a cron service call
  `curl -X POST -H "Authorization: Bearer $CRON_SECRET" https://<backend>/api/cron/run`.
- **Where crawls run:** on the always-on backend (the Oracle VM in
  `deploy/oracle`). Vercel serverless functions time out long before a crawl
  finishes, so they must never run audits.
- **Postgres in production:** `docker compose --profile postgres up -d` and set
  `DATABASE_URL=postgresql+psycopg://seo:<POSTGRES_PASSWORD>@postgres/seo`.

### How to verify (about 5 minutes)

```bash
cd apps/backend
python -m pytest -q                                   # all tests pass
# two audits of one site
python -m app.cli https://books.toscrape.com/ --max-pages 20 --max-depth 2 --skip-external-links --json | grep -o '"persisted": [a-z]*'
python -m app.cli https://books.toscrape.com/ --max-pages 20 --max-depth 2 --skip-external-links --json | grep -o '"audit_id": [0-9]*'
uvicorn app.main:app --port 5055 &
curl -s localhost:5055/api/projects                   # books.toscrape.com, audit_count 2
curl -s localhost:5055/api/projects/1/audits          # two audits, newest first
curl -s localhost:5055/api/audits/2/diff              # diff against audit 1
```

---

## Rank tracking (Phase 2)

Track keywords per project, daily, with competitor positions and alerts. See
[REST API](docs/api.md#rank-tracking) and [Environment](docs/env.md).

1. **Add keywords and competitors:** `POST /api/projects/{id}/keywords`,
   `POST /api/projects/{id}/competitors`.
2. **Preview for free:** `POST /api/projects/{id}/rank-checks/run` returns a
   dry-run preview. It's made-up data, never stored.
3. **Go live** when you choose to spend:
   - DataForSEO: `SERP_PROVIDER=dataforseo`, `DATAFORSEO_LOGIN`,
     `DATAFORSEO_PASSWORD`, then `SERP_DRY_RUN=false`. `SERP_DAILY_CAP` (default 50)
     is a hard daily limit.
   - Google CSE: `GOOGLE_CSE_API_KEY` + `GOOGLE_CSE_CX`, capped by
     `GOOGLE_CSE_DAILY_QUOTA`. Top 10 only; no device targeting.
4. **Alerts:** set `SLACK_WEBHOOK_URL` and/or the `SMTP_*` + `ALERT_EMAIL_*` settings.
5. **Schedule:** `SCHEDULER_ENABLED=true`, or a cron calling `/api/cron/run`.
   Scheduled checks run only with a live provider: dry-run data never becomes history.

### How to verify (no money spent)

```bash
cd apps/backend
python -m pytest tests/test_rank_schedule.py -v   # daily checks write history; a drop alerts once
uvicorn app.main:app --port 5055 &
curl -s -X POST -H 'Content-Type: application/json' -d '{"domain":"example.com"}' localhost:5055/api/projects
curl -s -X POST -H 'Content-Type: application/json' -d '{"keywords":[{"phrase":"espresso"}]}' localhost:5055/api/projects/1/keywords
curl -s -X POST localhost:5055/api/projects/1/rank-checks/run                 # dry-run preview
curl -s -o /dev/null -w '%{http_code}\n' -X POST "localhost:5055/api/projects/1/rank-checks/run?dry_run=false"   # 409 until a live provider is set
```

---

## Keywords Explorer & Content Gap (Phase 3)

- **Explore a keyword:** `POST /api/keywords/explore {"seed": "..."}`. You get
  ideas (Autocomplete + People Also Ask), volume, difficulty, a traffic
  estimate, and optional clusters. CSV via `GET /api/keywords/explore.csv?seed=...`.
- **Content gap:** `POST /api/projects/{id}/content-gap` returns keywords your
  competitors rank for (top 20) that you don't (top 100), ranked by
  opportunity. CSV via `GET /api/projects/{id}/content-gap.csv`.
- **Cost control:** dry run until DataForSEO is live
  (`SERP_PROVIDER=dataforseo`, credentials, `SERP_DRY_RUN=false`).
  `DATAFORSEO_LABS_DAILY_CAP` (default 20) is a hard daily limit, and cached
  answers are free.

### How to verify (no money spent)

```bash
cd apps/backend
python -m pytest tests/test_explorer.py tests/test_content_gap.py tests/test_keywords_api.py -v
uvicorn app.main:app --port 5057 &
curl -s -X POST -H 'Content-Type: application/json' -d '{"seed":"espresso machine"}' localhost:5057/api/keywords/explore
curl -s "localhost:5057/api/keywords/explore.csv?seed=espresso%20machine" | head -3   # starts with '# DRY RUN'
curl -s -X POST -H 'Content-Type: application/json' -d '{"domain":"example.com"}' localhost:5057/api/projects
curl -s -X POST -H 'Content-Type: application/json' -d '{"domain":"rival.org"}' localhost:5057/api/projects/1/competitors
curl -s -X POST -H 'Content-Type: application/json' -d '{}' localhost:5057/api/projects/1/content-gap
```

---

## Platform dashboard (Phase 4)

The frontend now has pages for everything Phases 1–3 added. The global nav
links **Projects**, **Keywords Explorer** and **+ New audit**.

| Page | What it shows |
| --- | --- |
| `/projects` | One card per site: latest health, audit count, last audit date |
| `/projects/[id]` | Overview: KPI tiles, health over time, latest audit diff, biggest rank moves |
| `/projects/[id]/audits` | Audit history, a diff of any two audits (new/fixed issues by severity, pages added/removed, status changes), "Open report" |
| `/projects/[id]/ranks` | Tracked keywords, add/remove keywords and competitors, position history chart (#1 at the top, gaps for skipped checks, table view), alert settings, dry-run preview |
| `/projects/[id]/gap` | Content gap against chosen competitors. Runs only when you click **Run**. CSV download |
| `/keywords` | Keywords Explorer: ideas, volume, difficulty, CPC, traffic estimate, optional clusters, CSV |
| `/dashboard?session=<id>` | Opens any earlier audit's full report |

Every data view has loading, empty and error states. Dry-run (made-up) data
always shows a "Preview data" banner, and CSV links say "(preview)".

Design rules are in `apps/frontend/DESIGN.md` (generated by
`npx getdesign@latest add apple`). It is followed selectively. The section
**"SEO dashboard adaptations"** at its end lists what's adopted and what's
overridden for a data dashboard (severity colours, chart palette, density,
states, dark mode).

### How to verify (no money spent, ~5 minutes)

```bash
# 1. Tests
cd apps/frontend && npx vitest run && npx tsc --noEmit

# 2. Backend in dry run, on a throwaway data folder
cd ../backend
export SESSION_DIR=/tmp/seo-p4 SERP_PROVIDER=dry_run DATAFORSEO_LOGIN= DATAFORSEO_PASSWORD=
python -m uvicorn app.main:app --port 5000 &

# 3. Seed: two audits of a small site (creates project 1), keywords, competitors.
#    Same shell, so the CLI writes to the same SESSION_DIR.
python -m app.cli https://books.toscrape.com/ --max-pages 20 --skip-external-links   # run twice
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"keywords":[{"phrase":"buy books online"},{"phrase":"poetry books"}]}' \
  localhost:5000/api/projects/1/keywords
curl -s -X POST -H 'Content-Type: application/json' -d '{"domain":"amazon.com"}' \
  localhost:5000/api/projects/1/competitors

# 4. Frontend pointed at the local backend
cd ../frontend && npm run dev        # http://localhost:3000/projects
```

Then open `/projects` → the project → each tab. Check that Content Gap makes
no request until you click **Run**, and that the dry-run banners show. The
rank history chart stays empty until real rank checks have run. **Preview
check** shows dry-run positions but doesn't save them.

> **Production builds:** `apps/frontend/.env.production` points
> `NEXT_PUBLIC_API_URL` at the live server, and `NEXT_PUBLIC_*` values are
> baked in at build time. For a local `next build`/`next start`, override it:
> `NEXT_PUBLIC_API_URL=http://127.0.0.1:5000 NEXT_PUBLIC_WS_URL=ws://127.0.0.1:5000/ws npx next build`.

---

## Core Web Vitals (Phase 5.1)

Every audit measures Core Web Vitals (LCP, INP, CLS, plus lab TBT and a
performance score). It measures the start URL plus the most important pages
by internal PageRank, up to `PSI_MAX_PAGES` (default 5), mobile.

- **Sources:** PageSpeed Insights when `PSI_API_KEY` is set (hard daily cap
  `PSI_DAILY_CAP`, default 50), then local Lighthouse when
  `LIGHTHOUSE_ENABLED=true`. With neither, audits run as before and the UI says
  "not measured".
- **Rating:** Google's thresholds. Real-user (field) data when Google has it
  for the page, otherwise lab data, labelled. Poor values add warnings that
  count in the health score.
- **Where it shows:**
  - the Core Web Vitals card on the project Overview (homepage trend)
  - the per-page table on the Site Audit tab
  - the report's Performance tab
- **CLI:** `--psi-key KEY` (overrides `PSI_API_KEY`) and `--psi-max-pages N`.
  The CLI used to call PSI for every page; it now measures the top N.
- **Lighthouse setup (once):** `npm i -g lighthouse@12`. Chrome is
  auto-detected, or set `CHROME_PATH`. Not available on the Oracle VM yet
  (no Chrome in the image); that comes with Playwright in Phase 5.2.

### How to verify (no money spent)

```bash
cd apps/backend
python -m pytest tests/test_vitals_rating.py tests/test_vitals_psi.py tests/test_vitals_lighthouse.py \
  tests/test_vitals_runner.py tests/test_vitals_storage.py tests/test_vitals_pipeline.py tests/test_vitals_api.py -q

# Local Lighthouse (one-time install, uses your installed Chrome)
npm i -g lighthouse@12
export LIGHTHOUSE_ENABLED=true SESSION_DIR=/tmp/seo-cwv
python -m app.cli https://books.toscrape.com/ --max-pages 10 --skip-external-links --psi-max-pages 2 --json \
  | python -c "import sys,json; d=json.load(sys.stdin); print(d['web_vitals_status']); [print(v['url'], v['source'], v['lcp_ms'], v['rating'], v['error']) for v in d['web_vitals']]"
```

Expected: `measured`, then two lines showing `lighthouse`, an LCP in ms and a
rating. Then start the backend (same `SESSION_DIR` and `LIGHTHOUSE_ENABLED`)
and the frontend as in the Phase 4 section. Open the project's Overview to see
the Core Web Vitals card.
