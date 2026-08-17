# Keyword Rank Tracking & Rank-Aware Suggestions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each tracked keyword's Google position in the dashboard, and suggest replacement keywords for keywords that genuinely do not rank.

**Architecture:** The rank-checking and suggestion engines already exist in `app/seo/`. This plan makes them reachable: it loads `.env` so credentials apply at all, adds a `rank_targets` audit parameter so rank checks fire only on user-nominated `{url, keywords}` pairs (bounding quota spend), replaces fragile note-string matching with an explicit `status` field, seeds suggestions from genuinely-unranked keywords only, and adds the UI to drive and display it.

**Tech Stack:** Python 3.14 / FastAPI / Pydantic v2 / pytest on the backend; Next.js 14 / React 18 / TypeScript / Vitest / Tailwind on the frontend.

## Global Constraints

- Google CSE free tier is **100 queries per day**. One query = one keyword on one page.
- `GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE` (default 3) caps *automatic* extraction only; it must never silently truncate user-nominated keywords.
- `rank_targets[].keywords` is bounded to **1..10** entries by schema validation.
- No failure in rank checking or suggestions may abort an audit.
- Never log, echo, or commit a credential value. `.env` and `.env.*` are gitignored (`!.env.example` excepted).
- Suggestions seed **only** from `status == "not_ranked"`. Never from `skipped`.
- Backend tests: `pytest` from `apps/backend`. Frontend tests: `npm test` from `apps/frontend`.

---

### Task 1: Load `.env` in the Python backend

The live backend is the Python FastAPI app. `app/config/config.py` calls bare `os.getenv`, and nothing loads a `.env` file — the only `dotenv` call in the repo is in `apps/backend/src/server.ts`, the legacy Express server that no longer runs. Without this task, a user pasting real credentials into `.env` still gets "ranking check unavailable". Everything else in this plan depends on it.

**Files:**
- Modify: `apps/backend/requirements.txt`
- Modify: `apps/backend/app/config/config.py:1-13`
- Create: `apps/backend/.env` (empty values, gitignored)
- Test: `apps/backend/tests/test_config_env.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `app.config.config` module reads `apps/backend/.env` at import. Attribute names unchanged: `GOOGLE_CSE_API_KEY`, `GOOGLE_CSE_CX`, `GOOGLE_CSE_DAILY_QUOTA`, `GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE`, `GOOGLE_CSE_CACHE_TTL_HOURS`.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_config_env.py`:

```python
import importlib
from pathlib import Path


def test_config_reads_values_from_backend_dotenv(tmp_path, monkeypatch):
    """config.py must load apps/backend/.env, not just os.environ."""
    env_file = Path(__file__).resolve().parents[1] / ".env"
    assert env_file.exists(), "apps/backend/.env must exist (empty values are fine)"

    monkeypatch.delenv("GOOGLE_CSE_API_KEY", raising=False)
    monkeypatch.setattr(
        "dotenv.load_dotenv",
        lambda *a, **k: __import__("os").environ.setdefault("GOOGLE_CSE_API_KEY", "from-dotenv"),
    )

    from app.config import config as config_module
    reloaded = importlib.reload(config_module)

    assert reloaded.GOOGLE_CSE_API_KEY == "from-dotenv"


def test_dotenv_does_not_override_real_environment(monkeypatch):
    """An explicitly exported env var must win over the .env file."""
    monkeypatch.setenv("GOOGLE_CSE_CX", "from-real-env")

    from app.config import config as config_module
    reloaded = importlib.reload(config_module)

    assert reloaded.GOOGLE_CSE_CX == "from-real-env"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_config_env.py -v`
Expected: FAIL — `apps/backend/.env` does not exist, and `dotenv` is not importable.

- [ ] **Step 3: Add the dependency**

Append to `apps/backend/requirements.txt`:

```
python-dotenv>=1.0.0
```

Install it: `cd apps/backend && python -m pip install -r requirements.txt`

- [ ] **Step 4: Load the file in config.py**

Replace the top of `apps/backend/app/config/config.py` (currently line 1, `import os`) with:

```python
import os
from pathlib import Path

from dotenv import load_dotenv

# The live backend is the Python app; apps/backend/src/server.ts (which called
# dotenv.config()) is the retired Express server. Without this, GOOGLE_CSE_*
# values pasted into apps/backend/.env are never read and every rank check
# reports "not configured".
# override=False so a real exported environment variable still wins.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
```

Leave lines 3-13 (the `PORT = ...` through `GOOGLE_CSE_CACHE_TTL_HOURS = ...` assignments) exactly as they are.

- [ ] **Step 5: Create the .env scaffold**

Create `apps/backend/.env` by copying `.env.example` verbatim — every key present, every value empty or default:

```
PORT=5000
NODE_ENV=development
CRAWL_TIMEOUT=10
MAX_DEPTH=2
HF_TOKEN=
GOOGLE_CSE_API_KEY=
GOOGLE_CSE_CX=
GOOGLE_CSE_DAILY_QUOTA=100
GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE=3
GOOGLE_CSE_CACHE_TTL_HOURS=24
```

Do not write any real credential value. The user fills in `GOOGLE_CSE_API_KEY` and `GOOGLE_CSE_CX` themselves.

- [ ] **Step 6: Verify .env is not stageable**

Run: `cd apps/backend && git check-ignore -v .env`
Expected: prints a matching `.gitignore` rule. If it prints nothing, STOP — the file would be committable.

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd apps/backend && python -m pytest tests/test_config_env.py -v`
Expected: PASS (2 tests)

- [ ] **Step 8: Commit**

```bash
git add apps/backend/requirements.txt apps/backend/app/config/config.py apps/backend/tests/test_config_env.py
git commit -m "fix: load apps/backend/.env in the Python backend config"
```

`.env` itself is gitignored and must not appear in the commit.

---

### Task 2: Add explicit `status` to rank results

`check_rankings()` signals outcome only through free-text `note`, and `keyword-panel.tsx:12` string-matches it against a hardcoded `SKIPPED_NOTES` list missing the `"error"` case. Task 6 needs to distinguish "genuinely does not rank" from "never checked", which note-matching cannot do reliably.

**Files:**
- Modify: `apps/backend/app/seo/rank_checker.py:126-164`
- Test: `apps/backend/tests/test_rank_checker.py`

**Interfaces:**
- Consumes: Task 1's config loading.
- Produces: every dict returned by `check_rankings()` gains `status: str`, one of `"ranked"`, `"not_ranked"`, `"skipped"`. Existing keys `keyword`, `position`, `note`, `checked_at`, `top_urls` are unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/test_rank_checker.py`:

```python
def test_status_is_ranked_when_position_found():
    items = [{"link": "https://example.com/page"}]

    with patch("app.seo.rank_checker.requests.get", return_value=_canned_response(items)):
        result = rank_checker.check_rankings("https://example.com/page", ["espresso"], FAKE_CONFIG)

    assert result[0]["status"] == "ranked"
    assert result[0]["position"] == 1


def test_status_is_not_ranked_when_absent_from_top_10():
    items = [{"link": f"https://competitor{i}.com/"} for i in range(10)]

    with patch("app.seo.rank_checker.requests.get", return_value=_canned_response(items)):
        result = rank_checker.check_rankings("https://example.com/page", ["espresso"], FAKE_CONFIG)

    assert result[0]["status"] == "not_ranked"
    assert result[0]["position"] is None


def test_status_is_skipped_when_not_configured():
    unconfigured = SimpleNamespace(
        GOOGLE_CSE_API_KEY="", GOOGLE_CSE_CX="",
        GOOGLE_CSE_DAILY_QUOTA=100, GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE=3,
        GOOGLE_CSE_CACHE_TTL_HOURS=24,
    )
    result = rank_checker.check_rankings("https://example.com/page", ["espresso"], unconfigured)

    assert result[0]["status"] == "skipped"
    assert result[0]["position"] is None


def test_status_is_skipped_when_quota_reached():
    exhausted = SimpleNamespace(
        GOOGLE_CSE_API_KEY="k", GOOGLE_CSE_CX="cx",
        GOOGLE_CSE_DAILY_QUOTA=0, GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE=3,
        GOOGLE_CSE_CACHE_TTL_HOURS=24,
    )
    result = rank_checker.check_rankings("https://example.com/page", ["espresso"], exhausted)

    assert result[0]["status"] == "skipped"


def test_status_is_skipped_on_request_error():
    with patch("app.seo.rank_checker.requests.get", side_effect=RuntimeError("boom")):
        result = rank_checker.check_rankings("https://example.com/page", ["espresso"], FAKE_CONFIG)

    assert result[0]["status"] == "skipped"
    assert result[0]["note"] == "ranking check failed — Google CSE request error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_rank_checker.py -v`
Expected: the five new tests FAIL with `KeyError: 'status'`. Pre-existing tests still pass.

- [ ] **Step 3: Implement**

In `apps/backend/app/seo/rank_checker.py`, in `check_rankings()`, replace the skip-branch append (currently lines 142-148) with:

```python
            results.append({
                "keyword": kw,
                "position": None,
                "status": "skipped",
                "note": _NOTES[skip_reason],
                "checked_at": checked_at,
                "top_urls": [],
            })
            continue
```

and replace the success append (currently lines 157-163) with:

```python
        results.append({
            "keyword": kw,
            "position": position,
            "status": "ranked" if position else "not_ranked",
            "note": None if position else "not found in top 10",
            "checked_at": checked_at,
            "top_urls": urls,
        })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && python -m pytest tests/test_rank_checker.py -v`
Expected: PASS, all tests including pre-existing ones.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/seo/rank_checker.py apps/backend/tests/test_rank_checker.py
git commit -m "feat: add explicit status field to rank check results"
```

---

### Task 3: Let nominated keywords bypass the per-page cap

`check_rankings()` truncates to `config.GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE` (default 3). That guard is right for automatic extraction but would silently discard keywords a user typed in deliberately.

**Files:**
- Modify: `apps/backend/app/seo/rank_checker.py:126-135`
- Test: `apps/backend/tests/test_rank_checker.py`

**Interfaces:**
- Consumes: Task 2's `status` field.
- Produces: `check_rankings(page_url, keywords, config, deep_rank_check=False, max_keywords=None)`. When `max_keywords` is `None`, the config cap applies (unchanged behaviour). When an int, it overrides the cap.

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/test_rank_checker.py`:

```python
def test_config_cap_applies_when_max_keywords_not_given():
    items = [{"link": "https://other.com/"}]
    keywords = ["one", "two", "three", "four", "five"]

    with patch("app.seo.rank_checker.requests.get", return_value=_canned_response(items)) as mock_get:
        result = rank_checker.check_rankings("https://example.com/page", keywords, FAKE_CONFIG)

    assert len(result) == 3
    assert mock_get.call_count == 3


def test_max_keywords_overrides_config_cap():
    items = [{"link": "https://other.com/"}]
    keywords = ["one", "two", "three", "four", "five"]

    with patch("app.seo.rank_checker.requests.get", return_value=_canned_response(items)) as mock_get:
        result = rank_checker.check_rankings(
            "https://example.com/page", keywords, FAKE_CONFIG, max_keywords=5
        )

    assert len(result) == 5
    assert mock_get.call_count == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_rank_checker.py -k max_keywords -v`
Expected: FAIL — `check_rankings() got an unexpected keyword argument 'max_keywords'`.

- [ ] **Step 3: Implement**

In `apps/backend/app/seo/rank_checker.py`, change the `check_rankings` signature and the `capped` line:

```python
def check_rankings(
    page_url: str,
    keywords: List[str],
    config,
    deep_rank_check: bool = False,
    max_keywords: Optional[int] = None,
) -> List[Dict]:
```

```python
    # The config cap guards *automatic* extraction from spending quota. Keywords a
    # user nominated explicitly must not be silently dropped, so callers with an
    # explicit list pass their own bound.
    limit = max_keywords if max_keywords is not None else config.GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE
    capped = keywords[:limit]
```

`Optional` is already imported at line 12.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && python -m pytest tests/test_rank_checker.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/seo/rank_checker.py apps/backend/tests/test_rank_checker.py
git commit -m "feat: allow explicit max_keywords override in check_rankings"
```

---

### Task 4: Add the `RankTarget` request schema

**Files:**
- Modify: `apps/backend/app/schemas/schemas.py:1-14`
- Test: `apps/backend/tests/test_rank_targets_schema.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `app.schemas.schemas.RankTarget` with fields `url: str` and `keywords: List[str]` (1..10). `AuditRequestParams.rank_targets: Optional[List[RankTarget]] = None`.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_rank_targets_schema.py`:

```python
import pytest
from pydantic import ValidationError

from app.schemas.schemas import AuditRequestParams, RankTarget


def test_rank_target_accepts_url_and_keywords():
    t = RankTarget(url="https://example.com/services", keywords=["cloud consulting"])
    assert t.url == "https://example.com/services"
    assert t.keywords == ["cloud consulting"]


def test_rank_target_rejects_empty_keyword_list():
    with pytest.raises(ValidationError):
        RankTarget(url="https://example.com/", keywords=[])


def test_rank_target_rejects_more_than_ten_keywords():
    with pytest.raises(ValidationError):
        RankTarget(url="https://example.com/", keywords=[f"kw{i}" for i in range(11)])


def test_audit_params_default_rank_targets_to_none():
    params = AuditRequestParams(url="https://example.com")
    assert params.rank_targets is None


def test_audit_params_accepts_rank_targets():
    params = AuditRequestParams(
        url="https://example.com",
        rank_targets=[{"url": "https://example.com/a", "keywords": ["x", "y"]}],
    )
    assert len(params.rank_targets) == 1
    assert params.rank_targets[0].keywords == ["x", "y"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_rank_targets_schema.py -v`
Expected: FAIL — `ImportError: cannot import name 'RankTarget'`.

- [ ] **Step 3: Implement**

In `apps/backend/app/schemas/schemas.py`, insert before `class AuditRequestParams`:

```python
class RankTarget(BaseModel):
    """One user-nominated page and the keywords to rank-check on it.

    Nomination is what bounds quota spend: the free Google CSE tier allows 100
    queries/day and one query is one keyword on one page, so checking every
    crawled page would exhaust a day in a single audit of any real site.
    """
    url: str
    keywords: List[str] = Field(min_length=1, max_length=10)
```

Then add this field to `AuditRequestParams`, after `target_keywords` (line 14):

```python
    rank_targets: Optional[List[RankTarget]] = None
```

`BaseModel`, `Field`, `List`, and `Optional` are all already imported at lines 1-2.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && python -m pytest tests/test_rank_targets_schema.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/schemas/schemas.py apps/backend/tests/test_rank_targets_schema.py
git commit -m "feat: add RankTarget schema and rank_targets audit param"
```

---

### Task 5: Rank-check only nominated pages

**Files:**
- Modify: `apps/backend/app/services/audit_service.py:52-95` (signatures), `:218-224` (rank call)
- Test: `apps/backend/tests/test_rank_target_matching.py`

**Interfaces:**
- Consumes: Task 3's `max_keywords`, Task 4's `RankTarget`.
- Produces: `audit_service._match_rank_target(page_url: str, rank_targets: Optional[List[Any]]) -> Optional[List[str]]` returning the nominated keyword list for a page, else `None`. `run_full_audit(...)` and `run_audit_task(...)` both accept `rank_targets: Optional[List[Any]] = None`.

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/test_rank_target_matching.py`:

```python
from types import SimpleNamespace

from app.services import audit_service


def _target(url, keywords):
    return SimpleNamespace(url=url, keywords=keywords)


def test_matches_ignoring_scheme_www_and_trailing_slash():
    targets = [_target("example.com/services", ["cloud"])]
    assert audit_service._match_rank_target("https://www.example.com/services/", targets) == ["cloud"]


def test_matches_ignoring_query_string_and_fragment():
    targets = [_target("https://example.com/services", ["cloud"])]
    assert audit_service._match_rank_target("https://example.com/services?utm=1#top", targets) == ["cloud"]


def test_returns_none_for_unnominated_page():
    targets = [_target("https://example.com/services", ["cloud"])]
    assert audit_service._match_rank_target("https://example.com/about", targets) is None


def test_returns_none_when_no_targets_supplied():
    assert audit_service._match_rank_target("https://example.com/", None) is None
    assert audit_service._match_rank_target("https://example.com/", []) is None


def test_distinct_pages_get_their_own_keywords():
    targets = [
        _target("https://example.com/a", ["alpha"]),
        _target("https://example.com/b", ["beta", "gamma"]),
    ]
    assert audit_service._match_rank_target("https://example.com/a", targets) == ["alpha"]
    assert audit_service._match_rank_target("https://example.com/b", targets) == ["beta", "gamma"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_rank_target_matching.py -v`
Expected: FAIL — `module 'app.services.audit_service' has no attribute '_match_rank_target'`.

- [ ] **Step 3: Implement the matcher**

In `apps/backend/app/services/audit_service.py`, add after `_resolve_keyword_data` (after line 49):

```python
def _match_rank_target(page_url: str, rank_targets: Optional[List[Any]]) -> Optional[List[str]]:
    """Return the nominated keywords for `page_url`, or None if not nominated.

    Both sides are normalised with rank_checker._normalize_url, which strips
    scheme, leading www., query string, fragment, and trailing slash — so a user
    typing "example.com/services" matches the crawled
    "https://www.example.com/services/".
    """
    if not rank_targets:
        return None
    normalized_page = rank_checker._normalize_url(page_url)
    for target in rank_targets:
        if rank_checker._normalize_url(target.url) == normalized_page:
            return list(target.keywords)
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && python -m pytest tests/test_rank_target_matching.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Thread the parameter through**

Add `rank_targets: Optional[List[Any]] = None,` to the parameter list of `run_audit_task` (near line 63, after `enable_competitor_gap`) and of `run_full_audit` (near line 95, after `enable_competitor_gap`). In `run_audit_task`'s call into the audit (near lines 80-81), pass `rank_targets=rank_targets,` alongside the existing flags.

- [ ] **Step 6: Replace the rank call**

In `apps/backend/app/services/audit_service.py`, replace lines 221-224:

```python
        rank_data = (
            rank_checker.check_rankings(page_url, [k["phrase"] for k in keyword_data], config)
            if enable_rank_check else []
        )
```

with:

```python
        # Rank checks fire only on pages the user nominated. With enable_rank_check
        # on but nothing nominated, spend is zero rather than one query per keyword
        # per crawled page — which would exhaust the 100/day free tier in one audit.
        nominated_keywords = _match_rank_target(page_url, rank_targets)
        rank_data = (
            rank_checker.check_rankings(
                page_url, nominated_keywords, config, max_keywords=len(nominated_keywords)
            )
            if enable_rank_check and nominated_keywords else []
        )
```

- [ ] **Step 7: Write the quota-bounding test**

Create `apps/backend/tests/test_rank_quota_bounding.py`:

```python
from types import SimpleNamespace
from unittest.mock import patch

from app.services import audit_service


def test_unnominated_page_spends_no_queries():
    targets = [SimpleNamespace(url="https://example.com/a", keywords=["alpha"])]

    with patch("app.seo.rank_checker.check_rankings") as mock_check:
        keywords = audit_service._match_rank_target("https://example.com/zzz", targets)

    assert keywords is None
    mock_check.assert_not_called()


def test_nominated_page_returns_exactly_its_keywords():
    targets = [SimpleNamespace(url="https://example.com/a", keywords=["alpha", "beta"])]
    assert audit_service._match_rank_target("https://example.com/a", targets) == ["alpha", "beta"]
```

- [ ] **Step 8: Echo the nominated targets into the response**

A nominated URL the crawl never reached produces no page card, so its absence would be
invisible in the UI. The frontend needs to know what was asked for in order to report
what was missed. In the result dict (the flat dict beginning near line 301), add after
`"pages": page_rows,` (line 310):

```python
        "rank_targets": [
            {"url": t.url, "keywords": list(t.keywords)} for t in (rank_targets or [])
        ],
```

- [ ] **Step 9: Run the full backend suite**

Run: `cd apps/backend && python -m pytest -v`
Expected: PASS, including the pre-existing gating tests in `test_audit_service_crawler_registry.py`.

- [ ] **Step 10: Commit**

```bash
git add apps/backend/app/services/audit_service.py apps/backend/tests/test_rank_target_matching.py apps/backend/tests/test_rank_quota_bounding.py
git commit -m "feat: rank-check only user-nominated pages"
```

---

### Task 6: Seed suggestions from genuinely-unranked keywords

The crux of the feature. A null position means either "does not rank" or "was never checked". Seeding from the latter would fabricate advice from missing data — worst before credentials are configured, when every keyword would look like a failure.

**Files:**
- Modify: `apps/backend/app/seo/keyword_suggestions.py:101-132`
- Modify: `apps/backend/app/services/audit_service.py:235-242`
- Test: `apps/backend/tests/test_keyword_suggestions.py`

**Interfaces:**
- Consumes: Task 2's `status` field.
- Produces: `suggest_keywords(seed_keywords, rank_results, config, fetch_page, page_url, enable_competitor_gap=False)` now derives underperformers internally from `rank_results`. Every returned suggestion dict gains `replaces: Optional[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/test_keyword_suggestions.py`:

```python
from unittest.mock import patch

from app.seo import keyword_suggestions


FAKE_CONFIG_S = SimpleNamespace(
    GOOGLE_CSE_API_KEY="k", GOOGLE_CSE_CX="cx",
    GOOGLE_CSE_DAILY_QUOTA=100, GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE=3,
    GOOGLE_CSE_CACHE_TTL_HOURS=24,
)


def _rank(keyword, status, position=None):
    return {"keyword": keyword, "position": position, "status": status,
            "note": None, "checked_at": "", "top_urls": []}


def test_suggestions_seed_from_not_ranked_keyword():
    seeds = [{"phrase": "espresso machine", "score": None, "found_in": []}]
    ranks = [_rank("espresso machine", "not_ranked")]

    with patch.object(keyword_suggestions, "_autocomplete_suggestions", return_value=["espresso machine reviews"]):
        out = keyword_suggestions.suggest_keywords(
            seeds, ranks, FAKE_CONFIG_S, fetch_page=lambda u: None, page_url="https://example.com/"
        )

    assert [s["phrase"] for s in out] == ["espresso machine reviews"]
    assert out[0]["replaces"] == "espresso machine"


def test_skipped_status_produces_no_suggestions():
    """Not configured / quota reached / request error mean nothing was measured."""
    seeds = [{"phrase": "espresso machine", "score": None, "found_in": []}]
    ranks = [_rank("espresso machine", "skipped")]

    with patch.object(keyword_suggestions, "_autocomplete_suggestions", return_value=["anything"]) as mock_ac:
        out = keyword_suggestions.suggest_keywords(
            seeds, ranks, FAKE_CONFIG_S, fetch_page=lambda u: None, page_url="https://example.com/"
        )

    assert out == []
    mock_ac.assert_not_called()


def test_ranked_keyword_produces_no_suggestions():
    seeds = [{"phrase": "espresso machine", "score": None, "found_in": []}]
    ranks = [_rank("espresso machine", "ranked", position=3)]

    with patch.object(keyword_suggestions, "_autocomplete_suggestions", return_value=["anything"]):
        out = keyword_suggestions.suggest_keywords(
            seeds, ranks, FAKE_CONFIG_S, fetch_page=lambda u: None, page_url="https://example.com/"
        )

    assert out == []


def test_no_rank_data_falls_back_to_seed_keywords():
    """Backward compatibility: suggestions still work with rank checking off."""
    seeds = [{"phrase": "espresso machine", "score": None, "found_in": []}]

    with patch.object(keyword_suggestions, "_autocomplete_suggestions", return_value=["espresso grinder"]):
        out = keyword_suggestions.suggest_keywords(
            seeds, [], FAKE_CONFIG_S, fetch_page=lambda u: None, page_url="https://example.com/"
        )

    assert [s["phrase"] for s in out] == ["espresso grinder"]
    assert out[0]["replaces"] is None
```

Add `from types import SimpleNamespace` at the top of the file if it is not already imported.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_keyword_suggestions.py -v`
Expected: the four new tests FAIL — `KeyError: 'replaces'` and suggestions generated for skipped/ranked keywords.

- [ ] **Step 3: Implement**

In `apps/backend/app/seo/keyword_suggestions.py`, replace the body of `suggest_keywords` (lines 109-132) with:

```python
    current_phrases = {k["phrase"].lower() for k in seed_keywords}
    suggestions: List[Dict] = []
    seen = set()

    # Only "not_ranked" is evidence of underperformance. "skipped" means the check
    # never ran (no credentials, quota exhausted, or request error) — seeding from
    # it would invent replacements for keywords nobody measured.
    underperforming = [r["keyword"] for r in rank_results if r.get("status") == "not_ranked"]
    has_rank_data = any(r.get("status") in ("ranked", "not_ranked") for r in rank_results)

    if has_rank_data:
        seed_phrases = [(kw, kw) for kw in underperforming[:3]]
    else:
        seed_phrases = [(s["phrase"], None) for s in seed_keywords[:3]]

    for seed_phrase, replaces in seed_phrases:
        for phrase in _autocomplete_suggestions(seed_phrase):
            key = phrase.lower()
            if key in seen or key in current_phrases:
                continue
            seen.add(key)
            suggestions.append({
                "phrase": phrase,
                "reason": "related search",
                "competitor_examples": None,
                "replaces": replaces,
            })

    if enable_competitor_gap and seed_keywords:
        page_domain = rank_checker._domain(page_url)
        gap_seed = underperforming[0] if underperforming else seed_keywords[0]["phrase"]
        for gap in _competitor_gap(
            gap_seed, page_domain, current_phrases, rank_results, config, fetch_page
        ):
            key = gap["phrase"].lower()
            if key in seen or key in current_phrases:
                continue
            seen.add(key)
            gap["replaces"] = gap_seed if underperforming else None
            suggestions.append(gap)

    return suggestions[:MAX_SUGGESTIONS]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && python -m pytest tests/test_keyword_suggestions.py -v`
Expected: PASS, including pre-existing tests in the file.

- [ ] **Step 5: Run the full backend suite**

Run: `cd apps/backend && python -m pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/seo/keyword_suggestions.py apps/backend/tests/test_keyword_suggestions.py
git commit -m "feat: seed keyword suggestions from genuinely unranked keywords only"
```

---

### Task 7: Pass `rank_targets` through the API route

**Files:**
- Modify: `apps/backend/app/api/routes.py:64-75`

**Interfaces:**
- Consumes: Task 4's `AuditRequestParams.rank_targets`, Task 5's `run_full_audit(rank_targets=...)`.
- Produces: `POST /api/audit` forwards `rank_targets` to the audit.

- [ ] **Step 1: Implement**

In `apps/backend/app/api/routes.py`, add this line to the `run_full_audit(...)` call, immediately after `target_keywords=params.target_keywords,` (line 74):

```python
                rank_targets=params.rank_targets,
```

- [ ] **Step 2: Verify the route accepts the field end to end**

Start the backend: `cd apps/backend && python -m uvicorn app.main:app --port 5000`

In a second shell:

```bash
curl -s -X POST http://localhost:5000/api/audit \
  -H "Content-Type: application/json" \
  -d '{"url":"http://localhost:3000","max_pages":2,"enable_rank_check":true,"rank_targets":[{"url":"http://localhost:3000/","keywords":["seo auditor"]}]}'
```

Expected: HTTP 200 with a `session_id`. Not a 422 validation error.

- [ ] **Step 3: Confirm it appears in the OpenAPI schema**

Run: `curl -s http://localhost:5000/openapi.json | grep -o "rank_targets"`
Expected: prints `rank_targets`.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/app/api/routes.py
git commit -m "feat: forward rank_targets from the audit route"
```

---

### Task 8: Mirror the new types in the shared package

**Files:**
- Modify: `packages/shared/src/types/index.ts:53-70` and the audit-params interface at `:188-194`

**Interfaces:**
- Consumes: Tasks 2, 4, 6 (field names must match the Python payload exactly).
- Produces: `RankTarget`, `KeywordRanking.status`, `SuggestedKeyword.replaces`, and `rank_targets` on the audit request params interface.

- [ ] **Step 1: Implement**

In `packages/shared/src/types/index.ts`, replace the `KeywordRanking` and `SuggestedKeyword` interfaces (lines 53-64) with:

```typescript
export type RankStatus = "ranked" | "not_ranked" | "skipped";

export interface KeywordRanking {
  keyword: string;
  position: number | null;
  /** "skipped" means the check never ran — not that the page ranks badly. */
  status: RankStatus;
  note?: string | null;
  checked_at?: string;
}

export interface SuggestedKeyword {
  phrase: string;
  reason: string;
  competitor_examples?: string[] | null;
  /** The underperforming keyword this is offered as a replacement for. */
  replaces?: string | null;
}

export interface RankTarget {
  url: string;
  keywords: string[];
}
```

Then add to `AuditRequestParams` (line 185), immediately after `enable_competitor_gap`:

```typescript
  rank_targets?: RankTarget[];
```

And add the same field to `AuditResponse` (line 173), after `note: string;`, so the
dashboard can tell which nominated pages the crawl never reached:

```typescript
  rank_targets?: RankTarget[];
```

- [ ] **Step 2: Build the shared package**

Run: `cd packages/shared && npm run build`
Expected: `npx tsc` completes with no errors.

- [ ] **Step 3: Commit**

```bash
git add packages/shared/src/types/index.ts
git commit -m "feat: add RankTarget, rank status, and replaces to shared types"
```

---

### Task 9: Rank-target input on the start form

**Files:**
- Modify: `apps/frontend/app/page.tsx:81-92` (state), `:140-162` (submit), `:312-325` (Advanced Overrides)
- Test: `apps/frontend/components/__tests__/rank-targets.test.tsx`

**Interfaces:**
- Consumes: Task 8's `RankTarget` type, Task 7's route.
- Produces: `POST /api/audit` bodies that include `rank_targets`, `enable_rank_check`, and `enable_keyword_suggestions` when at least one complete row exists. Exports `buildRankTargets(rows)` and `countQueries(rows)` from `apps/frontend/lib/rank-targets.ts`.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/components/__tests__/rank-targets.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { buildRankTargets, countQueries } from "@/lib/rank-targets";

describe("buildRankTargets", () => {
  it("splits comma-separated keywords and trims whitespace", () => {
    const rows = [{ url: "https://a.com/x", keywords: " cloud , devops " }];
    expect(buildRankTargets(rows)).toEqual([
      { url: "https://a.com/x", keywords: ["cloud", "devops"] },
    ]);
  });

  it("drops rows missing a url or keywords", () => {
    const rows = [
      { url: "", keywords: "cloud" },
      { url: "https://a.com/x", keywords: "" },
      { url: "https://a.com/y", keywords: "seo" },
    ];
    expect(buildRankTargets(rows)).toEqual([{ url: "https://a.com/y", keywords: ["seo"] }]);
  });

  it("caps each row at ten keywords to match schema validation", () => {
    const rows = [{ url: "https://a.com/x", keywords: Array.from({ length: 15 }, (_, i) => `k${i}`).join(",") }];
    expect(buildRankTargets(rows)[0].keywords).toHaveLength(10);
  });
});

describe("countQueries", () => {
  it("sums keyword counts across rows", () => {
    const rows = [
      { url: "https://a.com/x", keywords: "one,two" },
      { url: "https://a.com/y", keywords: "three" },
    ];
    expect(countQueries(rows)).toBe(3);
  });

  it("counts nothing for incomplete rows", () => {
    expect(countQueries([{ url: "", keywords: "one,two" }])).toBe(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npm test -- rank-targets`
Expected: FAIL — cannot resolve `@/lib/rank-targets`.

- [ ] **Step 3: Implement the helper**

Create `apps/frontend/lib/rank-targets.ts`:

```typescript
import { RankTarget } from "@seo-auditor/shared";

export interface RankTargetRow {
  url: string;
  keywords: string;
}

const MAX_KEYWORDS_PER_TARGET = 10;

/** Convert UI rows into API payload shape, dropping incomplete rows. */
export function buildRankTargets(rows: RankTargetRow[]): RankTarget[] {
  return rows
    .map(row => ({
      url: row.url.trim(),
      keywords: row.keywords
        .split(",")
        .map(k => k.trim())
        .filter(Boolean)
        .slice(0, MAX_KEYWORDS_PER_TARGET),
    }))
    .filter(t => t.url.length > 0 && t.keywords.length > 0);
}

/** One Google CSE query is spent per keyword per page. */
export function countQueries(rows: RankTargetRow[]): number {
  return buildRankTargets(rows).reduce((sum, t) => sum + t.keywords.length, 0);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/frontend && npm test -- rank-targets`
Expected: PASS (5 tests)

- [ ] **Step 5: Add form state**

In `apps/frontend/app/page.tsx`, add after line 88 (`const [advancedOpen, setAdvancedOpen] = useState(false);`):

```tsx
  const [rankRows, setRankRows] = useState<RankTargetRow[]>([{ url: "", keywords: "" }]);
```

Add these imports alongside the existing ones:

```tsx
import { buildRankTargets, countQueries, RankTargetRow } from "@/lib/rank-targets";
```

And derive the readout near the other `useMemo` usage:

```tsx
  const rankQueryCount = useMemo(() => countQueries(rankRows), [rankRows]);
```

- [ ] **Step 6: Add the UI block**

In `apps/frontend/app/page.tsx`, insert inside `CollapsibleContent`, immediately after the "Ignore robots.txt" label block (after line 324):

```tsx
                <div className="space-y-3 rounded-lg border border-border/50 bg-muted/20 p-3">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-semibold">Keyword rank tracking</p>
                    <span className={`text-xs ${rankQueryCount > 100 ? "text-rose-500 font-semibold" : "text-muted-foreground"}`}>
                      will use {rankQueryCount} of your 100 daily queries
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Only the pages you list here are rank-checked. Requires Google CSE credentials in apps/backend/.env.
                  </p>
                  {rankRows.map((row, i) => (
                    <div key={i} className="flex gap-2">
                      <Input
                        placeholder="https://example.com/services"
                        value={row.url}
                        onChange={e => setRankRows(rows => rows.map((r, j) => j === i ? { ...r, url: e.target.value } : r))}
                        disabled={isLoading}
                        className="flex-1"
                      />
                      <Input
                        placeholder="keyword one, keyword two"
                        value={row.keywords}
                        onChange={e => setRankRows(rows => rows.map((r, j) => j === i ? { ...r, keywords: e.target.value } : r))}
                        disabled={isLoading}
                        className="flex-1"
                      />
                      <Button
                        type="button" variant="ghost" size="sm"
                        onClick={() => setRankRows(rows => rows.length > 1 ? rows.filter((_, j) => j !== i) : rows)}
                        disabled={isLoading}
                      >
                        Remove
                      </Button>
                    </div>
                  ))}
                  <Button
                    type="button" variant="outline" size="sm"
                    onClick={() => setRankRows(rows => [...rows, { url: "", keywords: "" }])}
                    disabled={isLoading}
                  >
                    Add page
                  </Button>
                </div>
```

- [ ] **Step 7: Send the new fields**

In `apps/frontend/app/page.tsx`, replace the `ApiService.runAudit({...})` call body (lines 148-153) with:

```tsx
      const rankTargets = buildRankTargets(rankRows);
      const data = await ApiService.runAudit({
        url: url.trim(),
        max_pages: Math.min(Math.max(maxPages, 1), 5000),
        max_depth: Math.min(Math.max(maxDepth, 0), 15),
        ignore_robots: ignoreRobots,
        ...(rankTargets.length > 0 && {
          rank_targets: rankTargets,
          enable_rank_check: true,
          enable_keyword_suggestions: true,
        }),
      });
```

- [ ] **Step 8: Verify build and tests**

Run: `cd apps/frontend && npx tsc --noEmit && npm test && npx next lint`
Expected: typecheck clean, all tests pass, lint clean.

- [ ] **Step 9: Commit**

```bash
git add apps/frontend/lib/rank-targets.ts apps/frontend/app/page.tsx apps/frontend/components/__tests__/rank-targets.test.tsx
git commit -m "feat: add keyword rank tracking inputs to the audit start form"
```

---

### Task 10: Render ranks and replacements in the keyword panel

**Files:**
- Modify: `apps/frontend/components/keyword-panel.tsx:12-15` (remove `SKIPPED_NOTES`), `:74-111` (rendering)
- Test: `apps/frontend/components/__tests__/keyword-panel.test.tsx`

**Interfaces:**
- Consumes: Task 8's `RankStatus` and `SuggestedKeyword.replaces`.
- Produces: `KeywordPanel` accepts an optional `rankTargets?: RankTarget[]` prop for the not-reached list. Callers that omit it keep current behaviour.

- [ ] **Step 1: Write the failing tests**

Append to `apps/frontend/components/__tests__/keyword-panel.test.tsx`:

```tsx
it("shows the position for a ranked keyword", () => {
  const pages = [{
    url: "https://example.com/a",
    keyword_analysis: {
      top_keywords: [{ phrase: "cloud", score: null, found_in: ["title"] }],
      rankings: [{ keyword: "cloud", position: 3, status: "ranked" as const, note: null }],
      suggested_keywords: [],
    },
  }] as any;

  render(<KeywordPanel pages={pages} />);
  expect(screen.getByText("#3")).toBeInTheDocument();
});

it("shows a skipped banner without claiming the keyword ranks badly", () => {
  const pages = [{
    url: "https://example.com/a",
    keyword_analysis: {
      top_keywords: [{ phrase: "cloud", score: null, found_in: ["title"] }],
      rankings: [{
        keyword: "cloud", position: null, status: "skipped" as const,
        note: "ranking check unavailable — Google CSE not configured",
      }],
      suggested_keywords: [],
    },
  }] as any;

  render(<KeywordPanel pages={pages} />);
  expect(screen.getByText(/not configured/i)).toBeInTheDocument();
  expect(screen.queryByText(/not ranking in top 10/i)).not.toBeInTheDocument();
});

it("labels a suggestion with the keyword it replaces", () => {
  const pages = [{
    url: "https://example.com/a",
    keyword_analysis: {
      top_keywords: [{ phrase: "cloud", score: null, found_in: ["title"] }],
      rankings: [{ keyword: "cloud", position: null, status: "not_ranked" as const, note: "not found in top 10" }],
      suggested_keywords: [{ phrase: "cloud migration", reason: "related search", replaces: "cloud" }],
    },
  }] as any;

  render(<KeywordPanel pages={pages} />);
  expect(screen.getByText(/instead of/i)).toBeInTheDocument();
  expect(screen.getByText("cloud migration")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/frontend && npm test -- keyword-panel`
Expected: FAIL — the skipped case renders "not ranking in top 10", and no "instead of" text exists.

- [ ] **Step 3: Replace note-matching with status**

In `apps/frontend/components/keyword-panel.tsx`, delete the `SKIPPED_NOTES` constant (lines 12-15) and replace the `skippedNote` derivation (lines 22-25) with:

```tsx
  const skippedNote = pagesWithKeywords
    .flatMap(p => p.keyword_analysis?.rankings || [])
    .find(r => r.status === "skipped")?.note;
```

- [ ] **Step 4: Render rankings from status**

Replace the ranking `<li>` body (lines 81-86) with:

```tsx
                    <li key={r.keyword} className="flex justify-between border-b border-border/30 pb-1">
                      <span>{r.keyword}</span>
                      <span className={
                        r.status === "ranked" ? "font-semibold text-emerald-500"
                        : r.status === "not_ranked" ? "text-amber-600"
                        : "text-muted-foreground italic"
                      }>
                        {r.status === "ranked" ? `#${r.position}`
                          : r.status === "not_ranked" ? "not in top 10"
                          : "not checked"}
                      </span>
                    </li>
```

- [ ] **Step 5: Render the replaces link**

In the suggested-keywords `<li>` (after line 101, the `reason` span), add:

```tsx
                      {s.replaces && (
                        <span className="text-[11px] text-amber-600 block">
                          instead of <span className="font-medium">{s.replaces}</span>
                        </span>
                      )}
```

- [ ] **Step 6: Add the not-reached list**

Change the component signature to accept the optional prop:

```tsx
interface KeywordPanelProps {
  pages: PageItem[];
  rankTargets?: RankTarget[];
}

export function KeywordPanel({ pages, rankTargets }: KeywordPanelProps) {
```

Import `RankTarget` from `@seo-auditor/shared`. Then, immediately after the `skippedNote` banner block (after line 50), add:

```tsx
      {(() => {
        const crawled = new Set(pages.map(p => p.url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")));
        const missed = (rankTargets || [])
          .map(t => t.url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, ""))
          .filter(u => !crawled.has(u));
        if (missed.length === 0) return null;
        return (
          <div className="rounded-lg border border-border/50 bg-muted/20 px-4 py-2.5 text-xs text-muted-foreground">
            Not reached by this crawl (try a higher max depth, or check robots.txt): {missed.join(", ")}
          </div>
        );
      })()}
```

- [ ] **Step 7: Wire the prop from the dashboard**

Without this the not-reached list can never render. In
`apps/frontend/app/dashboard/page.tsx:249`, change:

```tsx
    "keywords": <Card><CardContent className="pt-6"><KeywordPanel pages={pages} /></CardContent></Card>,
```

to:

```tsx
    "keywords": <Card><CardContent className="pt-6"><KeywordPanel pages={pages} rankTargets={auditData?.rank_targets} /></CardContent></Card>,
```

If the local variable holding the audit response is not named `auditData` at that point
in the file, use whichever name is in scope — it is the object with `.pages` on it.

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd apps/frontend && npm test -- keyword-panel`
Expected: PASS, including the pre-existing tests in the file.

- [ ] **Step 9: Full verification**

Run: `cd apps/frontend && npx tsc --noEmit && npm test && npx next lint`
Then from the repo root: `npm run build`
Expected: all clean.

- [ ] **Step 10: Commit**

```bash
git add apps/frontend/components/keyword-panel.tsx apps/frontend/app/dashboard/page.tsx apps/frontend/components/__tests__/keyword-panel.test.tsx
git commit -m "feat: render rank status and replacement suggestions in keyword panel"
```

---

### Task 11: End-to-end verification with real credentials

**Files:** none modified.

**Interfaces:**
- Consumes: every prior task.
- Produces: nothing; a manual gate.

- [ ] **Step 1: Confirm credentials are in place**

Confirm `apps/backend/.env` has non-empty `GOOGLE_CSE_API_KEY` and `GOOGLE_CSE_CX`. Do not print the file contents. Check only that the values are non-empty:

```bash
cd apps/backend && python -c "from app.config import config; print('key set:', bool(config.GOOGLE_CSE_API_KEY), '| cx set:', bool(config.GOOGLE_CSE_CX))"
```

Expected: `key set: True | cx set: True`

- [ ] **Step 2: Restart both servers**

From the repo root: `npm run dev`

The backend must restart to pick up `.env`, and the in-memory rank cache is discarded on restart — a re-run costs fresh quota.

- [ ] **Step 3: Run one audit with a single nominated page**

In the browser at `http://localhost:3000`, open Advanced Overrides, add one rank-tracking row with a real URL and **one** keyword. Confirm the readout says `will use 1 of your 100 daily queries`. Start the audit.

- [ ] **Step 4: Verify the dashboard**

Expected on the Keyword Intelligence panel for that page:
- a Rankings row showing either `#N` in green or `not in top 10` in amber — **not** `not checked`
- if `not in top 10`, a Suggested Keywords list where entries carry "instead of <keyword>"

If it shows `not checked`, the credentials are not loading — re-check Task 1.

- [ ] **Step 5: Confirm quota spend**

Only pages you nominated should have Rankings sections. Every other crawled page shows Top Keywords with no Rankings block.

---

## Notes for the implementer

- Backend tests run from `apps/backend` (`pytest.ini` lives there). Frontend tests run from `apps/frontend`.
- `rank_checker._normalize_url` and `_domain` are private by convention but are the intended shared helpers — `keyword_suggestions.py:72` already calls `_get_cse_results` the same way.
- Do not remove the `deep_rank_check` parameter. It is deliberately inert, reserved for page-2+ pagination.
- The competitor-gap path nulls `crawler.event_callback` (`audit_service.py:232-244`) so competitor fetch errors do not leak into the live activity feed. Preserve that.
- Never print or log a credential value at any step.
