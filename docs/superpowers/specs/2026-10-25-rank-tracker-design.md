# Phase 2: Provider layer + Rank Tracker — Design

**Date:** 2026-10-25
**Status:** Approved, pending implementation plan
**Branch:** `feat/rank-tracker`
**Brief:** `BUILD_PROMPT.md` Phase 2 (with the SERP part of Phase 3's provider layer moved here, per `docs/GAP_REPORT.md` §4)

## Problem

Rank checking today answers "does this exact page appear in Google CSE's top
10" during an audit, through a hard-wired Google CSE client with an in-memory
quota that resets on restart. Nothing tracks a keyword over time, across
countries or devices, against competitors, or alerts on a drop. Google CSE is
also being wound down for new customers, so the data source must be swappable.

## Decisions taken

- A **standalone rank tracker**: projects own keyword lists, checked daily,
  independently of site crawls. The in-audit rank check goes through the same
  provider layer.
- Alerts go to **Slack (incoming webhook) and email (SMTP)**. Each is optional.
- **Google Search Console is deferred to Phase 5**, where the brief lists it
  again. It needs OAuth and site verification of its own.

## Design

### 1. Provider layer — `app/providers/`

`serp.py`:

```python
@dataclass(frozen=True)
class SerpQuery:
    keyword: str
    country: str = "US"        # ISO 3166-1 alpha-2
    language: str = "en"       # ISO 639-1
    device: str = "desktop"    # desktop | mobile
    depth: int = 100           # results requested

@dataclass(frozen=True)
class SerpItem:
    position: int              # organic rank, 1-based
    url: str
    domain: str
    title: str = ""

@dataclass
class SerpResult:
    items: List[SerpItem]
    provider: str
    note: Optional[str] = None   # e.g. "device not supported by google_cse"

class SerpProvider(Protocol):
    name: str
    def search(self, query: SerpQuery) -> SerpResult: ...

class ProviderSkipped(Exception):
    """The call was not made: not configured, or the spend cap was reached.
    Carries a user-facing reason."""
```

Adapters:

- **`DataForSeoProvider`** (`dataforseo.py`): `POST
  https://api.dataforseo.com/v3/serp/google/organic/live/advanced` with HTTP
  basic auth (`DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD`). One task per query:
  `keyword`, `location_name` (mapped from the ISO country by a fixed table in
  the adapter; an unmapped country raises `ValueError`), `language_code`,
  `device`, `depth`. It parses `tasks[0].result[0].items` of `type ==
  "organic"`, using `rank_group` as the position. A non-20000 `status_code` at
  the response or task level raises `ProviderError` with the provider's
  message. **The request and response shape is verified against DataForSEO's
  documentation during implementation, and the parser is tested against a
  recorded fixture of that documented response.**
- **`GoogleCseProvider`** (`google_cse.py`): today's CSE call, moved here.
  Returns at most 10 items (depth > 10 is clamped, with a `note`). Device is
  ignored, with a `note`. Country maps to CSE's `gl` parameter.
- **`DryRunProvider`** (`dry_run.py`): no network. Returns deterministic
  synthetic items derived from a hash of the query, plus `note = "dry run"`.
  A test can inject a fixed result set.

`registry.py`: `get_serp_provider()` reads `SERP_PROVIDER` (`dataforseo` /
`google_cse` / `dry_run`, default `google_cse` if CSE is configured, otherwise
`dry_run`) and wraps the provider in the **spend guard**. If `SERP_PROVIDER=dataforseo` and
`SERP_DRY_RUN` is not exactly `false`, the registry returns the dry-run
provider and logs that it did so. **The first live DataForSEO call requires
the owner to set `SERP_DRY_RUN=false` explicitly.**

`spend.py`, the **spend guard**: wraps any non-dry-run provider. Before each
call it atomically reserves one unit in `provider_usage(provider, day)` with an
`UPDATE … SET calls = calls + 1 WHERE calls < cap` (inserting the day's row
first). It raises `ProviderSkipped("daily cap of N reached")` when no row
updated. Caps come from `SERP_DAILY_CAP` (default **50**). A reserved unit is
not refunded on a provider error (the call may have been billed).

### 2. Data — migration `0002_rank_tracker`

- `keywords`: add `language` (default `en`), `enabled` (default true) and
  `created_at`. Identity stays (project, phrase, country, device). Keywords
  created by audits (Phase 1) keep country/device NULL. The tracker treats
  NULL as `US`/`desktop`.
- `rank_checks`: add `serp_json` (list of `{position, url, domain}` for the
  top results, capped at 100) and `competitor_positions_json`
  (`{domain: position|null}`).
- `projects`: add `rank_schedule` (null / `daily`, default null),
  `last_rank_checked_at`, `alert_settings_json`.
- New `provider_usage` (id, provider, day DATE, calls INT; unique (provider, day)).
- New `alerts` (id, project_id, keyword_id, rank_check_id, kind, channel,
  sent_at, payload_json; unique (rank_check_id, kind, channel)).

Adding the first keyword to a project with `rank_schedule = null` sets it to
`daily`.

### 3. Tracking — `app/rank/tracker.py`

`check_keyword(session, provider, keyword, project, competitors) -> RankCheck`:

1. `provider.search(SerpQuery(keyword.phrase, country or "US", language,
   device or "desktop", depth=RANK_DEPTH))`. `RANK_DEPTH` defaults to 100.
2. **My position:** the first item whose domain is the project domain or a
   subdomain of it (`domain == d or domain.endswith("." + d)`), giving
   `ranking_url`. Status is `ranked`, or `not_ranked` if absent.
3. **Competitor positions:** the same matching per competitor domain, from the
   same items.
4. On `ProviderSkipped` or a provider error: a row with status `skipped` and
   the reason in `note`. No position.
5. Store the row with `provider` set to the provider's name and `audit_id`
   NULL.

`run_project(project_id, now, provider=None) -> RunReport`: checks every
enabled keyword, then evaluates alerts (section 4) against each keyword's
previous non-skipped check, and sends at most one digest per channel.

### 4. Alerts — `app/alerts/`

`rules.py`: `evaluate(previous, current, settings) -> List[Change]`, a pure
function. Defaults, overridable in `alert_settings_json`:

| Kind | Fires when | Setting |
| --- | --- | --- |
| `drop` | position worsened by ≥ N | `drop_threshold` (3) |
| `left_top10` | was ≤ 10, now > 10 or not ranked | `top10_alerts` (true) |
| `lost` | was ranked, now not ranked | always on |
| `gain` | position improved by ≥ N | `gain_threshold` (null = off) |

A `skipped` check never produces or clears an alert. The comparison skips
over it to the last real result.

`notifiers.py`:
- `SlackNotifier(webhook_url)`: POSTs `{"text": …}` with a 10s timeout.
- `EmailNotifier(host, port, user, password, sender, recipients)`: `smtplib`
  with STARTTLS, a plain-text digest.

Both are built from config only when their settings are present.

`digest.py`: formats one message per project run, listing each change as
keyword, country/device, old → new position and ranking URL.

Delivery: an `alerts` row is inserted per (rank_check, kind, channel) **before**
sending. The unique constraint makes a re-run unable to send the same alert
twice. A send failure is logged and the row is kept with `payload_json.error`.
It never raises into the tracker.

### 5. Scheduling

**Dry-run results are never stored as history.** When the registry yields
the dry-run provider, `run_due_rank_checks` logs a warning and checks nothing.

`jobs.run_due_rank_checks(now, runner=None)`: projects with `rank_schedule =
"daily"`, at least one enabled keyword, and `last_rank_checked_at` null or
≥ 24 h old. Claimed with the same conditional `UPDATE` as audits, then
`tracker.run_project`. APScheduler adds it as a second 15-minute job.
`/api/cron/run` runs both jobs in its background task.

### 6. API — `app/api/rank.py`

- `POST /api/projects/{id}/keywords` `{"keywords": [{"phrase", "country"?,
  "language"?, "device"?}]}`: bulk add, skipping existing identities.
  Returns `{created, skipped}`.
- `GET /api/projects/{id}/keywords`: each keyword with its latest check
  (position, ranking_url, checked_at, status) and the change versus the
  previous check.
- `PATCH /api/keywords/{id}` (`enabled`), `DELETE /api/keywords/{id}`.
- `GET /api/keywords/{id}/history?days=90`: checks oldest-first, with
  position, ranking_url, status, competitor_positions.
- `GET/POST /api/projects/{id}/competitors`, `DELETE
  /api/projects/{id}/competitors/{competitor_id}`.
- `POST /api/projects/{id}/rank-checks/run?dry_run=true`: `dry_run` defaults
  to **true** and returns a **preview** synchronously, built from the dry-run
  provider. It is **never persisted and never alerts**. `dry_run=false` runs the
  project in a background task with the configured live provider (behind the
  spend guard). It returns 409 when no live provider is configured.
- Alert settings and `rank_schedule` are set through the existing `PATCH
  /api/projects/{id}`.

### 7. In-audit rank checks

`rank_checker.check_rankings` keeps its signature and result shape, and
`_get_cse_results` keeps its `(urls, skip_reason)` contract. That's what the
existing rank, quota and keyword-suggestion tests exercise.

- The raw CSE request moves into `rank_checker.fetch_cse_urls(keyword, config,
  gl=None, num=10)`. **`GoogleCseProvider` calls it**, so there is exactly one
  CSE implementation, and existing tests keep patching
  `app.seo.rank_checker.requests.get`.
- The in-memory daily quota is replaced by the **database spend guard** under
  provider `google_cse`, with cap `GOOGLE_CSE_DAILY_QUOTA`. It now survives
  restarts, and audits and the tracker share one budget per key. The in-memory
  cache stays as a per-process de-duplicator.
- With `SERP_PROVIDER=dataforseo` and a live (non-dry-run) provider, audits use
  DataForSEO at depth 10.
- **Audits never use the dry-run provider.** Fake positions in a real audit
  report would be misleading. Without a live provider the check is skipped as
  "not configured", as today.

### 8. Config, docs

New settings in `config.py` and `.env.example` (placeholders only):
`SERP_PROVIDER`, `SERP_DRY_RUN` (default `true`), `SERP_DAILY_CAP` (default
`50`), `RANK_DEPTH` (default `100`), `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD`,
`SLACK_WEBHOOK_URL`, `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`,
`SMTP_PASSWORD`, `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO` (comma-separated).

`docs/env.md`, `docs/api.md`, `README.md` gain the rank tracker, the spend
cap, dry-run, and a "How to verify" section.

## Error handling

- Provider not configured, cap reached, or provider error: that keyword's
  check is `skipped` with a reason. The other keywords and the run continue.
- Alert channel failure: logged and recorded on the alert row. The run
  succeeds.
- Central DB unavailable: the rank endpoints return 503, and the scheduled
  job logs and exits.

## Testing (all external calls mocked; no test touches the network)

- `DataForSeoProvider`: request body, auth header and parsing against the
  documented response fixture; error status → `ProviderError`; unmapped
  country → `ValueError`.
- `GoogleCseProvider`: depth clamping and the device note; the `gl` parameter.
- `DryRunProvider`: deterministic and never calls `requests`.
- Spend guard: allows exactly `cap` calls per day, refuses the next, resets on
  a new day, and two threads can't exceed the cap.
- Registry: `dataforseo` without `SERP_DRY_RUN=false` → dry run.
- Tracker: my position by subdomain match, competitor positions,
  skipped-on-cap.
- Rules: each kind, the thresholds, and skip-over-skipped.
- Notifiers: Slack payload; email via a fake SMTP server object; failure
  recorded and not raised.
- De-duplication: running the same evaluation twice sends once.
- **Done-when test:** two scheduled `run_due_rank_checks` runs a day apart on a
  fake provider, where keyword "espresso" goes from 4 to 9. History has two
  checks, and Slack and email each receive exactly one digest containing the
  `drop` (4 → 9).
- In-audit rank checks: existing tests pass, now via the provider.
- API: keyword bulk add, history, competitors, and the manual run defaulting
  to dry run.

## Done when

Scheduled daily checks write history and an alert fires on a simulated drop,
proven by the done-when test and by a dry-run end-to-end check through the
API. **No live paid call is made in this phase without the owner's explicit
OK.**

## Out of scope

- Google Search Console (Phase 5).
- Keyword metrics (volume, difficulty) and SERP clustering (Phase 3).
- Rank charts in the dashboard (Phase 4).
- Live verification with real credentials (rank-tracking Task 11) needs your
  keys, and will be run with you when they're available.
