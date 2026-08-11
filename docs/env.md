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
| `GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE` | Max keywords ranked per page per audit (caps quota spend) | `3` |
| `GOOGLE_CSE_CACHE_TTL_HOURS` | How long a (keyword, domain) rank result is cached before re-querying | `24` |

### Getting a free Google CSE API key + CX

Both `enable_rank_check` and `enable_competitor_gap` require these two values. Without them, keyword ranking/suggestion features degrade gracefully (see `docs/api.md`) rather than failing.

1. Go to the [Programmable Search Engine control panel](https://programmablesearchengine.google.com/controlpanel/create) and create a new search engine. Set it to search the entire web.
2. Copy the **Search engine ID** shown in the setup panel — this is `GOOGLE_CSE_CX`.
3. Go to the [Google Cloud Console credentials page](https://console.cloud.google.com/apis/credentials), enable the **Custom Search API** for your project, and create an API key — this is `GOOGLE_CSE_API_KEY`.
4. The free tier is 100 queries/day; `GOOGLE_CSE_DAILY_QUOTA` should match whatever quota your Google Cloud project actually has.
