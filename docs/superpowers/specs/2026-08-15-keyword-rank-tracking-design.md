# Keyword Rank Tracking & Rank-Aware Suggestions — Design

**Date:** 2026-08-15
**Status:** Approved, pending implementation plan

## Problem

The dashboard's Keyword Intelligence panel shows only a "Top Keywords" list. Users
cannot see how those keywords actually perform in search, and get no guidance when a
keyword is performing badly.

## What already exists

This is mostly a wiring and gating problem, not a greenfield build. Already implemented:

| Capability | Location | State |
| --- | --- | --- |
| Google CSE rank lookup, with cache + daily quota | `app/seo/rank_checker.py` | Complete |
| Keyword suggestions via Google Autocomplete | `app/seo/keyword_suggestions.py` | Complete |
| Competitor keyword-gap analysis | `app/seo/keyword_suggestions.py:57` | Complete |
| "Rankings" UI section | `components/keyword-panel.tsx:74` | Complete |
| "Suggested Keywords" UI section | `components/keyword-panel.tsx:92` | Complete |
| `rankings` / `suggested_keywords` types | `packages/shared/src/types/index.ts:53-70` | Complete |

Both UI sections are hidden behind `.length > 0` guards and both arrays arrive empty,
for two independent reasons:

1. **Nothing turns the features on.** `enable_rank_check` and
   `enable_keyword_suggestions` default to `False` (`schemas.py:11-12`), and the start
   form's "Advanced Overrides" panel exposes only Max Pages, Max Crawl Depth, and
   Ignore robots.txt. The audit request never sets them.
2. **No credentials.** `GOOGLE_CSE_API_KEY` / `GOOGLE_CSE_CX` are unset; no `.env`
   exists. The user is obtaining these separately.

## Requirements

1. Show each tracked keyword's Google position on the page it belongs to.
2. When a keyword performs badly, suggest replacement keywords.
3. Stay within the free CSE tier of 100 queries/day.

## Decisions

| Question | Decision |
| --- | --- |
| Quota strategy | Rank-check **only** user-nominated pages |
| Nomination shape | Explicit `{url, keywords[]}` pairs — different keywords per page |
| "Not performing well" | Keyword absent from Google's top 10 for that page |
| Credentials | User supplies; we scaffold an empty `.env` |

Rejected: checking every page until quota runs out (spend depends on crawl order, one
audit exhausts the day); a single global keyword list applied to nominated URLs (cannot
express per-page keywords).

## Design

### 1. Schema

New model in `app/schemas/schemas.py`, mirrored in `packages/shared/src/types/index.ts`:

```python
class RankTarget(BaseModel):
    url: str
    keywords: List[str] = Field(min_length=1, max_length=10)
```

Added to `AuditRequestParams`:

```python
rank_targets: Optional[List[RankTarget]] = None
```

`target_keywords` keeps its current meaning (a global override of extracted keywords)
and is untouched. The two are orthogonal: `target_keywords` decides what appears under
"Top Keywords"; `rank_targets` decides what gets rank-checked.

### 2. Targeted rank checking

In `audit_service.py`, rank checking fires only for a crawled page that matches a
`rank_targets` entry. Matching normalises both sides with the existing
`rank_checker._normalize_url()`, which already strips scheme, `www.`, query string,
fragment, and trailing slash — so `/services`, `site.com/services/`, and
`https://www.site.com/services` all resolve to the same key.

`enable_rank_check` remains the master on/off switch. With it enabled and `rank_targets`
empty, **no queries fire** and the panel reports that no pages were nominated, rather
than silently spending quota across the whole crawl.

Query cost is therefore exactly `sum(len(t.keywords) for t in rank_targets)`, knowable
before the crawl begins.

**Per-page cap reconciliation.** `check_rankings()` currently truncates to
`config.GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE` (default 3). That cap protects *automatic*
extraction, but must not silently discard keywords a user typed in deliberately.
`check_rankings()` gains an optional `max_keywords: Optional[int] = None` argument
which, when supplied, overrides the config cap. Nominated targets pass
`len(target.keywords)`, bounded to 10 by the schema. Automatic paths pass nothing and
keep today's behaviour.

### 3. Rank result status

`check_rankings()` currently signals outcome through free-text `note` strings, and
`keyword-panel.tsx:12` string-matches those against a hardcoded `SKIPPED_NOTES` array.
That coupling is fragile and already leaks: the `"error"` note is absent from the
frontend list, so a CSE request failure renders as a raw error string inside a ranking
row instead of the intended banner.

Each ranking result gains an explicit, machine-readable field:

```
status: "ranked" | "not_ranked" | "skipped"
```

- `ranked` — found in the top 10; `position` is set.
- `not_ranked` — the query ran and the page was genuinely absent from the top 10.
- `skipped` — not configured, quota reached, or request error. **Nothing was measured.**

`note` stays for human-readable display. The frontend switches to `status` and drops the
`SKIPPED_NOTES` string list.

### 4. Rank-aware suggestions

`suggest_keywords()` gains an `underperforming: List[str]` parameter. It is built from
rank results where `status == "not_ranked"` — and *only* that status.

This distinction is the crux of the feature. A `null` position occurs both when a page
genuinely does not rank and when the check never ran (missing credentials, exhausted
quota, network error). Seeding suggestions from the latter would fabricate
recommendations from an absence of data, telling a user their keyword is failing when it
was never measured. `skipped` results are therefore excluded.

When `underperforming` is non-empty, autocomplete seeds come from those keywords rather
than `seed_keywords[:3]`. Each returned suggestion gains:

```
replaces: str | None
```

naming the weak keyword it is offered against. When no rank data is present,
`underperforming` is empty and the function falls back to today's behaviour, so existing
callers and tests are unaffected.

### 5. Frontend

**Start form** (`app/page.tsx`, Advanced Overrides): a "Keyword rank tracking" block of
repeatable rows — a URL field and a comma-separated keywords field — with add/remove
controls. Above the rows, a live readout: `will use N of your 100 daily queries`, where
`N` is the sum of keyword counts. Submitting sends `rank_targets` and sets
`enable_rank_check` / `enable_keyword_suggestions` when at least one row is filled.

**Keyword panel** (`components/keyword-panel.tsx`): the Rankings section already renders
`#3` in green and a muted fallback otherwise; it switches from note-string matching to
`status`. The Suggested Keywords section renders `replaces` as an "instead of *X*" line
linking each suggestion to the keyword it answers.

A nominated URL that the crawl never reached produces no page card at all, so its absence
would be invisible. The panel therefore renders a short "not reached by this crawl" list
of any `rank_targets` URL with no matching crawled page — the common cause being a URL
beyond `max_depth` or blocked by robots.txt.

### 6. Configuration

**Nothing currently loads a `.env` file into the Python backend.** `app/config/config.py`
calls bare `os.getenv`, and the repo's only `dotenv` call lives in
`apps/backend/src/server.ts` — the retired Express server. Scaffolding `.env` alone would
therefore change nothing: credentials pasted into it would never be read, and every rank
check would still report "not configured".

So configuration is two parts:

1. Add `python-dotenv` to `requirements.txt` and load `apps/backend/.env` at the top of
   `config.py`, with `override=False` so an explicitly exported environment variable
   still wins.
2. Scaffold `apps/backend/.env` from `.env.example` with **empty** values for
   `GOOGLE_CSE_API_KEY` and `GOOGLE_CSE_CX`, for the user to fill in.

`.env` and `.env.*` are already gitignored (`!.env.example` excepted), so no secret can be
committed. No key value is ever written by tooling or read into logs.

### Error handling

| Condition | Behaviour |
| --- | --- |
| Credentials missing | `status: "skipped"`, banner shown, no suggestions seeded |
| Daily quota exhausted | `status: "skipped"`, banner shown, no suggestions seeded |
| CSE request fails | `status: "skipped"`, logged, audit continues |
| Autocomplete fails | Logged at debug, zero suggestions, audit continues |
| Nominated URL never crawled | Reported in the panel as not reached; no query spent |
| Competitor page fetch fails | Skipped silently, gap analysis continues |

No failure in this subsystem aborts an audit.

## Testing

- URL normalisation matching: scheme, `www.`, trailing slash, and query-string variants
  of a nominated URL all match the crawled page.
- Quota bounding: an audit spends exactly `sum(len(keywords))` queries; a crawl with
  `rank_targets` empty and `enable_rank_check` true spends zero.
- `max_keywords` override: a target with 5 keywords checks all 5 despite
  `GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE=3`; automatic extraction still truncates to 3.
- **Suggestion gating:** `not_ranked` seeds suggestions; `skipped` (each of the three
  causes) seeds none.
- `replaces` names the correct originating keyword.
- Backward compatibility: with no `rank_targets`, existing rank-check and suggestion
  behaviour is unchanged.
- Frontend: quota readout arithmetic; Rankings renders from `status`; `replaces` renders.

## Out of scope

- Paid CSE tiers or quota above the free 100/day.
- Historical rank tracking over time (the existing session history stores whole audits;
  a rank time-series is a separate feature).
- Page-2+ rank positions. `check_rankings()` already accepts a `deep_rank_check` flag
  reserved for this; it stays inert.
- Non-Google search engines.

## Risks

- **Google Autocomplete is undocumented** and may change shape or disappear. Already
  wrapped so failures degrade to zero suggestions rather than breaking the audit.
- **100 queries/day is genuinely tight.** Nomination makes spend deliberate and
  predictable, but a user tracking many pages will still hit the ceiling. The pre-flight
  readout is what makes the cost visible before it is spent.
- **Cache is process-memory only** (`rank_checker.py:28`), so a backend restart discards
  it and re-queries cost fresh quota. Acceptable for local development; worth revisiting
  if this is ever deployed.
