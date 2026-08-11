# REST API Documentation

## Endpoints

### 1. Execute SEO Audit
- **URL**: `/api/audit`
- **Method**: `POST`
- **Content-Type**: `application/json`

#### Request Body
```json
{
  "url": "https://example.com",
  "max_pages": 8,
  "max_depth": 1,
  "ignore_robots": false,
  "enable_keyword_analysis": true,
  "enable_keyword_suggestions": false,
  "enable_rank_check": false,
  "enable_competitor_gap": false,
  "target_keywords": null
}
```

- `enable_keyword_analysis` (default `true`): extracts on-page keywords per page. Pure local computation, no external calls. This flag gates extraction only — it does **not** gate keyword suggestions (see `enable_keyword_suggestions` below).
- `enable_keyword_suggestions` (default `false`): generates suggested keywords via the Google Autocomplete endpoint (an unofficial, undocumented endpoint) — up to 3 external network calls per page. Off by default because it costs real network calls with no quota protection, unlike `enable_keyword_analysis`. When `enable_competitor_gap` is also set, this step additionally fetches competitor pages.
- `enable_rank_check` (default `false`): checks live Google rank for each page's top keywords via the Google Custom Search API. Costs quota (100 free queries/day) — see `docs/env.md`. Requires `GOOGLE_CSE_API_KEY`/`GOOGLE_CSE_CX`; without them, results carry a "not configured" note instead of an error.
- `enable_competitor_gap` (default `false`): fetches the top-ranking competitor pages for each page's top keyword and diffs their keywords against the current page's. Only takes effect when `enable_keyword_suggestions` is also set — competitor-gap is a sub-step of the suggestions pipeline. Costs extra page fetches and, if `enable_rank_check` is off, may also cost CSE quota.
- `target_keywords` (default `null`): when provided, overrides automatic keyword extraction — ranking/suggestions are computed for these keywords instead.

> Note: `enable_rank_check`, `enable_competitor_gap`, and `enable_keyword_suggestions` are currently only settable via direct API calls — the dashboard UI does not yet expose toggles for them (that build-out is deferred to a future release).

#### Success Response (200 OK)
Returns full `AuditResponse` JSON containing `executive_summary`, `pages`, `recommendations`, `duplicates`, `broken_links`, `site_wide_analysis`, `elapsed_seconds`, and `note`. Each item in `pages` now optionally carries a `keyword_analysis` object:
```json
{
  "top_keywords": [{ "phrase": "espresso machine", "score": 5.0, "found_in": ["title", "h1"] }],
  "rankings": [{ "keyword": "espresso machine", "position": 3, "note": null, "checked_at": "2026-08-11T00:00:00+00:00" }],
  "suggested_keywords": [{ "phrase": "espresso machine reviews", "reason": "related search", "competitor_examples": null }]
}
```
`rankings` is empty unless `enable_rank_check` was set. `suggested_keywords` is empty unless `enable_keyword_suggestions` was set (competitor-gap entries only appear if `enable_competitor_gap` was also set).

---

### 2. Service Health Check
- **URL**: `/api/health`
- **Method**: `GET`

#### Success Response (200 OK)
```json
{
  "status": "ok",
  "service": "seo-auditor-backend",
  "timestamp": "2026-07-23T19:30:00.000Z"
}
```
