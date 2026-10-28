# Phase 5.4: Custom rules engine — Design

**Date:** 2026-10-29
**Status:** Approved, pending implementation plan
**Branch:** `feat/complete-site-audit`
**Brief:** `BUILD_PROMPT.md` Phase 5, item 4: "Custom rule engine:
user-defined checks stored per project." Fourth of five Phase 5 sub-projects
(5.1 Core Web Vitals, 5.2 JS rendering and 5.3 accessibility are merged).

## Problem

Every check is built in. A site owner can't say "every product page must have
structured data", "blog titles must end with '| Brand'" or "no page may
contain 'lorem ipsum'" and have each audit enforce it.

## Decisions taken

- **Check types:** page fields, page text and CSS selectors. There are no
  header rules, no regex and no code. Every rule can be limited to a URL path
  pattern.
- **Management:** a "Custom Rules" tab per project with a builder form and a
  "Test on a URL" button, with an API underneath.
- **Severity:** chosen per rule. Failures are ordinary issues and count in the
  health score like built-in ones.

## Design

### 1. The rule model

A new table, `custom_rules` (migration `0007_custom_rules`):

| Column | Type |
| --- | --- |
| `id` | int PK |
| `project_id` | FK `projects.id`, `ON DELETE CASCADE`, indexed |
| `name` | string(80) |
| `enabled` | bool, default true |
| `severity` | string(16): `critical` / `warning` / `info` |
| `message` | string(200) |
| `url_pattern` | string(200), nullable (`fnmatch` glob on the URL path, e.g. `/blog/*`, `/products/*/reviews`) |
| `check_json` | JSON: one check (below) |
| `created_at`, `updated_at` | UTC datetime |

The check is one of these (a pydantic discriminated union, in `app/rules/schema.py`):

```jsonc
{"type": "field", "field": "title", "op": "contains", "value": "| Brand"}
{"type": "text", "scope": "visible", "op": "not_contains", "value": "lorem ipsum", "case_sensitive": false}
{"type": "selector", "selector": "script[type='application/ld+json']", "op": "exists"}
{"type": "selector", "selector": "nav.breadcrumb", "op": "count_lte", "value": 1}
```

| Field | Kind | Operators |
| --- | --- | --- |
| `title`, `meta_description`, `h1`, `canonical`, `meta_robots` | text | `equals`, `not_equals`, `contains`, `not_contains`, `starts_with`, `ends_with`, `is_empty`, `is_not_empty`, `length_gte`, `length_lte` |
| `word_count`, `internal_links_count`, `external_links_count` | number | `eq`, `gte`, `lte` |
| `status`, `response_time_ms` | number (response) | `eq`, `gte`, `lte` |

- **Text checks:** scope `visible` (the page's text, as the content checks
  see it) or `html` (raw markup). Ops are `contains` / `not_contains`.
  `case_sensitive` defaults to false.
- **Selector checks:** ops `exists`, `not_exists`, `count_eq`, `count_gte`,
  `count_lte`. The selector is compiled with `soupsieve` (bs4's own engine)
  when saved, and an invalid one is a 422 with soupsieve's message.
- **Validation:**
  - `value` is required unless the op is `is_empty`, `is_not_empty`,
    `exists` or `not_exists`
  - numbers are ≥ 0
  - strings are ≤ 200 characters, names ≤ 80
  - at most 50 rules per project (409 beyond)
  - field and op must match the field's kind
- Text comparisons strip whitespace. Text field ops are case-insensitive,
  except `equals` / `not_equals`, which are exact after stripping.

### 2. Engine: `app/rules/engine.py` (pure)

```python
@dataclass
class RuleView:            # what workers receive (plain, picklable)
    id: int; name: str; severity: str; message: str
    url_pattern: Optional[str]; check: Dict[str, Any]

def applies(rule, url) -> bool                        # url_pattern vs urlsplit(url).path
def html_phase(rules, url, meta, visible_text, html, soup) -> List[issue]
def response_phase(rules, url, status, response_time_ms) -> List[issue]
def describe(check) -> str                             # "Title contains '| Brand'"
def observe(check, page) -> Any                        # value the rule saw (for the test endpoint)
```

- `html_phase` runs field rules on HTML fields, text rules and selector
  rules. `response_phase` runs `status` and `response_time_ms` rules.
- A missing field value counts as `""` or `0`.
- **Issue:**
  - code `CUSTOM_<rule id>`
  - severity = the rule's severity
  - message `"{name}: {message}"`
  - extra keys `"rule_id"` and `"source": "custom"`
- The code stays stable when a rule is renamed, so diffs and alerts track it.

### 3. Audit integration

- **At audit start** (`_build_audit_result`): load the enabled rules of the
  project whose domain matches `project_domain(url)` (no project means no
  rules). This is wrapped so a DB failure means "no rules", logged.
  `run_full_audit` passes nothing new. The CLI uses the same lookup.
- **Workers:** `PagePayload.custom_rules: List[dict]` carries `RuleView`
  dicts.
  - `analyze_html` calls `html_phase` with the shared soup and the meta/text
    it already computed, so issues land in `HtmlAnalysis.issues`.
  - `analyze_response` calls `response_phase`.
- **Page cache:** `analyzer_fingerprint(..., rules_digest)`. The digest is a
  sha256 of the canonical JSON of the html-phase rules, so editing a rule
  re-analyses pages, and unchanged rules keep the reuse.
- **Result:** `custom_rules`: a list of `{rule_id, name, severity,
  description, pages_checked, pages_failed, example_urls[≤5]}`, computed after
  the crawl from `all_page_issues` and which pages each rule applied to. It's
  added to `SUMMARY_FIELDS`, so it's stored in `summary_json`; no new results
  table.

### 4. API: `app/api/rules.py`

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/projects/{id}/rules` | `{items: [rule + description]}` |
| POST | `/api/projects/{id}/rules` | 201; 409 at 50 rules; 422 invalid |
| PATCH | `/api/rules/{id}` | partial (name, enabled, severity, message, url_pattern, check) |
| DELETE | `/api/rules/{id}` | 204 |
| POST | `/api/projects/{id}/rules/test` | `{rule, url}` → `{passed, observed, issue, applies}` |
| GET | `/api/audits/{id}/custom-rules` | `{audit_id, items: summary}` from `summary_json.custom_rules` (empty for older audits) |

- **The test endpoint:**
  - The URL's `project_domain` must equal the project's domain (400
    otherwise).
  - It runs one fetch with `Crawler._fetch`, then `analyze_page` with just
    that rule.
  - `observed` is the value the rule looked at: the field value, the
    selector match count, or whether the text was found.
  - A fetch failure is 502 with the reason.
- 404 for an unknown project or rule. 503 when the central DB is down, as in
  the other routers.

### 5. UI

- **Types:** `RuleCheck`, `CustomRule`, `RuleTestResult`, `RuleSummary`.
- **Service:** `Platform.listRules`, `createRule`, `updateRule`,
  `deleteRule`, `testRule`.
- **Project tabs:** "Custom Rules" (`/projects/[id]/rules`), added to
  `TABS` in `components/platform/project-tabs.tsx`.
- **Rules page:**
  - **List:** name, description, scope, severity pill (icon + text),
    enabled switch, Edit, Delete, and "Last audit: failed on N of M pages"
    (from `GET /api/audits/{latest}/custom-rules`).
  - **Builder form:** check type → field/scope/selector → operator (filtered
    by kind) → value, plus URL pattern, severity, name and message. A "Test
    on a URL" input shows pass/fail, the observed value and whether the rule
    applies to that URL. Save / Cancel.
  - **Empty state:** "No rules yet", with "Add an example rule" (title is not
    empty, warning).
- **Site Audit tab:** a "Custom rules" section for the selected audit (failed
  / checked per rule, example URLs).
- Rule failures already appear in the report's issue lists.

## Error handling

| Case | Result |
| --- | --- |
| Invalid rule | 422 with the reason (field/op mismatch, bad selector, missing value) |
| 51st rule | 409 |
| Test URL on another domain | 400 |
| Test fetch fails | 502 with the reason |
| Rules can't be loaded at audit start | audit runs without custom rules, logged |
| A rule throws while evaluating a page | that rule is skipped for that page, logged, and the page is still audited |

## Testing

- **Engine:** every op on a text field and a number field, text contains/not
  (visible/html, case), selector ops, the URL pattern (match, no match, no
  pattern), missing values, the issue shape and the stable code, `describe`
  wording, and `observe`.
- **Schema validation:** a field/op mismatch, a bad selector, a missing
  value, limits.
- **Pipeline:** rules loaded for the project, issues in `page_issues_detail`
  and the health score, the response-phase rules, the summary counts, a
  rules-digest change invalidating the cache while the same rules reuse it,
  and no project meaning no rules.
- **API:** CRUD, the 50 cap, 404s, the test endpoint with the fetch mocked
  (pass, fail with observed, other domain 400, fetch error 502), and the
  custom-rules summary endpoint.
- **Frontend:** list, the form's dependent inputs, test, toggle, delete,
  empty state, and the Site Audit section.
- **Live check:** three rules on books.toscrape.com (the title contains "All
  products" on `/catalogue/category/books_1/*`, product pages have
  `.price_color`, word count ≥ 500 expected to fail), and the UI at 1440 and
  390 px.

## Done when

A project's rules are created, tested and toggled in the UI. Every audit
evaluates them on every page, with the failures as issues of the chosen
severity and a per-rule summary. A rule edit re-checks pages, and tests and
docs are updated.

## Out of scope

- Header rules, regex, JavaScript-rendered DOM rules, rule templates or
  sharing between projects, and site-wide rules (e.g. "at least one page
  has X").
