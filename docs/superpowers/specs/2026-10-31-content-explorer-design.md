# Content Explorer (Phase 7.2): Design

**Status:** approved in brainstorming on 2026-10-31.
**Branch:** `feat/content-explorer`

## Goal

You give a topic. The tool:
- fetches the top 10 organic results through the existing SERP provider
- runs our own on-page analysis on each one
- adds backlink counts

You then see what the ranking pages have in common (length, headings,
schema, links), so you know what a page needs to compete.

## Decisions

- **Global page** at `/content`, beside Keywords Explorer. No project needed.
- **Backlinks:** two DataForSEO bulk requests cover all 10 URLs, about $0.05 a search.
- **Cache:** each search is kept for 7 days. A repeat search inside that window is free, and a Refresh button forces a new fetch.

## How a search runs

`explore(topic, country, language, refresh=False, serp=None, backlinks=None, fetch=None)`:

1. **Normalise and validate.**
   - The topic is trimmed, lowercased, with spaces collapsed, and must be 2–80 characters.
   - The country is 2 letters and upper case; the language is 2 letters and lower case.
2. **Cache.** Without `refresh`, return the newest live search from the last 7 days with the same topic, country and language, with `cached: true`.
   - Dry-run searches are never served from the cache.
   - Dry-run searches are still saved, so they show in the recent list and can be reopened.
3. **SERP.** `get_serp_provider().search(SerpQuery(topic, country, language, depth=10))` takes the top 10 organic items.
   - One call, counted against `SERP_DAILY_CAP` as today.
   - At the cap (`ProviderSkipped`), return 429 and save nothing.
   - On any other provider error, return 502 and save nothing.
4. **Pages.** With a live SERP, every result is fetched with the audit's single-page fetch (`fetch_page`, 15 s timeout, 1 retry), 4 at a time. Each fetched page goes through `page_pipeline.analyze_page` with keyword analysis off. Per result we keep:
   - `status`
   - `error`: the fetch error, or `HTTP <code>` when the status is ≥ 400
   - `title` (from the SERP if the page has none)
   - `word_count` and `h1`
   - `outline`: the first 30 H2/H3 as `{level, text}`, text cut to 120 characters
   - `schema_types`: the `@type` values from valid JSON-LD, including inside `@graph` and lists, deduplicated, at most 10
   - `images`, `internal_links`, `external_links`
   - `readability`: Flesch score
   - `issues`: the number of error and warning issues
   - A page that fails keeps its SERP fields, with the rest set to `null`.
5. **Backlinks.** One `bulk_metrics(urls)` call on the backlink provider returns `{url: (backlinks, referring_domains)}`.
   - DataForSEO makes 2 requests: `POST /v3/backlinks/bulk_backlinks/live` and `POST /v3/backlinks/bulk_referring_domains/live`, each with `{"targets": [urls]}`. Each request first takes one unit of `DATAFORSEO_BACKLINKS_DAILY_CAP`.
   - At the cap, or on an error, the backlink fields are `null` and a note explains why. The on-page data still returns.
6. **Summary.** Computed over the pages that were fetched:
   - `median_words`
   - `schema_counts`: `{type: number of results using it}`, sorted by count
   - `median_referring_domains`
   - `common_h2_terms`: the top 15 words of 3 or more letters from H2 text, without stop words, each counted once per page, with `{term, count}` where count is the number of pages
7. **Save** the result to `content_searches`.

**Dry run** applies when the SERP provider is not live (`registry.is_live` is false) or the backlink provider is a dry run.
- With a dry-run SERP, page data is made up and nothing is fetched (`DryRunPages`).
- With a dry-run backlink provider, backlinks are made up by `DryRunBacklinks.bulk_metrics`.
- The made-up values are stable for each URL.
- `dry_run` is true when any part was made up, and the page shows the preview banner.

## Storage (migration 0011)

`content_searches`:

| Column | Type |
| --- | --- |
| `id` | primary key |
| `topic` | String(80), indexed |
| `country` | String(2) |
| `language` | String(2) |
| `created_at` | DateTime(timezone=True), indexed |
| `dry_run` | Boolean |
| `result_json` | JSON (`summary`, `results` and `notes`) |

Rows are never deleted; the cache rule only skips old ones.

## API (`app/api/content_explorer.py`)

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/content-explorer` | Body `{topic, country="US", language="en", refresh=false}`. Returns the search. 422 for bad input, 429 at the SERP cap, 502 when the SERP provider fails |
| GET | `/api/content-explorer/recent` | The last 10 searches: `{items: [{id, topic, country, language, created_at, dry_run}]}` |
| GET | `/api/content-explorer/{id}` | A saved search (`cached: true`), or 404 |
| GET | `/api/content-explorer/{id}/csv` | One row per result. A dry-run search starts with the same preview line Keywords Explorer's CSV uses |

A search object has:
- `id`, `topic`, `country`, `language`, `created_at`, `cached`, `dry_run`, `notes[]`
- `summary {median_words, median_referring_domains, schema_counts, common_h2_terms}`
- `results[]`: `{position, url, domain, title, status, error, word_count, h1, outline, schema_types, images, internal_links, external_links, readability, issues, backlinks, referring_domains}`

## Page (`/content`, "Content Explorer" in the top nav)

1. **Search form:** topic, country and language.
   - A cost hint: "≈ $0.05–0.08 per new search · cached 7 days (free)", or "Dry run: no cost" when the last response was a dry run.
   - The last 10 searches as chips that reopen a search.
2. **Header line:** "Top 10 for '…' · US · fetched 2 h ago (cached)", with **Refresh** and **Export CSV** buttons, the dry-run banner and any notes.
3. **Tiles:**
   - median words
   - top schema type ("Product: 6 of 10")
   - median referring domains
4. **Charts, each with a table view:**
   - words per position (vertical bars)
   - schema types (horizontal bars)
5. **Results table:**
   - columns: #, page (title, domain, an external link with `rel="noopener noreferrer"`), words, H2s, schema chips, referring domains, backlinks, readability, issues
   - sticky first column, and horizontal scroll inside the table on phones
   - a failed page shows a muted "Couldn't fetch (…)"
   - expanding a row shows the outline, indented by level
6. **Common H2 terms:** a list with page counts.

Phone width must not scroll sideways: grid children get `min-w-0`.

## Testing

- **Backend:**
  - the bulk request shape and parsing, with mocked HTTP; the cap stops both requests
  - schema type extraction (`@graph`, lists, invalid JSON)
  - page facts from fixture HTML, plus fetch errors and HTTP 404
  - summary math (medians, schema counts, H2 terms)
  - cache hit, miss and refresh, with dry-run results never served from the cache
  - 429 and 502 with nothing saved
  - backlinks failing without losing on-page data
  - the recent list, 404, and CSV
- **Frontend:**
  - search, then the results
  - the cached label and Refresh
  - expanding a row's outline
  - the CSV link
  - a chart's table view
  - the dry-run banner and cost hint
- **Live check (dry run):** the API with curl, and the page at 1440 and 390 px with no sideways scroll.

## Out of scope

Your own page compared against the results, more than 10 results, content
scoring, and scheduled re-checks.
