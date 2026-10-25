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
