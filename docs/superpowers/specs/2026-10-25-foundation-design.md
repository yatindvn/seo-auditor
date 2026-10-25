# Phase 1: Foundation (database + scheduler) — Design

**Date:** 2026-10-25
**Status:** Approved, pending implementation plan
**Branch:** `feat/foundation`
**Brief:** `BUILD_PROMPT.md` Phase 1; context in `docs/GAP_REPORT.md`

## Problem

Audits live only in per-session SQLite files, of which the newest 20 are kept.
There are no projects, so audits of different sites are one undifferentiated
list; history comparison only diffs recommendation codes client-side; nothing
persists rank checks; and nothing can run an audit on a schedule. Every later
phase (rank history, keywords, backlinks, AI visibility) needs a durable,
project-scoped store.

## Decisions taken

- **Projects are automatic per domain.** Auditing `example.com` creates or
  reuses the `example.com` project. Projects can also be created or renamed
  through the API.
- **The central DB is the system of record for finished audits; session files
  remain the crawl's working store** (approach A). The crawl, the live
  dashboard, the paginated endpoints, exports and the Part B page cache keep
  reading session files unchanged. A finished audit is copied into the central
  DB. Readers move over in later phases.

## Design

### 1. Database layer — `app/db/`

- `app/db/engine.py`: one SQLAlchemy 2.x `Engine` and `sessionmaker`, built
  from `DATABASE_URL`. The default is `sqlite:///<SESSION_DIR>/platform.db`, on
  the existing sessions volume. Postgres URLs use the `postgresql+psycopg://`
  driver. SQLite connections get `PRAGMA foreign_keys=ON` and WAL mode.
- `app/db/models.py`: declarative models (below).
- `apps/backend/alembic/` with `env.py` bound to `models.Base.metadata`. A
  single initial migration creates every table. At API startup, and in the CLI
  before persisting, `run_migrations()` runs `alembic upgrade head`
  programmatically. Tests create schemas from the same migration, not from
  `metadata.create_all`, so the migration itself is tested.

Tables (all ids are integer autoincrement; all timestamps timezone-aware UTC):

| Table | Columns |
| --- | --- |
| `projects` | id, name, domain (unique), created_at, audit_schedule (null / `daily` / `weekly`), audit_options_json (max_pages, max_depth, ignore_robots), last_scheduled_at |
| `audits` | id, project_id → projects, session_id (unique), start_url, status (`completed` / `partial` / `failed`), trigger (`manual` / `scheduled` / `import`), started_at, finished_at, page_count, health_score, summary_json |
| `audit_pages` | id, audit_id → audits (cascade), url, final_url, status, depth, title, word_count, issue_count, alias_of, duplicate_of, cache_status. Unique (audit_id, url) |
| `audit_issues` | id, audit_id → audits (cascade), url, code, severity, message. Index (audit_id, code), (audit_id, url) |
| `keywords` | id, project_id, phrase, country (null), device (null), target_url (null). Unique (project_id, phrase, country, device) |
| `rank_checks` | id, keyword_id → keywords, audit_id (null) → audits, checked_at, provider, status (`ranked` / `not_ranked` / `skipped`), position (null), ranking_url (null), note (null) |
| `competitors` | id, project_id, domain. Unique (project_id, domain) |
| `backlink_snapshots` | id, project_id, taken_at, provider, metrics_json |
| `ai_visibility_runs` | id, project_id, ran_at, provider, prompt, result_json |

The last three are shells for Phases 6–7; their columns will be revised by
migrations in those phases.

**Project domain rule:** `project_domain(url)` returns the lowercased host
with `www.` and any port removed (`https://WWW.Example.com:443/x` →
`example.com`). Subdomains other than `www` are separate projects.

### 2. Persisting audits — `app/db/audit_store.py`

`record_audit(session_factory, session_db, result, *, session_id, start_url,
trigger, started_at) -> Optional[int]`:

1. Find or create the project by `project_domain(start_url)`.
2. Insert the `audits` row: status `partial` if `result["partial"]`, otherwise
   `completed`; `health_score` from
   `result["executive_summary"]["health_score"]["score"]`; `summary_json` is the
   summary fields only (the `SUMMARY_FIELDS` set in `routes.py`, moved to a shared
   constant), never page rows.
3. Stream pages and issues from the session DB in batches of 500, using new
   `SessionDB.iter_pages(batch)` / `iter_issues(batch)` generators, and
   bulk-insert them. Memory stays flat at 5000 pages.
4. For each page's `keyword_analysis.rankings` entry, upsert a `keywords` row
   (project, phrase, target_url = page URL) and insert a `rank_checks` row
   linked to the audit (provider `google_cse`).
5. All in one transaction, returning the new audit id.

Called once at the end of `audit_service._build_audit_result`, after
`db.set_summary`, so the API, CLI and harness all persist. **Any exception is
caught and logged; the audit result gains `persisted: false` and
`audit_id: null`, and the audit itself still succeeds.** On success the result
carries `audit_id` and `project_id`.

`_build_audit_result` gains `trigger: str = "manual"` (the scheduler passes
`scheduled`).

**Backfill:** `python -m app.db.import_sessions [--session-dir DIR]` walks
existing session files, skips any `session_id` already in `audits`, and records
the rest with `trigger="import"`, `started_at` from the summary's `saved_at`.
Re-running it is a no-op.

### 3. Diff — `app/db/diff.py`

`diff_audits(session, old_id, new_id) -> AuditDiff`:

- Issues are keyed by `(url, code)`:
  - `new`: in the new audit only
  - `fixed`: in the old audit only
  - `persisting`: count only
- Pages are keyed by `url`:
  - `added`
  - `removed`
  - `status_changed` (old status → new status)
- Plus `health_score_change`.
- Both audits must belong to the same project, otherwise `ValueError` → HTTP 400.

Computed in SQL (anti-joins on the indexed columns), not by loading both audits
into Python.

### 4. API — `app/api/projects.py` (new router, mounted under `/api`)

- `GET /api/projects`: id, name, domain, audit_schedule, latest audit
  (id, finished_at, health_score), audit_count.
- `POST /api/projects` `{domain, name?, audit_schedule?, audit_options?}`
  creates a project, or returns 409 if one exists for that domain.
- `PATCH /api/projects/{id}`: name, audit_schedule, audit_options.
- `GET /api/projects/{id}/audits?offset&limit`: newest first.
- `GET /api/audits/{id}/diff?against={id}`: `against` defaults to the previous
  audit of the same project. 404 if there is none.

Existing endpoints are unchanged.

### 5. Scheduler — `app/scheduler/`

- `jobs.run_due_audits(now)`: selects projects whose `audit_schedule` is due
  (`daily`: `last_scheduled_at` older than 24h or null; `weekly`: 7 days),
  claims each by setting `last_scheduled_at = now` in an `UPDATE … WHERE
  last_scheduled_at IS <old value>` (so two triggers can't claim the same
  project), and runs `run_full_audit` for each claimed project, one at a time,
  with its `audit_options_json` and `trigger="scheduled"`. Returns the list of
  started session ids.
- **APScheduler** (`BackgroundScheduler`, a 15-minute interval job calling
  `run_due_audits`) starts with the API only when `SCHEDULER_ENABLED=true`.
  Off by default and in tests.
- **`POST /api/cron/run`**: requires `Authorization: Bearer <CRON_SECRET>`,
  compared with `hmac.compare_digest`.
  - **404** when `CRON_SECRET` is unset, so the endpoint does not exist until
    configured.
  - **401** on a wrong or missing token.
  - Otherwise it runs `run_due_audits` in a background task and returns
    `{"started": [...]}` immediately.
- Docs: crawls run on the always-on VM (Oracle). Vercel serverless can't run
  them. A cron service only needs to POST to the endpoint.

### 6. Config, deploy, docs

- `config.py`: `DATABASE_URL`, `CRON_SECRET`, `SCHEDULER_ENABLED`.
- `.env.example`: the three keys with placeholders only.
- `deploy/oracle/docker-compose.yml`: an optional `postgres:16-alpine` service
  with its own volume and healthcheck. The backend's `DATABASE_URL` comes from
  `${DATABASE_URL:-}` so the SQLite default still works without it.
- `requirements.txt`: `sqlalchemy>=2.0`, `alembic>=1.13`,
  `apscheduler>=3.10,<4`, `psycopg[binary]>=3.1`.
- `docs/env.md`, `docs/api.md`, `README.md`: the new variables, endpoints, the
  backfill command, and a "How to verify" section.

## Error handling

- DB unavailable or a migration failing at API startup: log an error and keep
  serving. Audits run and report `persisted: false`, and the project endpoints
  return 503. The audit path never depends on the central DB.
- A crawl with zero pages is still recorded (status from the result), so a
  failed site appears in history rather than vanishing.
- Scheduled audit errors are logged per project and do not stop the others.

## Testing

- **Migration:** the initial migration applies to an empty SQLite DB and
  produces every table and unique constraint. An opt-in Postgres test
  (`PG_TEST=1`) runs the same migration against Docker `postgres:16-alpine`.
- `project_domain` table: www, ports, case, subdomains.
- `record_audit`:
  - Two audits of one site land in one project.
  - Pages and issues are copied completely, and in batches. A session with
    1,200 pages runs as three batches, which the test checks.
  - Rank results become `keywords` and `rank_checks` rows.
- `_build_audit_result` with a broken DB: the audit returns normally with
  `persisted: false`.
- `diff_audits`:
  - new, fixed and persisting issues
  - added and removed pages
  - status changes
  - the health score delta
  - audits from different projects raise an error
- Backfill: imports, then a second run imports nothing.
- `run_due_audits`: due vs not-due projects, `daily` vs `weekly`, and two
  concurrent calls claim a project once (`run_full_audit` is mocked).
- `/api/cron/run`: 404 without a secret, 401 for a wrong token, 202 that runs
  due jobs.
- Project endpoints: listing, creation conflict, pagination, and the default
  `against` for diffs.
- The existing 342 backend and 57 frontend tests keep passing.

## Done when

A real audit is stored and listed under its project, a second audit of the same
site is diffed against it (new/fixed issues), and both are visible through the
new endpoints. Verified with two audits of books.toscrape.com.

## Out of scope

- Moving existing readers (pages, issues, exports, page cache) to the central DB.
- Frontend changes (Phase 4).
- Rank-check scheduling and alerts (Phase 2).
- Retention or cleanup of central DB data.
