# Phase 3: Keywords Explorer + Content Gap — Design

**Date:** 2026-10-25
**Status:** Approved, pending implementation plan
**Branch:** `feat/keywords-explorer`
**Brief:** `BUILD_PROMPT.md` Phase 3 (the SERP interface was already built in Phase 2)

## Problem

Keyword ideas exist only inside an audit, per page, as Google Autocomplete
suggestions. There is no search volume, no difficulty, no way to explore a seed
keyword on its own, and no domain-level content gap. The existing "competitor
gap" fetches competitor pages and diffs their on-page keywords, which says
nothing about what those competitors rank for.

## Decisions taken

- **Content Gap uses DataForSEO Labs only**, for real domain-level data. When
  no live provider is configured it returns a labelled dry-run preview (no free
  fallback).
- **Keyword metrics come from DataForSEO** (Google Ads search volume, Labs
  keyword difficulty). Traffic potential is our own **estimate**, labelled as such.
- Results are computed on request and **not stored as history** in this phase.
  Provider responses are cached.

## DataForSEO endpoints (verified 2026-10-25, docs.dataforseo.com)

| Use | Endpoint (POST, basic auth, JSON array of one task) | Request | Response fields used |
| --- | --- | --- | --- |
| Search volume | `/v3/keywords_data/google_ads/search_volume/live` | `keywords` (≤1000, ≤80 chars each; one charged request), `location_name`, `language_code` | `result[]` items: `keyword`, `search_volume`, `cpc`, `competition`, `competition_index` |
| Difficulty | `/v3/dataforseo_labs/google/bulk_keyword_difficulty/live` | `keywords` (≤1000), `location_name`, `language_code` | `result[0].items[]`: `keyword`, `keyword_difficulty` (0–100, logarithmic) |
| Ranked keywords | `/v3/dataforseo_labs/google/ranked_keywords/live` | `target` (bare domain), `location_name`, `language_code`, `limit` (default 100, max 1000), `item_types: ["organic"]` | `result[0].items[]`: `keyword_data.keyword`, `keyword_data.keyword_info.search_volume`, `keyword_data.keyword_properties.keyword_difficulty`, `ranked_serp_element.serp_item.rank_group`, `ranked_serp_element.serp_item.url` |
| People Also Ask | the existing SERP call (`/v3/serp/google/organic/live/advanced`) | — | items of `type == "people_also_ask"` in the same `items[]` as organic results. **The question field is not confirmed by the docs:** the parser reads each nested element's `title` and ignores anything else. It's confirmed on the first live call; if absent, ideas come from Autocomplete only. |

Success is `status_code == 20000` at response and task level (Phase 2's rule).
The Google Ads endpoint allows 12 requests/minute per account. The explorer
makes at most one such request per explore.

## Design

### 1. Keyword data provider — `app/providers/keywords.py`

```python
@dataclass(frozen=True)
class KeywordMetrics:
    keyword: str
    search_volume: Optional[int]
    cpc: Optional[float]
    competition: Optional[str]      # LOW / MEDIUM / HIGH, as the provider reports
    difficulty: Optional[int]       # 0-100

@dataclass(frozen=True)
class RankedKeyword:
    keyword: str
    position: int
    url: str
    search_volume: Optional[int]
    difficulty: Optional[int]

class KeywordDataProvider(Protocol):
    name: str
    def metrics(self, keywords: List[str], country: str, language: str) -> Dict[str, KeywordMetrics]: ...
    def difficulty(self, keywords: List[str], country: str, language: str) -> Dict[str, int]: ...
    def ranked_keywords(self, domain: str, country: str, language: str, limit: int) -> List[RankedKeyword]: ...
```

- `DataForSeoKeywordProvider` (`app/providers/dataforseo_keywords.py`): the three
  endpoints above. It shares the HTTP and error handling with the SERP adapter
  through a small `_post_task(endpoint, task)` helper moved into
  `dataforseo.py`, and the country→`location_name` table. Keywords are
  lowercased and trimmed, and those over 80 chars are dropped (and reported)
  before the call.
- `DryRunKeywordProvider`: deterministic made-up metrics and ranked keywords,
  each result carrying `dry_run=True`.
- `registry.get_keyword_provider(cfg)`: DataForSEO only when `SERP_PROVIDER ==
  "dataforseo"`, `SERP_DRY_RUN` is false and credentials are set. Otherwise
  dry run. Its budget is provider name **`dataforseo_labs`**, capped by
  **`DATAFORSEO_LABS_DAILY_CAP`** (default 20). One unit is reserved per HTTP
  request actually made (a 500-keyword volume lookup is one unit), and none on
  a cache hit. See §2 for why the adapter reserves the budget itself instead of
  being wrapped in `SpendGuard`.
- The **SERP adapter gains People Also Ask**: `SerpResult.questions:
  List[str]`, filled from `people_also_ask` items. Google CSE and dry run
  return `[]`.

### 2. Provider cache — `app/providers/cache.py`, migration `0003`

Table `provider_cache` (id, provider, endpoint, request_hash, response_json,
fetched_at; unique (provider, endpoint, request_hash)).
`cached_call(provider, endpoint, request: dict, ttl: timedelta, fetch:
Callable[[], Any]) -> Any`:
- `request_hash` = sha256 of the canonical JSON of the request.
- A fresh row → returned without calling `fetch` (no spend).
- Otherwise `fetch()`, store, and return.
- **Never used for dry-run providers**: callers skip the cache when
  `provider.name` starts with `dry_run`.

TTLs: metrics and difficulty **30 days**, ranked keywords **7 days**.

**Order per call: cache, then budget, then HTTP.** A cache hit must cost
nothing, so the budget can't be a wrapper around the whole adapter (as
`SpendGuard` is for SERP). Instead, `DataForSeoKeywordProvider` takes its cap,
and inside each method calls `cached_call(...)`, whose `fetch` does
`spend.reserve("dataforseo_labs", cap)` and then the HTTP request. A hit
therefore makes no request and reserves nothing.

### 3. Keywords Explorer — `app/keywords/explorer.py`

`explore(seed, country="US", language="en", cluster=False, serp=None, data=None) -> ExploreResult`:

1. **Ideas:** `_autocomplete_suggestions(seed)` (existing, free), plus
   `serp.search(seed).questions` (People Also Ask, from one SERP call) when a
   live SERP provider exists. Normalised (lowercase, whitespace-collapsed),
   de-duplicated, the seed excluded, capped at **50**.
2. **Metrics:** one `data.metrics([seed] + ideas)` call and one
   `data.difficulty(...)` call. Missing values stay `None`.
3. **Traffic potential (estimate):** `round(search_volume × CTR_TOP1)`, with
   `CTR_TOP1 = 0.28`, a documented constant. The field is named
   `traffic_potential_estimate`.
4. **Clustering** (only when `cluster=True`): the seed plus the top ideas by
   volume, **max 20**. One SERP call each (behind the SERP cap). Keywords whose
   top-10 URLs share **≥ 3** URLs are joined, transitively (union-find).
   Returns `clusters: [[keyword, …], …]`, each led by its highest-volume
   keyword. A SERP call that's skipped leaves that keyword unclustered.
5. `ExploreResult`: `seed`, `country`, `language`, `dry_run` (true if either
   provider was dry run), `keywords: [{keyword, source (seed / autocomplete /
   people_also_ask), search_volume, cpc, competition, difficulty,
   traffic_potential_estimate}]` sorted by volume (None last), and `clusters`.

### 4. Content Gap — `app/keywords/gap.py`

`content_gap(my_domain, competitors, country, language, limit=500, data=None) -> GapResult`:

1. `data.ranked_keywords(domain, …, limit)` for my domain and each competitor
   (1–5 competitors, so at most 6 calls; each is cached for 7 days).
2. A keyword is a **gap** when at least one competitor ranks it at position
   **≤ 20** and my domain does not rank it at position **≤ 100**.
3. **Opportunity** = `search_volume × (100 − difficulty) / 100`, where an
   unknown difficulty is treated as 50 and an unknown volume as 0. Sorted
   descending.
4. Row: `keyword, search_volume, difficulty, opportunity, competitors: {domain:
   {position, url}}, best_competitor_position`.
5. `GapResult`: `my_domain`, `competitors`, `dry_run`, `rows`, `total_gaps`.

### 5. API — `app/api/keywords.py`

- `POST /api/keywords/explore` `{seed, country?, language?, cluster?}` →
  `ExploreResult` JSON.
- `GET /api/keywords/explore.csv?seed=&country=&language=` → `text/csv`.
- `POST /api/projects/{id}/content-gap` `{competitors?, country?, language?,
  limit?}`. `competitors` defaults to the project's competitor list. 400 if
  there are none, or more than 5.
- `GET /api/projects/{id}/content-gap.csv?…` → `text/csv` (competitors as
  repeated `competitor=` params, defaulting the same way).
- Every response carries `dry_run`. Preview data is labelled in the CSV too,
  with a first line `# DRY RUN — made-up data`.
- `ProviderSkipped` (cap reached) → **429** with the reason. The central DB
  being unavailable → 503.

### 6. Config, docs

`DATAFORSEO_LABS_DAILY_CAP` (default `20`) in `config.py`, `.env.example`,
compose and `docs/env.md`. `docs/api.md` and the README gain the explorer and
gap endpoints, the estimate's meaning, and "How to verify".

## Error handling

- Autocomplete failure → no autocomplete ideas (existing behaviour).
- People Also Ask parse finding nothing → no questions. Never an error.
- A provider error on metrics/difficulty → those fields are `None` and the
  explore still returns, with `note` naming the failure. A provider error in
  the gap → 502 with the provider's status message, never credentials.
- Cap reached → 429.

## Testing (no network)

- Each DataForSEO keyword endpoint: request body and parsing against fixtures
  in the documented shapes; error status → `ProviderError`; keywords over 80
  chars are dropped.
- People Also Ask: questions read from a fixture `people_also_ask` item;
  absent → `[]`.
- Cache:
  - a hit makes no HTTP call and reserves no budget
  - an expired entry refetches
  - dry run is never cached
  - the same request in a different key order hits the same row
- Spend: `dataforseo_labs` is capped separately from `dataforseo`.
- Explorer: ideas merged and de-duplicated, the seed excluded, the 50 cap;
  traffic estimate; volume sort with None last.
- Clustering:
  - overlap ≥ 3 joins keywords, including transitively
  - more than 20 keywords are truncated
  - a skipped SERP leaves its keyword unclustered
- Gap:
  - the ≤ 20 / ≤ 100 rules
  - opportunity ordering and the defaults for unknown values
  - at most 6 provider calls
- API: dry-run labelling, CSV header line, 400/429, default competitors.

## Done when

The explorer returns ideas with volume, difficulty and the traffic estimate
(plus optional clusters), and the content gap ranks competitor keywords by
opportunity and exports CSV. Verified end to end in dry run through the API,
with no paid call without the owner's explicit OK.

## Out of scope

- Dashboard pages (Phase 4).
- Saving explorer or gap runs as history.
- A free (non-Labs) gap fallback (declined).
