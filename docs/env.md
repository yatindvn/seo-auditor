# Environment Variables Reference

## Frontend Environment Variables (`apps/frontend/.env`)

| Variable | Description | Default |
| --- | --- | --- |
| `VITE_API_URL` | Base URL for REST API backend | `http://localhost:5000` |
| `VITE_WS_URL` | Base URL for WebSocket server | `ws://localhost:5000` |
| `NEXT_PUBLIC_API_URL` | Next.js public REST API backend | `http://localhost:5000` |
| `NEXT_PUBLIC_WS_URL` | Next.js public WebSocket backend | `ws://localhost:5000` |

## Backend Environment Variables (`apps/backend/.env`)

| Variable | Description | Default |
| --- | --- | --- |
| `PORT` | Backend HTTP & WebSocket port | `5000` |
| `NODE_ENV` | Environment mode (`development` / `production`) | `development` |
| `CRAWL_TIMEOUT` | Python HTTP request timeout (seconds) | `10` |
| `MAX_DEPTH` | Maximum BFS crawl depth cap | `2` |
| `HF_TOKEN` | HuggingFace Token for AI suggestions | `""` |
| `GOOGLE_CSE_API_KEY` | Google Custom Search JSON API key, used for live rank checking | `""` |
| `GOOGLE_CSE_CX` | Google Programmable Search Engine ID (the "cx" parameter) | `""` |
| `GOOGLE_CSE_DAILY_QUOTA` | Max Google CSE queries per UTC day before rank checks start returning "quota reached" | `100` |
| `GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE` | Max *automatically extracted* keywords ranked per page (caps quota spend from extraction only — a user's explicit `rank_targets` keywords are never dropped by this cap) | `3` |
| `GOOGLE_CSE_CACHE_TTL_HOURS` | How long a (keyword, domain) rank result is cached before re-querying | `24` |
| `SESSION_DIR` | Directory for per-audit SQLite files; also holds `central/` (the default central DB) and `page_cache/` | `./sessions` |
| `DATABASE_URL` | Central database for projects, audit history and rank checks. `postgresql+psycopg://user:pass@host:5432/db` for Postgres | `sqlite:///$SESSION_DIR/central/platform.db` |
| `CRON_SECRET` | Bearer token required by `POST /api/cron/run`. Unset disables the route (404) | `""` |
| `SCHEDULER_ENABLED` | Run due scheduled audits inside the API process every 15 minutes | `false` |
| `PAGE_CACHE_MAX_AGE_DAYS` | A cached page analysis older than this is redone even if the server reports the page unchanged | `30` |
| `CRAWL_CONCURRENCY` | Concurrent fetches a crawl starts with | `32` |
| `CRAWL_MAX_CONCURRENCY` | Ceiling adaptive concurrency may grow to while the site responds well | `64` |
| `SERP_PROVIDER` | Rank data source: `dataforseo`, `google_cse` or `dry_run`. Unset: `google_cse` when its key is set, otherwise `dry_run` | `""` |
| `SERP_DRY_RUN` | Paid providers return made-up results (never stored) until this is exactly `false` | `true` |
| `SERP_DAILY_CAP` | Hard daily cap on paid SERP calls (DataForSEO), counted in the database | `50` |
| `RANK_DEPTH` | Results requested per tracked keyword (DataForSEO max 200; Google CSE returns at most 10) | `100` |
| `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` | DataForSEO API credentials | `""` |
| `DATAFORSEO_LABS_DAILY_CAP` | Hard daily cap on DataForSEO keyword-data calls (search volume, difficulty, ranked keywords). Cache hits are free and not counted | `20` |
| `DATAFORSEO_BACKLINKS_DAILY_CAP` | Hard daily cap on DataForSEO Backlinks API requests (a snapshot is 5 requests, about $0.25) | `20` |
| `PSI_API_KEY` | Google PageSpeed Insights key for Core Web Vitals. Empty = PSI not used | `""` |
| `PSI_DAILY_CAP` | Hard daily cap on PSI calls | `50` |
| `PSI_MAX_PAGES` | Pages measured per audit (start URL + top pages by internal PageRank) | `5` |
| `LIGHTHOUSE_ENABLED` | Local Lighthouse fallback (needs Node, Chrome, `npm i -g lighthouse@12`) | `false` |
| `CHROME_PATH` | Chrome binary for Lighthouse; auto-detected when empty | `""` |
| `LIGHTHOUSE_CLI` | Path to Lighthouse's `cli/index.js`; found via `npm root -g` when empty | `""` |
| `RENDER_MAX_PAGES` | Pages rendered in headless Chromium per audit when `render_js` is on | `20` |
| `RENDER_TIMEOUT_MS` | Per-page navigation timeout for rendering | `20000` |
| `GSC_SERVICE_ACCOUNT_FILE` | Path to a Google service account's JSON key for Search Console (read-only). Empty = not used | `""` |
| `GSC_DRY_RUN` | `true` = made-up Search Console data, to try the UI without Google | `false` |
| `GSC_DAILY_CAP` | Hard daily cap on Search Console analytics calls | `100` |
| `GSC_INSPECT_DAILY_CAP` | Hard daily cap on URL Inspection calls | `200` |
| `GSC_INSPECT_MAX_PAGES` | Pages inspected per audit | `20` |
| `ANTHROPIC_API_KEY` | Anthropic key for AI Visibility (Claude with web search). Empty = Claude not used | `""` |
| `ANTHROPIC_MODEL` | Claude model asked | `claude-sonnet-5` |
| `OPENAI_API_KEY` | OpenAI key for AI Visibility (Responses API with web search) | `""` |
| `OPENAI_MODEL` | OpenAI model asked; required with the key (no default) | `""` |
| `GEMINI_API_KEY` | Gemini API key for AI Visibility (Google Search grounding) | `""` |
| `GEMINI_MODEL` | Gemini model asked; required with the key (no default) | `""` |
| `ANTHROPIC_WEB_SEARCH_TOOL` | Claude web-search tool version | `web_search_20250305` |
| `OPENAI_WEB_SEARCH_TOOL` | OpenAI web-search tool type | `web_search` |
| `AI_VISIBILITY_DRY_RUN` | `true` = made-up answers even with keys set (also the behaviour with no keys) | `false` |
| `AI_VISIBILITY_DAILY_CAP` | Hard daily cap on AI calls (one prompt x one model = one call) | `30` |
| `GOOGLE_CSE_DAILY_QUOTA` | Daily cap on Google CSE calls, now counted in the database and shared by audits and rank tracking | `100` |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook for rank alerts | `""` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | SMTP server for email alerts (STARTTLS) | `""` / `587` |
| `ALERT_EMAIL_FROM` / `ALERT_EMAIL_TO` | Sender, and comma-separated recipients, of email alerts | `""` |

### Getting a free Google CSE API key + CX

Both `enable_rank_check` and `enable_competitor_gap` require these two values. Without them, keyword ranking/suggestion features degrade gracefully (see `docs/api.md`) rather than failing.

1. Go to the [Programmable Search Engine control panel](https://programmablesearchengine.google.com/controlpanel/create) and create a new search engine. Set it to search the entire web.
2. Copy the **Search engine ID** shown in the setup panel — this is `GOOGLE_CSE_CX`.
3. Go to the [Google Cloud Console credentials page](https://console.cloud.google.com/apis/credentials), enable the **Custom Search API** for your project, and create an API key — this is `GOOGLE_CSE_API_KEY`.
4. The free tier is 100 queries/day; `GOOGLE_CSE_DAILY_QUOTA` should match whatever quota your Google Cloud project actually has.
