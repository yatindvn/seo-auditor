# Gap Report — SEO Auditor → Ahrefs-style platform

**Date:** 2026-10-25
**Scope:** Step 0 of `BUILD_PROMPT.md` — inspect only, no code changed.
**Inspected at:** branch `feat/crawl-dedup` @ `e227c5c` (the most advanced local
state; **not yet merged to `main`**). Backend: 342 tests passing. Frontend: 54
tests passing, `tsc` clean.

---

## 1. Corrections to the brief's assumptions

| Brief says | Actual state | Evidence |
| --- | --- | --- |
| Read `api/` and `seo_auditor/` | Neither exists. They were the pre-monorepo layout, replaced by `apps/backend` and removed. | `git log`: `33cde9f` (monorepo refactor), PR #22 `refactor/delete-duplicate-engine` |
| Local code is on branch `feat/keyword-rank-tracking`, worktree `keyword-intelligence` | Both were merged and no longer exist: PR #1 (`worktree-keyword-intelligence`), PR #3 (`feat/keyword-rank-tracking`). `git worktree list` shows one worktree. The newest local work is on `feat/crawl-dedup` (crawl dedup, cross-audit page reuse, a history fix, crawl speed), 23 commits ahead of `main`. | `git branch -a`, `git worktree list` |
| Next.js dashboard: "Planned only" | **Built**: Next.js 14 + Tailwind + shadcn-style `components/ui` + Recharts, ~24 panels, live crawl over WebSocket, 54 tests. What's missing is the *platform* shape (projects, per-tool pages). | `apps/frontend/app/dashboard/page.tsx`, `apps/frontend/components/*` |
| Site Audit has 17 modules | 19 `check_*` functions, plus page-weight/performance proxies, site-wide analysis (PageRank, orphans, duplicates), and Part A/B dedup and reuse. | `apps/backend/app/auditor/checks.py`, `app/utils/performance.py`, `app/analysis/analysis.py` |
| Workers should run on Render/Railway/Fly.io | A long-running backend host already exists: Docker + Caddy on an Oracle VM. The Vercel frontend never runs crawls. | `deploy/oracle/docker-compose.yml`, `deploy/oracle/Caddyfile`, `docs/deployment-oracle.md`, `vercel.json` |

---

## 2. Feature status

### Site Audit — **Built** (gaps: JS rendering, real CWV, project-level history)

| Capability | Status | Evidence |
| --- | --- | --- |
| BFS crawler, robots, sitemaps (crawled), redirects, retries | Built | `app/crawler/crawler.py` |
| Adaptive concurrency, 429/`Retry-After` backoff, `Crawl-delay` | Built (unmerged) | `app/crawler/throttle.py`, `crawler.py` (`AdaptiveLimit`) |
| 19 on-page checks | Built | `app/auditor/checks.py` (`check_status_and_https` … `check_js_rendering_signal`) |
| Site-wide: PageRank, orphans, dead ends, duplicates (exact + MinHash) | Built | `app/analysis/analysis.py`, `app/analysis/minhash.py` |
| One check per page (aliases, body-hash duplicates) | Built (unmerged) | `crawler.py` (`_owner_of`), `docs/superpowers/specs/2026-10-25-crawl-dedup-design.md` |
| Reuse of unchanged pages across audits (ETag/304, page cache) | Built (unmerged) | `app/models/page_cache.py`, `docs/superpowers/specs/2026-10-25-page-reuse-design.md` |
| Exports: JSON, CSV, XLSX, PDF summary, HTML | Built | `app/utils/report.py:198-299`, `GET /api/export/{fmt}` (`app/api/routes.py:328`) |
| Recommendations / prioritisation | Built (rule-based, not AI) | `app/ai/ai_suggestions.py` |
| **JS rendering** | **Missing**: only a heuristic flag for JS-dependent pages; no browser | `checks.py` `check_js_rendering_signal`; no Playwright/Selenium in `requirements.txt` |
| **Core Web Vitals** | **Partial**: PSI client exists, wired into the **CLI only** (`--psi-key`); the API/UI never passes a key; no Lighthouse fallback | `app/utils/performance.py:89` `fetch_psi_metrics`; `app/cli.py:70,108`; `run_full_audit` has no `psi_key` |
| **Accessibility** | **Partial**: heuristic checks (alt text, lang, labels); no axe-core | `checks.py` `check_accessibility` |
| **History** | **Partial**: one SQLite file per audit, last 20 kept; history list/delete API; UI compares *recommendation codes* of two sessions client-side. No projects, no page/issue-level diff, nothing survives retention. | `app/models/session_model.py` (`RETENTION = 20`), `app/models/session_db.py`, `routes.py:283,296`, `components/historical-comparison-panel.tsx:57-58` |
| Custom rule engine, Search Console | Missing | none found |

### Rank Tracker — **Partial** (merged, end-to-end check never run)

| Capability | Status | Evidence |
| --- | --- | --- |
| Rank lookup per nominated page/keyword (`RankTarget`, `max_keywords`, rank status) | Built | `app/seo/rank_checker.py:135` `check_rankings`; `app/schemas/schemas.py` `RankTarget`; `audit_service.py` `_match_rank_target` |
| Provider | Google Custom Search JSON API only, hard-wired (not behind an interface) | `rank_checker.py:17` `CSE_ENDPOINT` |
| Quota + cache | In-memory only: resets on every restart | `rank_checker.py:29-45` |
| UI: rank status, "instead of" suggestions | Built | `components/keyword-panel.tsx` |
| **End-to-end verification with real credentials** | **Pending**: plan Task 11 is a manual gate needing your Google CSE key | `.superpowers/sdd/2026-08-15-keyword-rank-tracking/progress.md` ("PLAN COMPLETE except Task 11") |
| History per keyword, device, country, competitors, scheduling, alerts | Missing | no persistence of rank results outside the audit summary |

> **Risk to check before Phase 2:** Google has announced that the Custom Search
> JSON API is closed to new customers and being wound down. Please confirm its
> status for your account before relying on it. Either way, this makes the brief's
> plan to put SERP data behind a provider interface (DataForSEO first) the right
> call, not just a nice-to-have.

### Keywords Explorer — **Partial** (suggestions only)

| Capability | Status | Evidence |
| --- | --- | --- |
| On-page keyword extraction (weighted n-grams) | Built | `app/seo/keyword_extraction.py` |
| Suggestions from Google Autocomplete | Built (unofficial endpoint, no cap) | `app/seo/keyword_suggestions.py:20,27` |
| People Also Ask, search volume, difficulty, traffic potential, SERP clustering | Missing | none found |
| Standalone explorer (keyword in → ideas out) | Missing: suggestions only exist inside a site audit | `keyword_suggestions.py:102` `suggest_keywords` (per crawled page) |

### Content Gap — **Partial** (per-page prototype)

| Capability | Status | Evidence |
| --- | --- | --- |
| Competitor keyword gap | Partial: fetches competitor *pages* and diffs extracted keywords for one audited page; not domain-level, no opportunity ranking, no CSV | `keyword_suggestions.py:58` `_competitor_gap`, gated by `enable_competitor_gap` |

### Backlinks / Site Explorer — **Missing**
No references to backlinks, referring domains or a backlink provider in
`apps/`, `packages/` or `docs/`.

### Content Explorer (small) — **Missing**
None found.

### AI Visibility (Brand Radar-style) — **Missing**
No LLM client of any kind. `app/ai/ai_suggestions.py` is a rule-based scorer
despite its folder name. (`HF_TOKEN` is listed in `apps/backend/.env` but unused
by the code.)

### Database, scheduler, alerts — **Partial / Missing**

| Capability | Status | Evidence |
| --- | --- | --- |
| Persistence | Partial: raw SQLite, one file per audit, plus a per-site page cache; no ORM, no Postgres, no migrations, no projects/keywords tables | `app/models/session_db.py`, `app/models/page_cache.py`; no SQLAlchemy/Alembic in `requirements.txt` |
| Scheduler / cron endpoint | Missing | none found |
| Alerts (email/Slack) | Missing | none found |

### Next.js dashboard — **Built** (single-audit tool, not yet a platform)

| Capability | Status | Evidence |
| --- | --- | --- |
| Start form with presets, advanced overrides, rank targets | Built | `app/page.tsx` |
| Audit dashboard: score, severity chart, recommendations, pages table, broken links, duplicates, architecture graph, ~20 more panels | Built | `app/dashboard/page.tsx`, `components/*` |
| Live crawl view | Built | `app/live-crawl/page.tsx`, `components/live-crawl-panel.tsx` |
| Projects, audit diff page, rank charts, keyword explorer, content gap pages | Missing | only 3 page routes exist: `/`, `/dashboard`, `/live-crawl` |

---

## 3. Things to fix before (or at the start of) Phase 1

**Phase 0 status:** items 1 and 2 are done (see below). Item 3 is still open.

1. **Command injection in `apps/frontend/app/api/audit/route.ts:34`.** When
   `NEXT_PUBLIC_API_URL`/`VITE_API_URL` is unset, the route builds
   `python -m app.cli "${url}" …` from the request body and runs it with
   `exec`. A `url` containing `"` or `$(…)` runs arbitrary commands on the
   Next.js host. The app's own UI never calls this route (it calls the backend
   directly), so the fix is to delete the fallback branch. Production is
   currently safe only because `.env.production` sets the variable.
   **Done:** commit `a7c192e`. The fallback is removed; with no backend URL the
   route returns 503. Covered by `app/api/audit/route.test.ts`.
2. **Merge `feat/crawl-dedup` into `main` first.** Phase branches should start
   from a `main` that contains the dedup, page-reuse, history-fix and speed work,
   or every phase will conflict with it.
   **Done:** merged into local `main` as `4759ae9`, then verified: backend 342
   passed, frontend 54 passed, `tsc` clean, `npm run build` succeeded. Not pushed.
3. **Rank tracker Task 11** (manual E2E with real credentials) has never run.
   This is the brief's "pending end-to-end verification".

Hygiene, already fine: `apps/backend/.env` is gitignored and has never been
committed; `apps/backend/.env.example` exists.

---

## 4. Proposed phase order

The brief's order mostly holds. Three adjustments:

| # | Phase | Change from the brief, and why |
| --- | --- | --- |
| 0 | **Prep** (small): fix the route.ts injection, merge `feat/crawl-dedup`, decide CSE vs DataForSEO | New. Security fix plus a clean base. Under an hour of work. |
| 1 | **Foundation**: SQLAlchemy + Alembic, Postgres with SQLite fallback, projects/audits/pages/issues/keywords/rank_checks tables, APScheduler + `/api/cron/run`, audit diff | As briefed. **Design constraint:** keep the existing per-session SQLite API working (history panel, exports, page cache) until the new tables replace each reader. Workers stay on the existing Oracle VM rather than adding Render/Railway. |
| 2 | **Provider layer + Rank Tracker**: `SerpProvider` interface, DataForSEO SERP adapter (cap + dry-run), Google CSE adapter kept as a second provider, then history/device/country/competitors/alerts | **Moved up:** the brief's Phase 2 needs a SERP provider that the brief only builds in Phase 3. Build only the SERP part of the provider layer here. |
| 3 | **Keywords Explorer + Content Gap**: `KeywordMetricsProvider`, volume/difficulty/PAA, clustering, domain-level gap with CSV, DB-cached responses | As briefed, minus the SERP interface already built in Phase 2. |
| 4 | **Dashboard: platform pages**: projects, audit history/diff, rank charts, keyword explorer, content gap | **Reframed:** *extend* the existing Next.js app rather than build one. The `npx getdesign@latest add apple` step is an unverified third-party package; I'll ask before running it. |
| 5 | **Complete Site Audit**: Playwright rendering (flag), PSI wired into the API (+ Lighthouse fallback), axe-core, custom rules, Search Console | As briefed. Playwright needs a browser in the ARM Docker image on the VM: check size and memory first. |
| 6 | **Backlinks** | As briefed. |
| 7 | **AI Visibility + small Content Explorer** | As briefed. |

**Paid APIs:** every phase that calls DataForSEO, PSI or LLM APIs gets an
env-var hard cap (default low) and a dry-run mode, all mocked in tests. I'll ask
you before the first live call, per the brief.

---

## 5. Decisions I need from you

1. Approve this phase order, including **Phase 0**.
2. OK to **merge `feat/crawl-dedup` into `main`** as part of Phase 0?
3. Rank data provider: confirm your **Google CSE** status, and whether you have
   (or will get) **DataForSEO** credentials. Phase 2 can start on mocks either way.
