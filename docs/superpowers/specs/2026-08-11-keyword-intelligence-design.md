# Keyword Intelligence — Design Spec

Date: 2026-08-11
Status: Approved, ready for implementation planning

## 1. Goal

Add a Keyword Intelligence feature to the SEO auditor that, for every page in a crawl (not a single manually-pasted URL), answers three questions using only free/official data sources:

1. **What keywords is this page targeting?** — extracted from the page's own on-page signals.
2. **Where does it rank on Google for those keywords?** — checked live via Google's official Programmable Search Engine / Custom Search JSON API (100 free queries/day).
3. **What better keywords should it target?** — suggested via Google Autocomplete (free, unofficial) plus a keyword-gap comparison against pages currently outranking it.

No paid SEO SaaS (Ahrefs/Semrush/Moz), no scraping Google search results pages, no heavyweight NLP dependencies.

## 2. Non-goals (explicit)

- **No historical rank tracking over time.** Current rank at audit time only. Tracking changes week-over-week needs a scheduler + time-series storage — separate, larger effort.
- **No search volume, CPC, or difficulty scores.** Not available without a paid provider; not faked with invented numbers. Suggestions are relevance-based (on-page + competitor-gap + autocomplete), not volume-ranked.
- **No backlink data.**
- **Google Autocomplete is unofficial** — every call is wrapped so failure never breaks the audit.

## 3. Repo duplication decision

This repo has two near-identical copies of the Python audit engine: `apps/backend/app/` (live, wired to FastAPI routes) and `apps/backend/seo_auditor/seo_auditor/` (older, independently pip-installable CLI package). They already duplicate `checks.py`, `crawler.py`, `analysis.py`, and `ai_suggestions.py` — differing by import lines only.

**Decision: implement the 3 new keyword modules identically in both trees**, matching this existing precedent, rather than building a new shared pip-installable package. Rationale (confirmed with user):

- A genuine shared-module extraction would require a new installable package with its own `setup.py`, wired as a dependency into both trees' install flows — packaging/build-tooling work orthogonal to this feature, with real risk of breaking the existing install/deploy path.
- It would only deduplicate the *new* files, leaving the pre-existing duplication of `checks.py`/`crawler.py`/etc. untouched — an inconsistent half-fix.
- Full deduplication of the whole engine is a legitimate but separate refactor, out of scope here.

Both copies must be kept behaviorally identical. Every step below that touches `apps/backend/app/...` has a mirrored step touching `apps/backend/seo_auditor/seo_auditor/...`.

## 4. New backend modules

Created twice, once per tree: `apps/backend/app/seo/` and `apps/backend/seo_auditor/seo_auditor/seo/`. Each module is pure logic + one narrow I/O boundary, independently unit-testable with fakes.

### 4.1 `keyword_extraction.py`

```
extract_keywords(page_meta: dict, content_stats: dict, top_n: int = 8) -> list[dict]
```

- Zero external calls, zero new dependencies.
- Builds weighted 1–3 word n-gram frequency across: `title` (×3), `h1` (×2.5), `meta_description` (×2), H2/H3 text from `heading_hierarchy` (×1.5), body text from `content_stats["text"]` (×1).
- Filters stop words using the **existing `STOP_WORDS`** set in `checks.py` (imported, not redefined).
- Supersedes the dead `keyword_density()` function in `checks.py` (confirmed zero callers repo-wide) — its word-frequency logic is folded into this module rather than left as a second, competing keyword function. `keyword_density()` itself is left in place (removing it is out of scope / a separate cleanup) but is no longer the thing this feature uses.
- Returns `[{"phrase": str, "score": float, "found_in": ["title", "h1", ...]}]`, sorted descending, capped at `top_n`.

### 4.2 `rank_checker.py`

```
check_rankings(page_url: str, keywords: list[str], config) -> list[dict]
```

- For each keyword (capped at `config.GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE`, default 3): `GET https://www.googleapis.com/customsearch/v1` with `key`, `cx`, `q=<keyword>`, `num=10`. First page of results only — no automatic pagination (that would be a second quota-consuming query per keyword); a `deep_rank_check` flag is accepted for future use but is off by default and out of scope to implement paging behind it now beyond accepting the flag.
- Matches `items[].link` against `page_url` after normalizing both (strip scheme, trailing slash, leading `www.`, query string) to find position 1–10.
- **Cache**: an in-memory module-level singleton (mirroring `session_model.py`'s `SessionStore` — no DB, no persistence beyond process lifetime, matching this codebase's existing pattern), keyed by `(keyword, target_domain)`, TTL from `config.GOOGLE_CSE_CACHE_TTL_HOURS` (default 24h). A cache hit returns the stored result without a network call.
- **Quota**: a daily counter on the same singleton, resets at UTC midnight, capped at `config.GOOGLE_CSE_DAILY_QUOTA` (default 100). Once exhausted, remaining keywords get `{"position": None, "note": "ranking check skipped — daily Google CSE quota reached"}` instead of a network call or exception.
- **Not configured**: if `GOOGLE_CSE_API_KEY` or `GOOGLE_CSE_CX` is missing, short-circuits immediately (before touching cache/quota) and returns `{"position": None, "note": "ranking check unavailable — Google CSE not configured"}` for every keyword. The rest of the audit is unaffected.
- Returns `[{"keyword": str, "position": int | None, "note": str | None, "checked_at": iso_timestamp, "top_urls": list[str]}]`. `top_urls` holds the (up to 10) result links from that keyword's CSE response — present whenever a live or cached CSE call actually happened, an empty list when skipped (quota/not-configured/error). This is what lets `keyword_suggestions.py`'s competitor-gap pass reuse an already-paid-for query instead of issuing its own (see §4.3).
- Any request exception is caught per-keyword; a failure never propagates and never fails the audit.
- Internally, the single function that actually performs a cache-or-live CSE lookup for one keyword (`_get_cse_results(keyword, target_domain, config) -> list[str] | None`, returning `None` on skip/failure) is exposed at module level so `keyword_suggestions.py` can call it directly for the case described in §4.3 — this keeps the cache/quota bookkeeping in exactly one place.

### 4.3 `keyword_suggestions.py`

```
suggest_keywords(
    seed_keywords: list[dict],
    page_meta: dict,
    rank_results: list[dict],
    config,
    fetch_page: Callable[[str], PageResultLike],
    enable_competitor_gap: bool = False,
) -> list[dict]
```

`config` here is the env-var settings module (CSE key/cx/quota/cache — needed by the competitor-gap path to call `rank_checker._get_cse_results()`). `enable_competitor_gap` is the *request-level* flag from `AuditRequestParams`, passed explicitly rather than folded into `config`, since it varies per audit while `config` is process-wide.

`fetch_page` is `Crawler._fetch` bound to the crawler instance already running this audit, passed in rather than imported — this is what lets one implementation work against either tree's (structurally near-identical but distinct) `Crawler` class, and satisfies "don't write a second HTTP client."

- **Source 1 — Autocomplete** (free, no key): `GET https://suggestqueries.google.com/complete/search?client=firefox&q=<seed>` for each seed keyword. Wrapped in try/except with a short timeout; failure is silently skipped (logged at debug, not error — this endpoint is expected to occasionally fail/change and that is normal, not exceptional). Code comment notes it's unofficial and may change/disappear without notice.
- **Source 2 — competitor gap** (opt-in via `enable_competitor_gap`, default off): needs the top-ranking URLs for the page's top seed keyword.
  - If `rank_results` already has a non-empty `top_urls` for that keyword (i.e. `rank_checker.check_rankings` already paid for that CSE call this audit), reuse it directly — no extra query.
  - Otherwise (e.g. `enable_rank_check` is off but `enable_competitor_gap` is on), call `rank_checker._get_cse_results()` directly for just that one keyword — same cache/quota-checked path, so it's still capped by the daily quota and still returns gracefully (`None`) when unavailable, in which case this source contributes nothing rather than erroring.
  - From whichever `top_urls` list resulted, take the top 2–3 that are not the audited domain, fetch each via `fetch_page(url)`, run `extract_keywords()` on each, and diff against the current page's keyword set. Surfaces phrases appearing in ≥2 competitors but absent or low-scoring on the current page.
- Combines both sources into `[{"phrase": str, "reason": "related search" | "used by top-ranking competitors but missing on this page", "competitor_examples": [url, ...] | None}]`, deduplicated by phrase, capped at 10.

## 5. Wiring into both audit pipelines

In `apps/backend/app/services/audit_service.py::_build_audit_result()` (and mirrored in `apps/backend/seo_auditor/seo_auditor/cli.py::collect_audit_data()`):

Deviation from the originally-sketched call site: `extract_keywords()` needs `heading_hierarchy`, which isn't computed until after the `if soup:` block — later than `content_issues, content_stats = checks.check_content(page)`. So the keyword pipeline is invoked immediately after `page_meta[page_url] = {...}` is fully assembled for that page (same per-page loop iteration, just the natural point where all needed data exists), not literally on the line right after `check_content()`.

```python
keyword_data = (
    [{"phrase": k, "score": None, "found_in": []} for k in params.target_keywords]
    if params.target_keywords else
    keyword_extraction.extract_keywords(page_meta[page_url], content_stats)
)
rank_data = (
    rank_checker.check_rankings(page_url, [k["phrase"] for k in keyword_data], config)
    if params.enable_rank_check else []
)
suggestions = (
    keyword_suggestions.suggest_keywords(
        keyword_data, page_meta[page_url], rank_data, config,
        fetch_page=crawler._fetch,
        enable_competitor_gap=params.enable_competitor_gap,
    )
    if params.enable_keyword_analysis else []
)
page_meta[page_url]["keyword_analysis"] = {
    "top_keywords": keyword_data,
    "rankings": rank_data,
    "suggested_keywords": suggestions,
}
```

(`rank_checker.check_rankings` already caps to `GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE` internally, so the call site doesn't need to slice `keyword_data` itself.)

`report.py::build_page_level_report()` gets one added field on each row: `"keyword_analysis": meta.get("keyword_analysis")` — same pattern as every other `meta.get(...)` field already there.

## 6. Schema / config changes

`apps/backend/app/schemas/schemas.py` — `AuditRequestParams` gains:

```python
enable_keyword_analysis: Optional[bool] = True
enable_rank_check: Optional[bool] = False
enable_competitor_gap: Optional[bool] = False
target_keywords: Optional[List[str]] = None
```

`enable_keyword_analysis` on by default (pure on-page extraction, no external calls, no quota cost). `enable_rank_check` and `enable_competitor_gap` off by default (cost Google CSE quota and/or extra latency/page fetches). `target_keywords`, when provided, overrides auto-extraction for that audit — `extract_keywords()` is skipped and the provided list is used as the seed for ranking/suggestions instead.

`apps/backend/app/config/config.py` gains, read the same way as existing vars (`os.getenv`, no new config framework):

```python
GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_CX = os.getenv("GOOGLE_CSE_CX", "")
GOOGLE_CSE_DAILY_QUOTA = int(os.getenv("GOOGLE_CSE_DAILY_QUOTA", "100"))
GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE = int(os.getenv("GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE", "3"))
GOOGLE_CSE_CACHE_TTL_HOURS = int(os.getenv("GOOGLE_CSE_CACHE_TTL_HOURS", "24"))
```

`.env.example` gets the same 5 keys, blank/default values, mirroring existing entries' style.

## 7. API surface

No new endpoint. `keyword_analysis` rides on the existing `PageItem` shape through the existing `/api/audit` → `/api/audit/latest` → `/api/pages` flow, same as every other per-page field. A dedicated `/api/keywords?session_id=...` endpoint was considered and rejected as YAGNI — it would be a second path to the same data already present in `/api/pages`.

## 8. Frontend

`packages/shared/src/types/index.ts` adds:

```typescript
export interface KeywordRanking {
  keyword: string;
  position: number | null;
  note?: string;
  checked_at?: string;
}
export interface SuggestedKeyword {
  phrase: string;
  reason: string;
  competitor_examples?: string[];
}
export interface KeywordAnalysis {
  top_keywords: { phrase: string; score: number; found_in: string[] }[];
  rankings: KeywordRanking[];
  suggested_keywords: SuggestedKeyword[];
}
```

...and `PageItem` gains `keyword_analysis?: KeywordAnalysis;`.

New `apps/frontend/components/keyword-panel.tsx`, structurally cloned from `technical-seo-panel.tsx` ("use client", `Card`/`CardHeader`/`CardContent`/`CardTitle`, a lucide icon, `pages: PageItem[]` prop). Per page: extracted keywords with their `found_in` locations, current rank or the appropriate note (not ranking in top 10 / quota reached / not configured), and suggested keywords with reason + competitor example URLs. A site-wide banner appears when rank-checking was skipped entirely (quota exhausted or not configured), so blank ranks read as "not checked" rather than "found nothing."

Registered in `apps/frontend/app/dashboard/page.tsx`: one entry in the widget-order array (`{ id: "keywords", width: "full", visible: true }`, placed after `"tech-seo"`) and one entry in the `widgetComponents` map, matching the `tech-seo` registration exactly.

## 9. Testing

Backend, added to `apps/backend/tests/` (existing style: plain unit tests, fakes/mocks, no live network):

- `test_keyword_extraction.py` — fixed `page_meta`/`content_stats` fixtures in, deterministic top-phrase list out; asserts weighting (title-only phrase outranks body-only phrase) and stop-word filtering.
- `test_rank_checker.py` — mocks `requests.get` to the CSE endpoint with canned JSON. Asserts: position parsing across the 10 results, URL-normalization matching (scheme/www/trailing-slash/query-string differences still match), a cache hit avoids a second `requests.get` call, quota exhaustion produces the "skipped" note instead of raising, and missing key/cx disables the feature cleanly with zero `requests.get` calls.
- `test_keyword_suggestions.py` — mocks the Autocomplete endpoint and the competitor CSE/fetch path; asserts graceful skip (empty list, no raise) when Autocomplete errors or times out, and correct gap-detection when competitor pages are supplied via a fake fetch function.

Only `apps/backend/app/seo/` gets committed tests; per §3, `apps/backend/seo_auditor/seo_auditor/seo/` is a byte-for-byte-equivalent copy and is not given a second parallel test suite — this matches how the existing duplicated modules (`checks.py` etc.) have exactly one tested copy today.

Frontend: `apps/frontend/components/__tests__/keyword-panel.test.tsx`, following `live-crawl-panel.test.tsx`'s pattern (mock `@/lib/audit-context` or pass `pages` directly as a prop per the component's actual signature, React Testing Library render + assertions).

Full suites (`pytest tests/ -q`, `npx vitest run`) must pass before and after, confirming no regression in the 7 backend / 6 frontend tests that exist today.

## 10. Docs

- `docs/api.md` — new `AuditRequestParams` fields, new `keyword_analysis` field on `PageItem` responses.
- `docs/env.md` — the 5 new env vars, plus a short walkthrough of getting a free `GOOGLE_CSE_API_KEY` + `GOOGLE_CSE_CX` from Google's Programmable Search Engine console.
- `docs/architecture.md` — add `RankChecker` / `KeywordSuggestions` boxes to the existing mermaid diagram, with the outbound call to Google CSE shown as an external dependency (matching how other external calls, if any, are already depicted).

## 11. Constraints carried through implementation

- No new heavyweight dependencies (no spaCy/NLTK/Selenium/Playwright). `requests` (already used throughout `crawler.py`) is the HTTP client for both the CSE call and the Autocomplete call.
- `enable_rank_check` and `enable_competitor_gap` default off; `enable_keyword_analysis` defaults on.
- An audit with no `GOOGLE_CSE_API_KEY`/`GOOGLE_CSE_CX` configured produces the same successful result as today, just with the "not configured" note per keyword — never an error, never a crash, never a silently-skipped whole audit.
- Style: plain dicts (no ORM/dataclass models introduced), logging via `logger.error(..., exc_info=exc)` matching `routes.py`'s existing pattern, tests as fakes/mocks matching existing `tests/` style.

## 12. Deliverable checklist

- [ ] `apps/backend/app/seo/{keyword_extraction,rank_checker,keyword_suggestions}.py`
- [ ] `apps/backend/seo_auditor/seo_auditor/seo/{keyword_extraction,rank_checker,keyword_suggestions}.py` (identical, mirrored)
- [ ] `audit_service.py::_build_audit_result()` wiring
- [ ] `cli.py::collect_audit_data()` wiring (mirrored)
- [ ] `report.py::build_page_level_report()` — add `keyword_analysis` field
- [ ] `schemas.py` — 4 new `AuditRequestParams` fields
- [ ] `config.py` + `.env.example` — 5 new env vars
- [ ] `packages/shared/src/types/index.ts` — `KeywordRanking`, `SuggestedKeyword`, `KeywordAnalysis`, `PageItem.keyword_analysis`
- [ ] `apps/frontend/components/keyword-panel.tsx`
- [ ] `apps/frontend/app/dashboard/page.tsx` — panel registration
- [ ] `apps/backend/tests/test_keyword_extraction.py`, `test_rank_checker.py`, `test_keyword_suggestions.py`
- [ ] `apps/frontend/components/__tests__/keyword-panel.test.tsx`
- [ ] `docs/api.md`, `docs/env.md`, `docs/architecture.md`
- [ ] `pytest tests/ -q` and `npx vitest run` both green, before/after comparison confirming no regression
