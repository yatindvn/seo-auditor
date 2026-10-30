# SEO Platform Build Brief (for Claude Code)

## Goal
Grow the existing `seo-auditor` project from a site-audit tool into an Ahrefs-style
SEO platform: Site Audit, Rank Tracker, Keywords Explorer, Content Gap, Backlinks,
AI Visibility, with history, scheduling, and a dashboard.

## Step 0: Inspect before building (do this first, do not write code yet)
1. Read the whole repo (apps/, packages/, api/, seo_auditor/, docs/, .superpowers/ plans,
   tests, README). The local code is ahead of what GitHub shows (branch
   `feat/keyword-rank-tracking`, worktree `keyword-intelligence`).
2. Write `docs/GAP_REPORT.md`: for each feature in the table below, mark
   Built / Partial / Missing, citing file paths as evidence.
3. Show me the report and the proposed phase order. Wait for my OK.

| Feature | Expected state |
|---|---|
| Site Audit (17 modules, exports) | Built, needs JS rendering, real Core Web Vitals, history |
| Rank Tracker | In progress (rank status, RankTarget, max_keywords) |
| Keywords Explorer | In progress (keyword suggestions) |
| Content Gap | In progress (competitor-gap path) |
| Backlinks / Site Explorer | Missing |
| Content Explorer (small version) | Missing |
| AI Visibility (Brand Radar-style) | Missing |
| Database, scheduler, alerts | Missing |
| Next.js dashboard | Planned only |

## Working rules
- Work on a new branch per phase (`feat/<phase-name>`). Small commits, clear messages.
- Never commit secrets. All keys go in `.env` (add `.env.example` with placeholder names only).
- Do not break existing CLI/API behavior. Run the full backend test suite before each commit.
- Write tests first for new logic (TDD). Mock all paid/external APIs in tests.
- Before any step that spends paid API credits, add a hard cap (env var, default low)
  and a dry-run mode. Ask me before first live call.
- Keep each external data source behind a provider interface so it can be swapped.
- Stop at the end of each phase, summarize what changed and how to verify, and wait for me.

## Phase 1: Foundation (database + scheduler)
- Add Postgres via SQLAlchemy + Alembic. SQLite fallback for local dev (`DATABASE_URL`).
- Tables: projects, audits, audit_pages, audit_issues, keywords, rank_checks,
  competitors, backlink_snapshots, ai_visibility_runs.
- Persist every audit and rank check with timestamps so runs can be compared.
- Scheduler: APScheduler for local, plus an HTTP endpoint (`/api/cron/run`, secret-protected)
  so a cron service can trigger jobs. Note: long crawls cannot run on Vercel serverless;
  document that workers should run on Render/Railway/Fly.io.
- Done when: an audit run is stored, listed, and two runs can be diffed (new/fixed issues).

## Phase 2: Finish Rank Tracker
- Complete the work in the current branch; finish the pending end-to-end verification.
- Add history per keyword, device (desktop/mobile), country/location, competitor tracking.
- Position-change alerts (email and/or Slack webhook), configurable thresholds.
- Provider interface for SERP data (DataForSEO first; Google Search Console for owned sites).
- Done when: scheduled daily checks write history and an alert fires on a simulated drop.

## Phase 3: Provider layer + Keywords Explorer + Content Gap
- `providers/` package with interfaces: SerpProvider, KeywordMetricsProvider, BacklinkProvider.
  Implement DataForSEO adapters (env: DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD).
- Keywords: suggestions (Google Autocomplete + People Also Ask), search volume,
  keyword difficulty, traffic potential, clustering by SERP overlap.
- Content Gap: compare my domain vs 1..N competitors, rank by opportunity
  (volume x difficulty), export CSV.
- Cache provider responses in the DB to avoid repeat spend.

## Phase 4: Frontend dashboard (Next.js + Tailwind + shadcn/ui + Recharts)
- Pages: projects, audit results (score, severity chart, recommendations, pages table,
  broken links, duplicates), audit history/diff, rank tracker charts, keyword explorer,
  content gap table.
- Run `npx getdesign@latest add apple` for the design tokens if it resolves; if it
  fails, continue with shadcn defaults. Use the UI/UX skill for composition and spacing.
- Severity colors: critical red, warning amber, info slate. Responsive, with explicit
  loading, empty and error states.

## Phase 5: Complete Site Audit
- JS rendering with Playwright (optional flag), rendered vs raw HTML comparison.
- Core Web Vitals via PageSpeed Insights API (env: PSI_API_KEY) with Lighthouse fallback.
- Full accessibility audit with axe-core through Playwright.
- Custom rule engine: user-defined checks stored per project.
- Google Search Console integration for indexing, clicks, impressions.

## Phase 6: Backlinks (Site Explorer)
- BacklinkProvider via DataForSEO: referring domains, backlinks, new/lost links,
  broken backlinks, an authority score (clearly labeled as provider-derived).
- Store snapshots to chart growth over time.

## Phase 7: AI Visibility + small Content Explorer
- AI Visibility: user-defined prompts sent to Claude/OpenAI/Gemini APIs; record whether
  the brand is mentioned, position, and cited sources; track over time.
- Content Explorer (small): for a topic, fetch top SERP results through the SerpProvider,
  run our on-page analysis on them, and show word count, headings, schema, backlinks.

## Definition of done (every phase)
- Tests pass, new code covered, README/docs updated, `.env.example` updated.
- A short "How to verify" section I can follow in under 5 minutes.
