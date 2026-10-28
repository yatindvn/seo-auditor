# Custom Rules Engine (Phase 5.4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Projects get user-defined, declarative rules (page fields, page
text, CSS selectors; optionally scoped to a URL path). Every audit evaluates
them on every page as ordinary issues of the chosen severity, with a per-rule
summary. A "Custom Rules" tab creates, tests and toggles them.

**Architecture:**
- `app/rules/` holds:
  - `schema.py`: pydantic validation of a rule and its check
  - `engine.py`: pure evaluation, description, observation and digest
  - `store.py`: loads a project's enabled rules
- The rules travel to the page workers inside `PagePayload`.
  - HTML-phase rules run at the end of `analyze_html`, using its parse, meta
    and text.
  - Response-phase rules (`status`, `response_time_ms`) run in
    `analyze_response`.
  - Each worker records which rule ids it checked in
    `meta["custom_rules_checked"]`, so the summary is exact.
- The page-cache fingerprint includes a digest of the HTML-phase rules.
- A CRUD and test API plus a Rules tab follow the existing platform
  patterns.

**Tech Stack:** Python, pydantic v2, soupsieve (bs4's selector engine), SQLAlchemy/Alembic, FastAPI; Next.js 14, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-29-custom-rules-design.md`

## Global Constraints

- **Check types:**
  - `field`, with text fields `title, meta_description, h1, canonical, meta_robots`, number fields `word_count, internal_links_count, external_links_count`, and response fields `status, response_time_ms`
  - `text` (scope `visible`|`html`, `contains`|`not_contains`, `case_sensitive` default false)
  - `selector` (`exists, not_exists, count_eq, count_gte, count_lte`)
- **Operators:**
  - text fields: `equals, not_equals, contains, not_contains, starts_with, ends_with, is_empty, is_not_empty, length_gte, length_lte`
  - number fields: `eq, gte, lte`
- **No headers, no regex, no code.** Selectors are compiled with soupsieve when saved (422 on error).
- **Limits:** name ≤ 80, message ≤ 200, url_pattern ≤ 200, value strings ≤ 200, numbers ≥ 0, and ≤ 50 rules per project (409).
- **URL pattern:** `fnmatch` on `urlsplit(url).path`.
- **Text semantics:** whitespace stripped. Text ops are case-insensitive except `equals`/`not_equals`. A missing value counts as `""`/`0`.
- **Issue:** code `CUSTOM_<id>`, the rule's severity, message `"{name}: {message}"` (just `"{name}: {description}"` when the message is empty), plus `"rule_id"` and `"source": "custom"`.
- **Never fatal:** HTML-phase rules only run when the page has HTML. A rule that raises is skipped for that page and logged. Rules failing to load means none are applied.
- **Test endpoint:** the URL must be on the project's domain (400). A fetch failure is 502.
- **Tests:** no network. Run the full backend suite before each commit.

---

### Task 1: Schema and engine

**Files:**
- Create: `apps/backend/app/rules/__init__.py`, `apps/backend/app/rules/schema.py`, `apps/backend/app/rules/engine.py`
- Test: `apps/backend/tests/test_rules_engine.py`

**Interfaces:**
- Produces:
  - `schema.RuleIn` (name, enabled=True, severity="warning", message="", url_pattern=None, check)
  - `schema.RulePatch`
  - `schema.validate_rule(data: dict) -> dict`, which raises `RuleError(str)`
  - `schema.TEXT_FIELDS`, `NUMBER_FIELDS`, `RESPONSE_FIELDS`
  - `engine.PageFacts(url, meta={}, text="", html="", soup=None, status=None, response_time_ms=None)`
  - `engine.phase_of(check) -> "html"|"response"`
  - `engine.applies(rule, url) -> bool`
  - `engine.observe(check, facts)`
  - `engine.passes(check, facts) -> bool`
  - `engine.evaluate(rules, facts, phase) -> Tuple[List[issue], List[int]]`
  - `engine.describe(check) -> str`
  - `engine.rules_digest(rules) -> str`
  - `engine.summarize(rules, checked_by_url, all_page_issues) -> List[dict]`
  - A rule dict is `{id, name, severity, message, url_pattern, check}`.

- [ ] **Step 1: Write the failing test**

```python
"""Custom rules: validation, evaluation, description and summary."""

import pytest
from bs4 import BeautifulSoup

from app.rules.engine import PageFacts, applies, describe, evaluate, observe, passes, phase_of, rules_digest, summarize
from app.rules.schema import RuleError, validate_rule

HTML = ("<html><head><title> Shop | Brand </title></head><body><nav class='breadcrumb'></nav>"
        "<p class='price_color'>£10</p><p class='price_color'>£12</p>"
        "<script type='application/ld+json'>{}</script></body></html>")


def _facts(**over):
    base = dict(url="https://a.com/products/x", html=HTML, soup=BeautifulSoup(HTML, "html.parser"),
                text="Shop now. Free shipping on everything.",
                meta={"title": " Shop | Brand ", "meta_description": None, "h1": "Shop", "word_count": 120,
                      "canonical": "https://a.com/products/x", "meta_robots": "index,follow",
                      "internal_links_count": 30, "external_links_count": 2},
                status=200, response_time_ms=850.0)
    base.update(over)
    return PageFacts(**base)


def _rule(check, rid=1, **over):
    return {"id": rid, "name": "My rule", "severity": "warning", "message": "fix it",
            "url_pattern": None, "check": check, **over}


@pytest.mark.parametrize("op, value, expected", [
    ("equals", "Shop | Brand", True), ("equals", "shop | brand", False), ("not_equals", "Other", True),
    ("contains", "| BRAND", True), ("not_contains", "brand", False), ("starts_with", "shop", True),
    ("ends_with", "brand", True), ("is_empty", None, False), ("is_not_empty", None, True),
    ("length_gte", 12, True), ("length_lte", 11, False),
])
def test_text_field_ops(op, value, expected):
    assert passes({"type": "field", "field": "title", "op": op, "value": value}, _facts()) is expected


def test_missing_text_field_is_empty():
    assert passes({"type": "field", "field": "meta_description", "op": "is_empty"}, _facts()) is True
    assert passes({"type": "field", "field": "meta_description", "op": "contains", "value": "x"}, _facts()) is False


@pytest.mark.parametrize("field, op, value, expected", [
    ("word_count", "gte", 300, False), ("word_count", "lte", 120, True), ("word_count", "eq", 120, True),
    ("internal_links_count", "gte", 10, True), ("status", "eq", 200, True), ("response_time_ms", "lte", 500, False),
])
def test_number_field_ops(field, op, value, expected):
    assert passes({"type": "field", "field": field, "op": op, "value": value}, _facts()) is expected


def test_text_checks():
    assert passes({"type": "text", "scope": "visible", "op": "contains", "value": "FREE SHIPPING"}, _facts()) is True
    assert passes({"type": "text", "scope": "visible", "op": "contains", "value": "FREE SHIPPING",
                   "case_sensitive": True}, _facts()) is False
    assert passes({"type": "text", "scope": "html", "op": "contains", "value": "ld+json"}, _facts()) is True
    assert passes({"type": "text", "scope": "visible", "op": "not_contains", "value": "lorem ipsum"}, _facts()) is True


def test_selector_checks_and_observe():
    sel = lambda op, value=None: {"type": "selector", "selector": ".price_color", "op": op, "value": value}
    assert passes(sel("exists"), _facts()) and not passes(sel("not_exists"), _facts())
    assert passes(sel("count_eq", 2), _facts()) and passes(sel("count_lte", 2), _facts())
    assert not passes(sel("count_gte", 3), _facts())
    assert observe(sel("exists"), _facts()) == 2
    assert observe({"type": "field", "field": "title", "op": "is_empty"}, _facts()) == "Shop | Brand"
    assert observe({"type": "text", "scope": "visible", "op": "contains", "value": "shipping"}, _facts()) is True


def test_url_pattern_scopes_rules():
    assert applies(_rule({}, url_pattern="/products/*"), "https://a.com/products/x?y=1")
    assert not applies(_rule({}, url_pattern="/blog/*"), "https://a.com/products/x")
    assert applies(_rule({}, url_pattern=None), "https://a.com/anything")


def test_phases():
    assert phase_of({"type": "field", "field": "status", "op": "eq", "value": 200}) == "response"
    assert phase_of({"type": "field", "field": "title", "op": "is_empty"}) == "html"
    assert phase_of({"type": "selector", "selector": "a", "op": "exists"}) == "html"


def test_evaluate_returns_issues_and_checked_ids():
    rules = [_rule({"type": "field", "field": "word_count", "op": "gte", "value": 300}, rid=7, severity="critical"),
             _rule({"type": "selector", "selector": "nav.breadcrumb", "op": "exists"}, rid=8),
             _rule({"type": "field", "field": "title", "op": "is_empty"}, rid=9, url_pattern="/blog/*"),
             _rule({"type": "field", "field": "status", "op": "eq", "value": 404}, rid=10)]
    issues, checked = evaluate(rules, _facts(), "html")
    assert checked == [7, 8]
    assert issues == [{"severity": "critical", "code": "CUSTOM_7", "message": "My rule: fix it",
                       "rule_id": 7, "source": "custom"}]
    issues, checked = evaluate(rules, _facts(), "response")
    assert checked == [10] and issues[0]["code"] == "CUSTOM_10"


def test_html_rules_skip_pages_without_html_and_bad_rules_are_skipped():
    rule = _rule({"type": "field", "field": "title", "op": "is_not_empty"})
    assert evaluate([rule], _facts(html="", soup=None), "html") == ([], [])
    broken = _rule({"type": "selector", "selector": "a", "op": "count_eq", "value": "not-a-number"}, rid=3)
    assert evaluate([broken], _facts(), "html") == ([], [])


def test_empty_message_falls_back_to_the_description():
    issues, _ = evaluate([_rule({"type": "field", "field": "word_count", "op": "gte", "value": 300}, message="")],
                         _facts(), "html")
    assert issues[0]["message"] == "My rule: Word count ≥ 300"


@pytest.mark.parametrize("check, text", [
    ({"type": "field", "field": "title", "op": "contains", "value": "| Brand"}, "Title contains '| Brand'"),
    ({"type": "field", "field": "meta_description", "op": "is_empty"}, "Meta description is empty"),
    ({"type": "field", "field": "word_count", "op": "gte", "value": 300}, "Word count ≥ 300"),
    ({"type": "field", "field": "title", "op": "length_lte", "value": 60}, "Title length ≤ 60"),
    ({"type": "text", "scope": "visible", "op": "not_contains", "value": "lorem"}, "Page text doesn't contain 'lorem'"),
    ({"type": "text", "scope": "html", "op": "contains", "value": "gtag("}, "HTML contains 'gtag('"),
    ({"type": "selector", "selector": "h1", "op": "count_eq", "value": 1}, "Exactly 1 × h1"),
    ({"type": "selector", "selector": ".x", "op": "not_exists"}, "No .x"),
    ({"type": "selector", "selector": ".x", "op": "exists"}, "Has .x"),
])
def test_describe(check, text):
    assert describe(check) == text


def test_digest_covers_only_html_rules_and_is_order_stable():
    a = _rule({"type": "field", "field": "title", "op": "is_empty"}, rid=1)
    b = _rule({"type": "field", "field": "status", "op": "eq", "value": 200}, rid=2)
    assert rules_digest([a, b]) == rules_digest([a]) == rules_digest([dict(reversed(list(a.items())))])
    assert rules_digest([a]) != rules_digest([{**a, "check": {**a["check"], "op": "is_not_empty"}}])
    assert rules_digest([]) == ""


def test_summarize_counts_checked_and_failed_pages():
    rule = _rule({"type": "field", "field": "title", "op": "is_empty"}, rid=5)
    checked = {"https://a.com/1": [5], "https://a.com/2": [5], "https://a.com/3": []}
    issues = {"https://a.com/2": [{"code": "CUSTOM_5", "rule_id": 5, "source": "custom", "severity": "warning", "message": "m"}]}
    assert summarize([rule], checked, issues) == [{
        "rule_id": 5, "name": "My rule", "severity": "warning", "description": "Title is empty",
        "pages_checked": 2, "pages_failed": 1, "example_urls": ["https://a.com/2"]}]


def test_validation_accepts_good_rules_and_normalises_numbers():
    rule = validate_rule({"name": "Long enough", "severity": "info",
                          "check": {"type": "field", "field": "word_count", "op": "gte", "value": "300"}})
    assert rule["check"]["value"] == 300 and rule["enabled"] is True and rule["url_pattern"] is None


@pytest.mark.parametrize("check, needle", [
    ({"type": "field", "field": "word_count", "op": "contains", "value": "x"}, "not valid for word_count"),
    ({"type": "field", "field": "title", "op": "contains"}, "needs a value"),
    ({"type": "field", "field": "title", "op": "length_gte", "value": "abc"}, "must be a whole number"),
    ({"type": "field", "field": "word_count", "op": "gte", "value": -1}, "must be ≥ 0"),
    ({"type": "selector", "selector": "div[", "op": "exists"}, "Invalid CSS selector"),
    ({"type": "selector", "selector": "div", "op": "count_eq"}, "needs a value"),
    ({"type": "text", "scope": "visible", "op": "contains", "value": "x" * 201}, "at most 200"),
    ({"type": "headers", "name": "X"}, "check"),
])
def test_validation_rejects_bad_rules(check, needle):
    with pytest.raises(RuleError) as err:
        validate_rule({"name": "r", "check": check})
    assert needle in str(err.value)


def test_validation_limits_names():
    with pytest.raises(RuleError):
        validate_rule({"name": "x" * 81, "check": {"type": "field", "field": "title", "op": "is_empty"}})
```

- [ ] **Step 2: Run and watch it fail**

Run: `cd apps/backend && python -m pytest tests/test_rules_engine.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.rules'`

- [ ] **Step 3: `app/rules/__init__.py`**

```python
"""Custom rules: user-defined, declarative checks stored per project and
evaluated on every page of every audit."""
```

- [ ] **Step 4: `app/rules/schema.py`**

```python
"""Validation of a custom rule. Declarative only: no regex, no code, no
headers -- nothing a rule can do may hang or harm the server."""

from __future__ import annotations

from typing import Annotated, Any, Dict, Literal, Optional, Union

import soupsieve
from pydantic import BaseModel, Field, ValidationError, model_validator

TEXT_FIELDS = ("title", "meta_description", "h1", "canonical", "meta_robots")
NUMBER_FIELDS = ("word_count", "internal_links_count", "external_links_count")
RESPONSE_FIELDS = ("status", "response_time_ms")
TEXT_OPS = ("equals", "not_equals", "contains", "not_contains", "starts_with", "ends_with",
            "is_empty", "is_not_empty", "length_gte", "length_lte")
NUMBER_OPS = ("eq", "gte", "lte")
VALUELESS_OPS = ("is_empty", "is_not_empty", "exists", "not_exists")
MAX_TEXT = 200


class RuleError(ValueError):
    """A rule that can't be saved, with a message fit for the user."""


def _whole_number(value: Any, what: str) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a whole number")
    if number != int(number):
        raise ValueError(f"{what} must be a whole number")
    if number < 0:
        raise ValueError(f"{what} must be ≥ 0")
    return int(number)


def _number(value: Any, what: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number")
    if number < 0:
        raise ValueError(f"{what} must be ≥ 0")
    return int(number) if number == int(number) else number


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("needs a value")
    if len(value) > MAX_TEXT:
        raise ValueError(f"value must be at most {MAX_TEXT} characters")
    return value


class FieldCheck(BaseModel):
    type: Literal["field"]
    field: Literal[TEXT_FIELDS + NUMBER_FIELDS + RESPONSE_FIELDS]  # type: ignore[valid-type]
    op: str
    value: Optional[Union[int, float, str]] = None

    @model_validator(mode="after")
    def _check(self):
        text_field = self.field in TEXT_FIELDS
        allowed = TEXT_OPS if text_field else NUMBER_OPS
        if self.op not in allowed:
            raise ValueError(f"'{self.op}' is not valid for {self.field} (use one of: {', '.join(allowed)})")
        if self.op in VALUELESS_OPS:
            self.value = None
        elif self.value is None or self.value == "":
            raise ValueError(f"'{self.op}' needs a value")
        elif self.op in ("length_gte", "length_lte"):
            self.value = _whole_number(self.value, "value")
        elif not text_field:
            self.value = _number(self.value, "value")
        else:
            self.value = _text(self.value)
        return self


class TextCheck(BaseModel):
    type: Literal["text"]
    scope: Literal["visible", "html"] = "visible"
    op: Literal["contains", "not_contains"]
    value: str
    case_sensitive: bool = False

    @model_validator(mode="after")
    def _check(self):
        self.value = _text(self.value)
        return self


class SelectorCheck(BaseModel):
    type: Literal["selector"]
    selector: str = Field(min_length=1, max_length=MAX_TEXT)
    op: Literal["exists", "not_exists", "count_eq", "count_gte", "count_lte"]
    value: Optional[Union[int, str]] = None

    @model_validator(mode="after")
    def _check(self):
        try:
            soupsieve.compile(self.selector)
        except Exception as exc:
            raise ValueError(f"Invalid CSS selector: {exc}")
        if self.op in VALUELESS_OPS:
            self.value = None
        elif self.value is None or self.value == "":
            raise ValueError(f"'{self.op}' needs a value")
        else:
            self.value = _whole_number(self.value, "value")
        return self


Check = Annotated[Union[FieldCheck, TextCheck, SelectorCheck], Field(discriminator="type")]


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    severity: Literal["critical", "warning", "info"] = "warning"
    message: str = Field(default="", max_length=MAX_TEXT)
    url_pattern: Optional[str] = Field(default=None, max_length=MAX_TEXT)
    check: Check


def _readable(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        where = ".".join(str(p) for p in error.get("loc", ()) if not isinstance(p, int))
        message = str(error.get("msg", "")).removeprefix("Value error, ")
        parts.append(f"{where}: {message}" if where else message)
    return "; ".join(parts)


def validate_rule(data: Dict[str, Any]) -> Dict[str, Any]:
    """A clean rule dict (name, enabled, severity, message, url_pattern, check),
    or RuleError with a readable reason."""
    try:
        rule = RuleIn.model_validate(data)
    except ValidationError as exc:
        raise RuleError(_readable(exc))
    out = rule.model_dump()
    out["url_pattern"] = (out["url_pattern"] or "").strip() or None
    return out
```

- [ ] **Step 5: `app/rules/engine.py`**

```python
"""Evaluating custom rules on one page. Pure: everything a rule may look at
arrives in PageFacts, and rules are plain dicts (they travel to worker
processes)."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import urllib.parse as up
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.auditor.checks import issue
from app.rules.schema import RESPONSE_FIELDS, TEXT_FIELDS

logger = logging.getLogger(__name__)

LABELS = {
    "title": "Title", "meta_description": "Meta description", "h1": "H1", "canonical": "Canonical",
    "meta_robots": "Meta robots", "word_count": "Word count", "internal_links_count": "Internal links",
    "external_links_count": "External links", "status": "Status code", "response_time_ms": "Response time (ms)",
}
_SYMBOL = {"eq": "=", "gte": "≥", "lte": "≤", "length_gte": "≥", "length_lte": "≤"}


@dataclass
class PageFacts:
    url: str
    meta: Dict[str, Any] = field(default_factory=dict)
    text: str = ""
    html: str = ""
    soup: Any = None
    status: Optional[int] = None
    response_time_ms: Optional[float] = None


def phase_of(check: Dict[str, Any]) -> str:
    return "response" if check.get("type") == "field" and check.get("field") in RESPONSE_FIELDS else "html"


def applies(rule: Dict[str, Any], url: str) -> bool:
    pattern = rule.get("url_pattern")
    return not pattern or fnmatch.fnmatchcase(up.urlsplit(url).path or "/", pattern)


def _field_value(name: str, facts: PageFacts) -> Any:
    if name == "status":
        return facts.status or 0
    if name == "response_time_ms":
        return facts.response_time_ms or 0
    value = facts.meta.get(name)
    if name in TEXT_FIELDS:
        return (value if isinstance(value, str) else ("" if value is None else str(value))).strip()
    return value or 0


def observe(check: Dict[str, Any], facts: PageFacts) -> Any:
    """What the rule looks at on this page: a field value, a match count, or
    whether the text was found."""
    kind = check["type"]
    if kind == "field":
        return _field_value(check["field"], facts)
    if kind == "selector":
        return len(facts.soup.select(check["selector"])) if facts.soup is not None else 0
    haystack = facts.text if check.get("scope", "visible") == "visible" else facts.html
    needle = check["value"]
    if not check.get("case_sensitive"):
        haystack, needle = haystack.lower(), needle.lower()
    return needle in (haystack or "")


def passes(check: Dict[str, Any], facts: PageFacts) -> bool:
    op, value, seen = check["op"], check.get("value"), observe(check, facts)
    if check["type"] == "text":
        return seen if op == "contains" else not seen
    if check["type"] == "selector":
        return {"exists": seen > 0, "not_exists": seen == 0, "count_eq": seen == int(value),
                "count_gte": seen >= int(value), "count_lte": seen <= int(value)}[op]
    if check["field"] in TEXT_FIELDS:
        text, low = seen, seen.lower()
        if op in ("length_gte", "length_lte"):
            return len(text) >= int(value) if op == "length_gte" else len(text) <= int(value)
        if op in ("is_empty", "is_not_empty"):
            return (text == "") is (op == "is_empty")
        target = str(value).strip()
        return {"equals": text == target, "not_equals": text != target,
                "contains": target.lower() in low, "not_contains": target.lower() not in low,
                "starts_with": low.startswith(target.lower()), "ends_with": low.endswith(target.lower())}[op]
    number, target = float(seen), float(value)
    return {"eq": number == target, "gte": number >= target, "lte": number <= target}[op]


def describe(check: Dict[str, Any]) -> str:
    kind, op, value = check.get("type"), check.get("op"), check.get("value")
    if kind == "selector":
        sel = check.get("selector", "")
        return {"exists": f"Has {sel}", "not_exists": f"No {sel}", "count_eq": f"Exactly {value} × {sel}",
                "count_gte": f"At least {value} × {sel}", "count_lte": f"At most {value} × {sel}"}.get(op, sel)
    if kind == "text":
        where = "Page text" if check.get("scope", "visible") == "visible" else "HTML"
        verb = "contains" if op == "contains" else "doesn't contain"
        return f"{where} {verb} '{value}'"
    label = LABELS.get(check.get("field"), str(check.get("field")))
    if op in ("is_empty", "is_not_empty"):
        return f"{label} {'is empty' if op == 'is_empty' else 'is not empty'}"
    if op in ("length_gte", "length_lte"):
        return f"{label} length {_SYMBOL[op]} {value}"
    if op in _SYMBOL:
        return f"{label} {_SYMBOL[op]} {value}"
    words = {"equals": "is", "not_equals": "is not", "contains": "contains", "not_contains": "doesn't contain",
             "starts_with": "starts with", "ends_with": "ends with"}
    return f"{label} {words.get(op, op)} '{value}'"


def _issue(rule: Dict[str, Any]) -> Dict[str, Any]:
    found = issue(rule["severity"], f"CUSTOM_{rule['id']}",
                  f"{rule['name']}: {rule.get('message') or describe(rule['check'])}")
    found.update(rule_id=rule["id"], source="custom")
    return found


def evaluate(rules: List[Dict[str, Any]], facts: PageFacts, phase: str) -> Tuple[List[Dict[str, Any]], List[int]]:
    """The issues this page raises in one phase, and the ids of the rules that
    were checked. HTML rules need HTML; a rule that raises is skipped."""
    if phase == "html" and not facts.html:
        return [], []
    issues, checked = [], []
    for rule in rules:
        if phase_of(rule["check"]) != phase or not applies(rule, facts.url):
            continue
        try:
            ok = passes(rule["check"], facts)
        except Exception as exc:
            logger.warning("Custom rule %s failed on %s: %s", rule.get("id"), facts.url, exc)
            continue
        checked.append(rule["id"])
        if not ok:
            issues.append(_issue(rule))
    return issues, checked


def rules_digest(rules: List[Dict[str, Any]]) -> str:
    """Changes when the HTML-phase rules change -- part of the page-cache
    fingerprint, so editing a rule re-checks pages."""
    html_rules = sorted((r for r in rules if phase_of(r["check"]) == "html"), key=lambda r: r["id"])
    if not html_rules:
        return ""
    return hashlib.sha256(json.dumps(html_rules, sort_keys=True, default=str).encode()).hexdigest()


def summarize(rules: List[Dict[str, Any]], checked_by_url: Dict[str, List[int]],
              all_page_issues: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out = []
    for rule in rules:
        checked = [u for u, ids in checked_by_url.items() if rule["id"] in (ids or [])]
        failed = sorted(u for u, issues in all_page_issues.items()
                        if any(i.get("source") == "custom" and i.get("rule_id") == rule["id"] for i in issues))
        out.append({"rule_id": rule["id"], "name": rule["name"], "severity": rule["severity"],
                    "description": describe(rule["check"]), "pages_checked": len(checked),
                    "pages_failed": len(failed), "example_urls": failed[:5]})
    return out
```

- [ ] **Step 6: Run and pass, full suite, then commit**

```bash
python -m pytest tests/test_rules_engine.py -q
python -m pytest -q
git add apps/backend/app/rules apps/backend/tests/test_rules_engine.py
git commit -m "feat(rules): declarative rule schema and pure evaluation engine"
```

---

### Task 2: Storage and the rule loader

**Files:**
- Create: `apps/backend/alembic/versions/0007_custom_rules.py`, `apps/backend/app/rules/store.py`, `apps/backend/tests/test_rules_store.py`
- Modify: `apps/backend/app/db/models.py`, `apps/backend/tests/test_db_schema.py`

**Interfaces:**
- Produces:
  - Model `CustomRule`
  - `store.rule_dict(row) -> dict` (the engine's rule dict)
  - `store.load_enabled_rules(url, factory=None) -> List[dict]`, which never raises

- [ ] **Step 1: Write the failing test**

```python
"""Loading a project's rules for an audit."""

from app.db.engine import get_session_factory
from app.db.models import CustomRule, Project
from app.rules import store


def _seed():
    with get_session_factory().begin() as s:
        project = Project(name="shop.com", domain="shop.com"); s.add(project); s.flush()
        s.add_all([
            CustomRule(project_id=project.id, name="b", severity="info", message="", url_pattern=None,
                       check_json={"type": "field", "field": "title", "op": "is_empty"}),
            CustomRule(project_id=project.id, name="off", enabled=False, severity="info", message="",
                       check_json={"type": "field", "field": "h1", "op": "is_empty"}),
            CustomRule(project_id=project.id, name="a", severity="critical", message="m", url_pattern="/p/*",
                       check_json={"type": "selector", "selector": "h1", "op": "exists"}),
        ])


def test_loads_enabled_rules_for_the_audited_site_in_id_order():
    _seed()
    rules = store.load_enabled_rules("https://www.shop.com/start")
    assert [r["name"] for r in rules] == ["b", "a"]
    assert rules[1] == {"id": rules[1]["id"], "name": "a", "severity": "critical", "message": "m",
                        "url_pattern": "/p/*", "check": {"type": "selector", "selector": "h1", "op": "exists"}}


def test_no_project_means_no_rules():
    assert store.load_enabled_rules("https://unknown.example/") == []


def test_a_database_failure_means_no_rules():
    def broken():
        raise RuntimeError("db down")
    assert store.load_enabled_rules("https://shop.com/", factory=broken) == []
```

Add `"custom_rules"` to `TABLES` in `tests/test_db_schema.py`.

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_rules_store.py -q`
Expected: FAIL with `ImportError: cannot import name 'CustomRule'`

- [ ] **Step 3: Model** (append to `app/db/models.py`)

```python
class CustomRule(Base):
    """A user-defined check, evaluated on every page of the project's audits (Phase 5.4)."""
    __tablename__ = "custom_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(String(200), default="")
    url_pattern: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    check_json: Mapped[Dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
```

- [ ] **Step 4: Migration `alembic/versions/0007_custom_rules.py`**

```python
"""custom rules

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-29 14:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('custom_rules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('message', sa.String(length=200), nullable=False),
    sa.Column('url_pattern', sa.String(length=200), nullable=True),
    sa.Column('check_json', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_custom_rules_project_id'), 'custom_rules', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_custom_rules_project_id'), table_name='custom_rules')
    op.drop_table('custom_rules')
```

Check how 0002 declared its boolean `server_default`. If the models-vs-migration test complains about the server default, match exactly what `Keyword.enabled` uses in the model and in 0002.

- [ ] **Step 5: `app/rules/store.py`**

```python
"""A project's enabled rules, as the plain dicts the engine and the page
workers use."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from sqlalchemy import select

from app.db.engine import get_session_factory
from app.db.models import CustomRule, Project
from app.db.projects import project_domain

logger = logging.getLogger(__name__)


def rule_dict(row: CustomRule) -> Dict[str, Any]:
    return {"id": row.id, "name": row.name, "severity": row.severity, "message": row.message or "",
            "url_pattern": row.url_pattern, "check": dict(row.check_json or {})}


def load_enabled_rules(url: str, factory=None) -> List[Dict[str, Any]]:
    """The audited site's enabled rules, oldest first. Never raises: an audit
    without its custom rules beats no audit."""
    try:
        factory = factory or get_session_factory()
        with factory() as session:
            project_id = session.scalar(select(Project.id).where(Project.domain == project_domain(url)))
            if project_id is None:
                return []
            rows = session.scalars(select(CustomRule).where(
                CustomRule.project_id == project_id, CustomRule.enabled.is_(True)).order_by(CustomRule.id)).all()
            return [rule_dict(r) for r in rows]
    except Exception as exc:
        logger.error("Custom rules not loaded for %s: %s", url, exc, exc_info=exc)
        return []
```

- [ ] **Step 6: Run and pass, full suite, then commit**

```bash
python -m pytest tests/test_rules_store.py tests/test_db_schema.py -q
python -m pytest -q
git add apps/backend/app/db/models.py apps/backend/alembic/versions/0007_custom_rules.py apps/backend/app/rules/store.py apps/backend/tests/test_rules_store.py apps/backend/tests/test_db_schema.py
git commit -m "feat(rules): custom_rules table (migration 0007) and loader"
```

---

### Task 3: Rules inside the audit pipeline

**Files:**
- Modify:
  - `apps/backend/app/services/page_pipeline.py`
  - `apps/backend/app/models/page_cache.py`
  - `apps/backend/app/services/audit_service.py`
  - `apps/backend/app/services/summary_fields.py`
- Test: `apps/backend/tests/test_rules_pipeline.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - `PagePayload.custom_rules: List[dict] = []`
  - `meta["custom_rules_checked"]: List[int]`
  - `analyzer_fingerprint(..., rules_digest: str = "")`
  - Result key `custom_rules` (the summary list), also in `SUMMARY_FIELDS`

- [ ] **Step 1: Write the failing test**

```python
"""Custom rules in an audit: loaded for the project, evaluated in the page
workers, counted in the summary, and part of the page-cache fingerprint."""

from app.db.engine import get_session_factory
from app.db.models import CustomRule, Project
from app.models import page_cache
from app.services import audit_service, page_pipeline

from test_audit_service_crawler_registry import FakeCrawler


def _rules(*checks):
    with get_session_factory().begin() as s:
        project = Project(name="example.com", domain="example.com"); s.add(project); s.flush()
        for i, (check, severity, pattern) in enumerate(checks):
            s.add(CustomRule(project_id=project.id, name=f"rule {i}", severity=severity, message="msg",
                             url_pattern=pattern, check_json=check))


def _run():
    return audit_service._build_audit_result("https://example.com/", FakeCrawler(),
                                             progress_callback=None, event_callback=None)


def test_failed_rules_are_issues_with_their_severity_and_a_summary():
    _rules(({"type": "field", "field": "word_count", "op": "gte", "value": 500}, "critical", None),
           ({"type": "text", "scope": "visible", "op": "contains", "value": "espresso"}, "warning", None),
           ({"type": "field", "field": "status", "op": "eq", "value": 404}, "info", None),
           ({"type": "selector", "selector": "h1", "op": "not_exists"}, "warning", "/blog/*"))
    result = _run()
    issues = [i for i in result["page_issues_detail"]["https://example.com/"] if i.get("source") == "custom"]
    assert sorted((i["severity"], i["message"]) for i in issues) == [
        ("critical", "rule 0: msg"), ("info", "rule 2: msg")]
    summary = {s["name"]: s for s in result["custom_rules"]}
    assert summary["rule 0"]["pages_failed"] == 1 and summary["rule 0"]["pages_checked"] == 1
    assert summary["rule 1"]["pages_failed"] == 0 and summary["rule 1"]["pages_checked"] == 1
    assert summary["rule 2"]["pages_checked"] == 1
    assert summary["rule 3"]["pages_checked"] == 0          # scoped to /blog/*
    assert result["executive_summary"]["health_score"]["critical_issues"] >= 1


def test_no_project_no_rules():
    result = _run()
    assert result["custom_rules"] == []


def test_the_fingerprint_follows_the_rules():
    base = page_cache.analyzer_fingerprint(True, None, False)
    assert page_cache.analyzer_fingerprint(True, None, False, rules_digest="") == base
    assert page_cache.analyzer_fingerprint(True, None, False, rules_digest="abc") != base


def test_workers_get_the_rules_in_the_payload():
    payload = page_pipeline.PagePayload(
        url="https://example.com/", final_url="https://example.com/", status_code=200, headers={},
        html="<html><head><title>T</title></head><body><h1>x</h1></body></html>",
        custom_rules=[{"id": 4, "name": "n", "severity": "warning", "message": "", "url_pattern": None,
                       "check": {"type": "selector", "selector": "h1", "op": "not_exists"}}])
    analysis = page_pipeline.analyze_page(payload)
    assert [i["code"] for i in analysis.issues if i.get("source") == "custom"] == ["CUSTOM_4"]
    assert analysis.meta["custom_rules_checked"] == [4]
```

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_rules_pipeline.py -q`
Expected: FAIL (`unexpected keyword argument 'custom_rules'`, …)

- [ ] **Step 3: Page pipeline** (`app/services/page_pipeline.py`)

1. Import: `from app.rules import engine as rules_engine`.
2. Add `custom_rules: List[Dict[str, Any]] = field(default_factory=list)` as the last field of `PagePayload`.
3. In `analyze_html`, right before `return HtmlAnalysis(`, add:

```python
    # Custom rules (Phase 5.4), on this parse: cached with the HTML half, so a
    # rule edit changes the analyzer fingerprint and re-analyses the page.
    rule_issues, rules_checked = rules_engine.evaluate(payload.custom_rules, rules_engine.PageFacts(
        url=page_url, meta=meta, text=text, html=payload.html or "", soup=soup), "html")
    issues += rule_issues
    meta["custom_rules_checked"] = rules_checked
```

4. In `analyze_response`, before `meta = {**html_part.meta, ...}`, add the code below, then change the `meta = {...}` line to `meta = {**html_part.meta, "performance": weight, "security_headers": security_headers, "custom_rules_checked": [*html_part.meta.get("custom_rules_checked", []), *response_checked]}`.

```python
    response_issues, response_checked = rules_engine.evaluate(payload.custom_rules, rules_engine.PageFacts(
        url=payload.url, status=payload.status_code, response_time_ms=payload.response_time_ms), "response")
    issues += response_issues
```

- [ ] **Step 4: Fingerprint** (`app/models/page_cache.py`)

Add the parameter `rules_digest: str = ""` to `analyzer_fingerprint`. In the `options` dict, add `"rules": rules_digest` only when it's non-empty, so the fingerprint is unchanged for audits without rules (existing caches stay valid):

```python
    options = {
        "keyword_analysis": bool(enable_keyword_analysis),
        "target_keywords": sorted(target_keywords or []),
        "signature": bool(compute_signature),
    }
    if rules_digest:
        options["rules"] = rules_digest
    digest.update(json.dumps(options, sort_keys=True).encode())
```

- [ ] **Step 5: Audit service** (`app/services/audit_service.py`)

1. Imports: `from app.rules import store as rules_store` and `from app.rules.engine import rules_digest, summarize as summarize_rules`.
2. In `_build_audit_result`, before the `cache = page_cache.PageCache.open(` line, add the line below. Then pass `rules_digest=rules_digest(custom_rules)` as the fourth argument of `analyzer_fingerprint(...)`.

```python
    # The audited site's custom rules travel to the page workers in each payload.
    custom_rules = rules_store.load_enabled_rules(url)
```

3. In `on_page`, add `custom_rules=custom_rules,` to the `page_pipeline.PagePayload(` call.
4. After the browser-pass block (before `duplicates = analysis.find_duplicates(`), add:

```python
    rules_summary = summarize_rules(
        custom_rules,
        {u: (a.meta or {}).get("custom_rules_checked", []) for u, a in analyses.items() if a is not None and not a.failed},
        all_page_issues,
    ) if custom_rules else []
```

5. In `result_data`, after `"axe_version": ...`, add `"custom_rules": rules_summary,`.
6. In `app/services/summary_fields.py`, add `"custom_rules",` before `"note",`.

- [ ] **Step 6: Run and pass, full suite, then commit**

```bash
python -m pytest tests/test_rules_pipeline.py tests/test_page_cache.py tests/test_page_reuse.py -q
python -m pytest -q
git add apps/backend/app apps/backend/tests/test_rules_pipeline.py
git commit -m "feat(rules): evaluate custom rules on every page; summary per rule; cache follows rules"
```

---

### Task 4: Rules API

**Files:**
- Create: `apps/backend/app/api/rules.py`, `apps/backend/tests/test_rules_api.py`
- Modify: `apps/backend/app/main.py`

**Interfaces:**
- Produces (all under `/api`):
  - `GET/POST /projects/{id}/rules`
  - `PATCH/DELETE /rules/{id}`
  - `POST /projects/{id}/rules/test`
  - `GET /audits/{id}/custom-rules`
  - `fetch_page(url) -> PageResult` (module-level, so tests can patch it)
- A rule in JSON is `{id, project_id, name, enabled, severity, message, url_pattern, check, description, created_at, updated_at}`.

- [ ] **Step 1: Write the failing test**

```python
"""Custom rules over HTTP."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import rules as rules_api
from app.crawler.crawler import PageResult
from app.db.engine import get_session_factory
from app.db.models import Audit, Project
from app.main import app

TITLE = {"type": "field", "field": "title", "op": "contains", "value": "| Brand"}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project_id():
    with get_session_factory().begin() as s:
        p = Project(name="shop.com", domain="shop.com"); s.add(p); s.flush()
        return p.id


def test_crud(client, project_id):
    created = client.post(f"/api/projects/{project_id}/rules", json={"name": "Brand in title", "check": TITLE,
                                                                     "url_pattern": "/blog/*"})
    assert created.status_code == 201
    rule = created.json()
    assert rule["description"] == "Title contains '| Brand'" and rule["enabled"] is True and rule["severity"] == "warning"
    assert client.get(f"/api/projects/{project_id}/rules").json()["items"][0]["id"] == rule["id"]

    patched = client.patch(f"/api/rules/{rule['id']}", json={"enabled": False, "severity": "critical"}).json()
    assert patched["enabled"] is False and patched["severity"] == "critical" and patched["check"] == TITLE

    assert client.patch(f"/api/rules/{rule['id']}", json={"check": {"type": "selector", "selector": "div[", "op": "exists"}}).status_code == 422
    assert client.delete(f"/api/rules/{rule['id']}").status_code == 204
    assert client.get(f"/api/projects/{project_id}/rules").json()["items"] == []


def test_validation_errors_are_readable(client, project_id):
    bad = client.post(f"/api/projects/{project_id}/rules",
                      json={"name": "x", "check": {"type": "field", "field": "word_count", "op": "contains", "value": "a"}})
    assert bad.status_code == 422 and "not valid for word_count" in bad.json()["detail"]


def test_limits_and_404s(client, project_id, monkeypatch):
    monkeypatch.setattr(rules_api, "MAX_RULES", 1)
    assert client.post(f"/api/projects/{project_id}/rules", json={"name": "a", "check": TITLE}).status_code == 201
    assert client.post(f"/api/projects/{project_id}/rules", json={"name": "b", "check": TITLE}).status_code == 409
    assert client.post("/api/projects/9999/rules", json={"name": "a", "check": TITLE}).status_code == 404
    assert client.patch("/api/rules/9999", json={"enabled": False}).status_code == 404
    assert client.delete("/api/rules/9999").status_code == 404


def _page(html, status=200):
    return PageResult(url="https://shop.com/p", final_url="https://shop.com/p", status_code=status,
                      html=html, headers={"Content-Type": "text/html"}, content_type="text/html", response_time_ms=120)


def test_rule_test_endpoint(client, project_id, monkeypatch):
    monkeypatch.setattr(rules_api, "fetch_page", lambda url: _page("<html><head><title>Shop</title></head><body></body></html>"))
    body = client.post(f"/api/projects/{project_id}/rules/test",
                       json={"url": "https://www.shop.com/p", "rule": {"name": "Brand", "check": TITLE}}).json()
    assert body["applies"] is True and body["passed"] is False and body["observed"] == "Shop"
    assert body["issue"]["message"] == "Brand: Title contains '| Brand'"

    scoped = client.post(f"/api/projects/{project_id}/rules/test",
                         json={"url": "https://shop.com/p", "rule": {"name": "B", "check": TITLE, "url_pattern": "/blog/*"}}).json()
    assert scoped["applies"] is False and scoped["passed"] is None


def test_rule_test_guards(client, project_id, monkeypatch):
    rule = {"name": "Brand", "check": TITLE}
    assert client.post(f"/api/projects/{project_id}/rules/test", json={"url": "https://evil.com/", "rule": rule}).status_code == 400
    monkeypatch.setattr(rules_api, "fetch_page", lambda url: PageResult(url=url, final_url=url, status_code=None, error="timeout"))
    failed = client.post(f"/api/projects/{project_id}/rules/test", json={"url": "https://shop.com/", "rule": rule})
    assert failed.status_code == 502 and "timeout" in failed.json()["detail"]


def test_audit_custom_rules_summary(client, project_id):
    t = datetime(2026, 10, 29, tzinfo=timezone.utc)
    summary = [{"rule_id": 1, "name": "r", "severity": "warning", "description": "Has h1",
                "pages_checked": 3, "pages_failed": 1, "example_urls": ["https://shop.com/x"]}]
    with get_session_factory().begin() as s:
        with_rules = Audit(project_id=project_id, session_id="s1", start_url="https://shop.com/", status="completed",
                           trigger="manual", started_at=t, finished_at=t, summary_json={"custom_rules": summary})
        old = Audit(project_id=project_id, session_id="s2", start_url="https://shop.com/", status="completed",
                    trigger="manual", started_at=t, finished_at=t, summary_json={})
        s.add_all([with_rules, old]); s.flush()
        ids = with_rules.id, old.id
    assert client.get(f"/api/audits/{ids[0]}/custom-rules").json() == {"audit_id": ids[0], "items": summary}
    assert client.get(f"/api/audits/{ids[1]}/custom-rules").json()["items"] == []
    assert client.get("/api/audits/9999/custom-rules").status_code == 404
```

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_rules_api.py -q`
Expected: FAIL (404s, or an import error for `app.api.rules`).

- [ ] **Step 3: Implement `app/api/rules.py`**

```python
"""Custom rules (Phase 5.4): create, edit, test, and read an audit's summary."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, Response
from sqlalchemy import func, select

from app.api.projects import _factory
from app.auditor import checks
from app.crawler.crawler import Crawler, PageResult
from app.db.models import Audit, CustomRule, Project, as_utc
from app.db.projects import project_domain
from app.rules import engine
from app.rules.schema import RuleError, validate_rule
from app.rules.store import rule_dict
from app.services import page_pipeline

router = APIRouter()
MAX_RULES = 50


def _json(row: CustomRule) -> Dict[str, Any]:
    return {"id": row.id, "project_id": row.project_id, "name": row.name, "enabled": row.enabled,
            "severity": row.severity, "message": row.message or "", "url_pattern": row.url_pattern,
            "check": row.check_json, "description": engine.describe(row.check_json),
            "created_at": as_utc(row.created_at).isoformat(), "updated_at": as_utc(row.updated_at).isoformat()}


def _valid(data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return validate_rule(data)
    except RuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _project(session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.get("/projects/{project_id}/rules")
def list_rules(project_id: int):
    with _factory()() as session:
        _project(session, project_id)
        rows = session.scalars(select(CustomRule).where(CustomRule.project_id == project_id).order_by(CustomRule.id)).all()
        return {"items": [_json(r) for r in rows]}


@router.post("/projects/{project_id}/rules", status_code=201)
def create_rule(project_id: int, body: Dict[str, Any] = Body(...)):
    rule = _valid(body)
    with _factory().begin() as session:
        _project(session, project_id)
        count = session.scalar(select(func.count()).select_from(CustomRule).where(CustomRule.project_id == project_id))
        if count >= MAX_RULES:
            raise HTTPException(status_code=409, detail=f"a project can have at most {MAX_RULES} rules")
        row = CustomRule(project_id=project_id, name=rule["name"], enabled=rule["enabled"], severity=rule["severity"],
                         message=rule["message"], url_pattern=rule["url_pattern"], check_json=rule["check"])
        session.add(row)
        session.flush()
        return _json(row)


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: int, body: Dict[str, Any] = Body(...)):
    with _factory().begin() as session:
        row = session.get(CustomRule, rule_id)
        if row is None:
            raise HTTPException(status_code=404, detail="rule not found")
        merged = {"name": row.name, "enabled": row.enabled, "severity": row.severity, "message": row.message,
                  "url_pattern": row.url_pattern, "check": row.check_json}
        merged.update({k: v for k, v in body.items() if k in merged})
        rule = _valid(merged)
        row.name, row.enabled, row.severity = rule["name"], rule["enabled"], rule["severity"]
        row.message, row.url_pattern, row.check_json = rule["message"], rule["url_pattern"], rule["check"]
        session.flush()
        return _json(row)


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int):
    with _factory().begin() as session:
        row = session.get(CustomRule, rule_id)
        if row is None:
            raise HTTPException(status_code=404, detail="rule not found")
        session.delete(row)
    return Response(status_code=204)


def fetch_page(url: str) -> PageResult:
    """One page, fetched the way an audit fetches it."""
    crawler = Crawler(start_url=url, max_pages=1, max_depth=0, timeout=15, retries=1)
    return crawler._fetch(url, conditional=False)


@router.post("/projects/{project_id}/rules/test")
def test_rule(project_id: int, body: Dict[str, Any] = Body(...)):
    url = str(body.get("url") or "").strip()
    rule = _valid(body.get("rule") or {})
    with _factory()() as session:
        domain = _project(session, project_id).domain
    if not url.startswith(("http://", "https://")) or project_domain(url) != domain:
        raise HTTPException(status_code=400, detail=f"the URL must be on {domain}")
    page = fetch_page(url)
    if page.error or page.status_code is None:
        raise HTTPException(status_code=502, detail=f"could not fetch {url}: {page.error or 'no response'}")
    view = {"id": 0, **{k: rule[k] for k in ("name", "severity", "message", "url_pattern", "check")}}
    if not engine.applies(view, url):
        return {"applies": False, "passed": None, "observed": None, "issue": None}
    analysis = page_pipeline.analyze_page(page_pipeline.PagePayload(
        url=url, final_url=page.final_url or url, status_code=page.status_code, headers=page.headers or {},
        html=page.html or "", response_time_ms=page.response_time_ms, content_type=page.content_type or "",
        enable_keyword_analysis=False, custom_rules=[view]))
    facts = engine.PageFacts(url=url, meta=analysis.meta, text=analysis.dupe_row.get("text") or "",
                             html=page.html or "", soup=checks._soup(page.html or ""),
                             status=page.status_code, response_time_ms=page.response_time_ms)
    found = next((i for i in analysis.issues if i.get("source") == "custom"), None)
    return {"applies": True, "passed": found is None, "observed": engine.observe(view["check"], facts), "issue": found}


@router.get("/audits/{audit_id}/custom-rules")
def audit_custom_rules(audit_id: int):
    with _factory()() as session:
        audit = session.get(Audit, audit_id)
        if audit is None:
            raise HTTPException(status_code=404, detail="audit not found")
        return {"audit_id": audit_id, "items": (audit.summary_json or {}).get("custom_rules") or []}
```

`rule_dict` is imported for symmetry but unused. Remove that import if your linter flags it.

In `app/main.py`, after the accessibility router lines:

```python
from app.api.rules import router as rules_router  # noqa: E402
app.include_router(rules_router, prefix="/api")
```

- [ ] **Step 4: Run and pass, full suite, then commit**

```bash
python -m pytest tests/test_rules_api.py -q
python -m pytest -q
git add apps/backend/app/api/rules.py apps/backend/app/main.py apps/backend/tests/test_rules_api.py
git commit -m "feat(rules): rules API (CRUD, live test on a URL, audit summary)"
```

---

### Task 5: Frontend data layer

**Files:**
- Modify: `packages/shared/src/types/platform.ts`, `apps/frontend/services/platform.ts`
- Create: `apps/frontend/lib/rules.ts`, `apps/frontend/lib/__tests__/rules.test.ts`

**Interfaces:**
- Produces:
  - Types `RuleSeverity`, `RuleCheck`, `CustomRule`, `NewRule`, `RuleTestResult`, `RuleSummary`
  - `Platform.listRules(pid)`, `createRule(pid, rule)`, `updateRule(id, patch)`, `deleteRule(id)`, `testRule(pid, url, rule)`, `auditCustomRules(auditId)`
  - `lib/rules.ts`: `CHECK_TYPES`, `FIELD_OPTIONS`, `opsFor(form)`, `needsValue(op)`, `emptyForm()`, `formFromRule(rule)`, `buildRule(form) -> NewRule`, `EXAMPLE_RULE`

- [ ] **Step 1: Types and service**

Append to `packages/shared/src/types/platform.ts`:

```ts
// Custom rules (backend Phase 5.4).
export type RuleSeverity = "critical" | "warning" | "info";
export type RuleCheck =
  | { type: "field"; field: string; op: string; value?: string | number | null }
  | { type: "text"; scope: "visible" | "html"; op: "contains" | "not_contains"; value: string; case_sensitive?: boolean }
  | { type: "selector"; selector: string; op: string; value?: number | null };

export interface NewRule {
  name: string;
  enabled?: boolean;
  severity: RuleSeverity;
  message: string;
  url_pattern: string | null;
  check: RuleCheck;
}

export interface CustomRule extends Required<Omit<NewRule, "enabled">> {
  id: number;
  project_id: number;
  enabled: boolean;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface RuleTestResult {
  applies: boolean;
  passed: boolean | null;
  observed: string | number | boolean | null;
  issue: { severity: string; code: string; message: string } | null;
}

export interface RuleSummary {
  rule_id: number;
  name: string;
  severity: RuleSeverity;
  description: string;
  pages_checked: number;
  pages_failed: number;
  example_urls: string[];
}
```

In `apps/frontend/services/platform.ts`:
- Add `CustomRule, NewRule, RuleTestResult, RuleSummary` to the type import.
- Add these after `auditAccessibility`:

```ts
  listRules: (id: number) => request<{ items: CustomRule[] }>(`/projects/${id}/rules`),
  createRule: (id: number, rule: NewRule) => request<CustomRule>(`/projects/${id}/rules`, post(rule)),
  updateRule: (ruleId: number, patchBody: Partial<NewRule> & { enabled?: boolean }) =>
    request<CustomRule>(`/rules/${ruleId}`, patch(patchBody)),
  deleteRule: (ruleId: number) => request<void>(`/rules/${ruleId}`, { method: "DELETE" }),
  testRule: (id: number, url: string, rule: NewRule) =>
    request<RuleTestResult>(`/projects/${id}/rules/test`, post({ url, rule })),
  auditCustomRules: (auditId: number) => request<{ audit_id: number; items: RuleSummary[] }>(`/audits/${auditId}/custom-rules`),
```

Rebuild shared: `cd packages/shared && npx tsc`.

- [ ] **Step 2: Write the failing test** (`lib/__tests__/rules.test.ts`)

```ts
import { describe, expect, it } from "vitest";

import { buildRule, emptyForm, formFromRule, needsValue, opsFor } from "@/lib/rules";

describe("rule form helpers", () => {
  it("offers the operators that fit the chosen check", () => {
    expect(opsFor({ ...emptyForm(), type: "field", field: "title" }).map((o) => o.value)).toContain("starts_with");
    expect(opsFor({ ...emptyForm(), type: "field", field: "word_count" }).map((o) => o.value)).toEqual(["gte", "lte", "eq"]);
    expect(opsFor({ ...emptyForm(), type: "selector" }).map((o) => o.value)).toEqual(["exists", "not_exists", "count_eq", "count_gte", "count_lte"]);
    expect(opsFor({ ...emptyForm(), type: "text" }).map((o) => o.value)).toEqual(["contains", "not_contains"]);
  });

  it("knows which operators need a value", () => {
    expect(needsValue("is_empty")).toBe(false);
    expect(needsValue("exists")).toBe(false);
    expect(needsValue("contains")).toBe(true);
  });

  it("builds each kind of rule", () => {
    const base = { ...emptyForm(), name: "R", message: "", severity: "warning" as const, urlPattern: "" };
    expect(buildRule({ ...base, type: "field", field: "word_count", op: "gte", value: "300" })).toEqual({
      name: "R", severity: "warning", message: "", url_pattern: null,
      check: { type: "field", field: "word_count", op: "gte", value: 300 },
    });
    expect(buildRule({ ...base, type: "field", field: "title", op: "is_empty", value: "ignored" }).check)
      .toEqual({ type: "field", field: "title", op: "is_empty" });
    expect(buildRule({ ...base, type: "text", scope: "html", op: "contains", value: "gtag(", caseSensitive: true }).check)
      .toEqual({ type: "text", scope: "html", op: "contains", value: "gtag(", case_sensitive: true });
    expect(buildRule({ ...base, type: "selector", selector: ".price", op: "count_lte", value: "1", urlPattern: "/p/*" }))
      .toMatchObject({ url_pattern: "/p/*", check: { type: "selector", selector: ".price", op: "count_lte", value: 1 } });
  });

  it("round-trips a saved rule into the form", () => {
    const form = formFromRule({ id: 1, project_id: 2, name: "N", enabled: true, severity: "critical", message: "m",
      url_pattern: "/b/*", check: { type: "field", field: "title", op: "contains", value: "x" },
      description: "", created_at: "", updated_at: "" });
    expect(buildRule(form)).toEqual({ name: "N", severity: "critical", message: "m", url_pattern: "/b/*",
      check: { type: "field", field: "title", op: "contains", value: "x" } });
  });
});
```

- [ ] **Step 3: Run and watch it fail**

Run: `cd apps/frontend && npx vitest run lib/__tests__/rules.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 4: `lib/rules.ts`**

```ts
import type { CustomRule, NewRule, RuleCheck, RuleSeverity } from "@seo-auditor/shared";

export type CheckType = "field" | "text" | "selector";
export interface RuleForm {
  name: string; severity: RuleSeverity; message: string; urlPattern: string;
  type: CheckType; field: string; scope: "visible" | "html"; selector: string;
  op: string; value: string; caseSensitive: boolean;
}

export const CHECK_TYPES: { value: CheckType; label: string }[] = [
  { value: "field", label: "Page field" }, { value: "text", label: "Page text" }, { value: "selector", label: "CSS selector" },
];

const TEXT_FIELDS = ["title", "meta_description", "h1", "canonical", "meta_robots"];
export const FIELD_OPTIONS = [
  { value: "title", label: "Title" }, { value: "meta_description", label: "Meta description" }, { value: "h1", label: "H1" },
  { value: "canonical", label: "Canonical" }, { value: "meta_robots", label: "Meta robots" },
  { value: "word_count", label: "Word count" }, { value: "internal_links_count", label: "Internal links" },
  { value: "external_links_count", label: "External links" }, { value: "status", label: "Status code" },
  { value: "response_time_ms", label: "Response time (ms)" },
];

const TEXT_OPS = [
  { value: "contains", label: "contains" }, { value: "not_contains", label: "doesn't contain" },
  { value: "equals", label: "is exactly" }, { value: "not_equals", label: "is not" },
  { value: "starts_with", label: "starts with" }, { value: "ends_with", label: "ends with" },
  { value: "is_empty", label: "is empty" }, { value: "is_not_empty", label: "is not empty" },
  { value: "length_gte", label: "length at least" }, { value: "length_lte", label: "length at most" },
];
const NUMBER_OPS = [{ value: "gte", label: "at least" }, { value: "lte", label: "at most" }, { value: "eq", label: "exactly" }];
const SELECTOR_OPS = [
  { value: "exists", label: "exists" }, { value: "not_exists", label: "doesn't exist" },
  { value: "count_eq", label: "appears exactly" }, { value: "count_gte", label: "appears at least" },
  { value: "count_lte", label: "appears at most" },
];
const TEXT_CHECK_OPS = [{ value: "contains", label: "contains" }, { value: "not_contains", label: "doesn't contain" }];
const VALUELESS = new Set(["is_empty", "is_not_empty", "exists", "not_exists"]);
const NUMERIC = new Set(["gte", "lte", "eq", "length_gte", "length_lte", "count_eq", "count_gte", "count_lte"]);

export function opsFor(form: Pick<RuleForm, "type" | "field">) {
  if (form.type === "text") return TEXT_CHECK_OPS;
  if (form.type === "selector") return SELECTOR_OPS;
  return TEXT_FIELDS.includes(form.field) ? TEXT_OPS : NUMBER_OPS;
}

export const needsValue = (op: string) => !VALUELESS.has(op);
export const isNumeric = (op: string) => NUMERIC.has(op);

export function emptyForm(): RuleForm {
  return { name: "", severity: "warning", message: "", urlPattern: "", type: "field", field: "title",
           scope: "visible", selector: "", op: "contains", value: "", caseSensitive: false };
}

export function formFromRule(rule: CustomRule): RuleForm {
  const c = rule.check as any;
  return { ...emptyForm(), name: rule.name, severity: rule.severity, message: rule.message ?? "",
           urlPattern: rule.url_pattern ?? "", type: c.type, field: c.field ?? "title", scope: c.scope ?? "visible",
           selector: c.selector ?? "", op: c.op, value: c.value == null ? "" : String(c.value), caseSensitive: !!c.case_sensitive };
}

export function buildRule(form: RuleForm): NewRule {
  const value = needsValue(form.op) ? (isNumeric(form.op) ? Number(form.value) : form.value) : undefined;
  let check: RuleCheck;
  if (form.type === "text") {
    check = { type: "text", scope: form.scope, op: form.op as "contains" | "not_contains", value: form.value,
              ...(form.caseSensitive ? { case_sensitive: true } : {}) };
  } else if (form.type === "selector") {
    check = { type: "selector", selector: form.selector, op: form.op, ...(value !== undefined ? { value: value as number } : {}) };
  } else {
    check = { type: "field", field: form.field, op: form.op, ...(value !== undefined ? { value } : {}) };
  }
  return { name: form.name.trim(), severity: form.severity, message: form.message.trim(),
           url_pattern: form.urlPattern.trim() || null, check };
}

export const EXAMPLE_RULE: NewRule = {
  name: "Every page has a title", severity: "warning", message: "Add a unique <title>.", url_pattern: null,
  check: { type: "field", field: "title", op: "is_not_empty" },
};
```

- [ ] **Step 5: Run and pass, then commit**

```bash
npx vitest run lib/__tests__/rules.test.ts && npx tsc --noEmit
git add packages/shared/src apps/frontend/services/platform.ts apps/frontend/lib/rules.ts apps/frontend/lib/__tests__/rules.test.ts
git commit -m "feat(frontend): custom rules types, API client and form helpers"
```

---

### Task 6: Custom Rules tab and the Site Audit section

**Files:**
- Create:
  - `apps/frontend/components/platform/rule-form.tsx`
  - `apps/frontend/components/platform/severity-pill.tsx`
  - `apps/frontend/app/projects/[id]/rules/page.tsx`
  - `apps/frontend/components/platform/rules-summary.tsx`
  - `components/__tests__/rules-page.test.tsx`
- Modify: `apps/frontend/components/platform/project-tabs.tsx`, `app/projects/[id]/audits/page.tsx`, `components/__tests__/site-audit-page.test.tsx`

**Interfaces:**
- Consumes: Task 5.
- Produces: `<RuleForm projectId initial? onSaved onCancel />`, `<RulesSummary items />`, and the route `/projects/[id]/rules`.

- [ ] **Step 1: Write the failing tests** (`components/__tests__/rules-page.test.tsx`)

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import RulesPage from "@/app/projects/[id]/rules/page";
import { Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/projects/7/rules" }));

const rule = {
  id: 3, project_id: 7, name: "Brand in title", enabled: true, severity: "warning" as const, message: "",
  url_pattern: "/blog/*", check: { type: "field" as const, field: "title", op: "contains", value: "| Brand" },
  description: "Title contains '| Brand'", created_at: "", updated_at: "",
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [{ id: 11 }], total: 1, offset: 0, limit: 1 } as any);
  vi.spyOn(Platform, "auditCustomRules").mockResolvedValue({ audit_id: 11, items: [
    { rule_id: 3, name: "Brand in title", severity: "warning", description: "", pages_checked: 20, pages_failed: 3, example_urls: [] }] });
});

describe("Custom Rules tab", () => {
  it("lists rules with their description, scope, severity and last result", async () => {
    vi.spyOn(Platform, "listRules").mockResolvedValue({ items: [rule] });
    render(<RulesPage params={{ id: "7" }} />);
    expect(await screen.findByText("Brand in title")).toBeInTheDocument();
    expect(screen.getByText("Title contains '| Brand'")).toBeInTheDocument();
    expect(screen.getByText("/blog/*")).toBeInTheDocument();
    expect(screen.getByText("Warning")).toBeInTheDocument();
    expect(await screen.findByText(/failed on 3 of 20 pages/i)).toBeInTheDocument();
  });

  it("toggles and deletes a rule", async () => {
    vi.spyOn(Platform, "listRules").mockResolvedValue({ items: [rule] });
    const update = vi.spyOn(Platform, "updateRule").mockResolvedValue({ ...rule, enabled: false });
    const remove = vi.spyOn(Platform, "deleteRule").mockResolvedValue(undefined);
    render(<RulesPage params={{ id: "7" }} />);
    await userEvent.click(await screen.findByRole("switch", { name: /enable brand in title/i }));
    expect(update).toHaveBeenCalledWith(3, { enabled: false });
    await userEvent.click(screen.getByRole("button", { name: /delete brand in title/i }));
    await userEvent.click(screen.getByRole("button", { name: /confirm delete/i }));
    expect(remove).toHaveBeenCalledWith(3);
  });

  it("builds a selector rule, tests it on a URL, and saves it", async () => {
    vi.spyOn(Platform, "listRules").mockResolvedValue({ items: [] });
    const test = vi.spyOn(Platform, "testRule").mockResolvedValue({ applies: true, passed: false, observed: 0, issue: null });
    const create = vi.spyOn(Platform, "createRule").mockResolvedValue({ ...rule, id: 9 });
    render(<RulesPage params={{ id: "7" }} />);
    await userEvent.click(await screen.findByRole("button", { name: /new rule/i }));
    await userEvent.type(screen.getByLabelText(/^name/i), "Has JSON-LD");
    await userEvent.selectOptions(screen.getByLabelText(/check/i), "selector");
    await userEvent.type(screen.getByLabelText(/css selector/i), "script[type='application/ld+json']");
    await userEvent.selectOptions(screen.getByLabelText(/condition/i), "exists");
    expect(screen.queryByLabelText(/^value/i)).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/test on a url/i), "https://shop.com/p");
    await userEvent.click(screen.getByRole("button", { name: /^test$/i }));
    expect(await screen.findByText(/failed/i)).toBeInTheDocument();
    expect(screen.getByText(/saw: 0/i)).toBeInTheDocument();
    expect(test.mock.calls[0][1]).toBe("https://shop.com/p");
    await userEvent.click(screen.getByRole("button", { name: /save rule/i }));
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0][1]).toEqual({ name: "Has JSON-LD", severity: "warning", message: "", url_pattern: null,
      check: { type: "selector", selector: "script[type='application/ld+json']", op: "exists" } });
  });

  it("shows a save error from the server", async () => {
    vi.spyOn(Platform, "listRules").mockResolvedValue({ items: [] });
    const { ApiError } = await import("@/services/platform");
    vi.spyOn(Platform, "createRule").mockRejectedValue(new ApiError(422, "check: Invalid CSS selector: bad"));
    render(<RulesPage params={{ id: "7" }} />);
    await userEvent.click(await screen.findByRole("button", { name: /new rule/i }));
    await userEvent.type(screen.getByLabelText(/^name/i), "X");
    await userEvent.type(screen.getByLabelText(/^value/i), "abc");
    await userEvent.click(screen.getByRole("button", { name: /save rule/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid CSS selector");
  });

  it("offers an example rule when there are none", async () => {
    vi.spyOn(Platform, "listRules").mockResolvedValue({ items: [] });
    const create = vi.spyOn(Platform, "createRule").mockResolvedValue(rule);
    render(<RulesPage params={{ id: "7" }} />);
    await userEvent.click(await screen.findByRole("button", { name: /add an example rule/i }));
    expect(create.mock.calls[0][1].check).toEqual({ type: "field", field: "title", op: "is_not_empty" });
  });
});
```

In `components/__tests__/site-audit-page.test.tsx`:
- In `beforeEach`, add `vi.spyOn(Platform, "auditCustomRules").mockResolvedValue({ audit_id: 3, items: [] });`.
- Add this test:

```tsx
  it("shows custom rule results for the selected audit", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [audit(3)], total: 1, offset: 0, limit: 50 } as any);
    render(<SiteAuditPage params={{ id: "7" }} />);
    expect(await screen.findByText(/No custom rules ran/)).toBeInTheDocument();
    expect(Platform.auditCustomRules).toHaveBeenCalledWith(3);
  });
```

- [ ] **Step 2: Run and watch them fail**

Run: `npx vitest run components/__tests__/rules-page.test.tsx components/__tests__/site-audit-page.test.tsx`
Expected: FAIL.

- [ ] **Step 3: `components/platform/rule-form.tsx`**

```tsx
"use client";

import { useState } from "react";
import type { CustomRule, RuleSeverity, RuleTestResult } from "@seo-auditor/shared";

import { buildRule, CHECK_TYPES, emptyForm, FIELD_OPTIONS, formFromRule, isNumeric, needsValue, opsFor, type RuleForm as Form } from "@/lib/rules";
import { ApiError, Platform } from "@/services/platform";

const input = "h-9 w-full rounded-lg border bg-background px-3 text-sm";
const label = "space-y-1 text-xs font-medium text-muted-foreground";

export function RuleForm({ projectId, initial, onSaved, onCancel }: {
  projectId: number; initial?: CustomRule; onSaved: (rule: CustomRule) => void; onCancel: () => void;
}) {
  const [form, setForm] = useState<Form>(initial ? formFromRule(initial) : emptyForm());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testUrl, setTestUrl] = useState("");
  const [test, setTest] = useState<RuleTestResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const ops = opsFor(form);

  const set = (patch: Partial<Form>) => {
    setForm((f) => {
      const next = { ...f, ...patch };
      if (!opsFor(next).some((o) => o.value === next.op)) next.op = opsFor(next)[0].value;
      return next;
    });
    setTest(null);
  };

  const save = async () => {
    setSaving(true); setError(null);
    try {
      const rule = buildRule(form);
      onSaved(initial ? await Platform.updateRule(initial.id, rule) : await Platform.createRule(projectId, rule));
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Could not save the rule");
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    setTestError(null); setTest(null);
    try {
      setTest(await Platform.testRule(projectId, testUrl.trim(), buildRule(form)));
    } catch (e) {
      setTestError(e instanceof ApiError ? e.detail : "Test failed");
    }
  };

  return (
    <form className="space-y-4 rounded-[18px] border bg-card p-5" onSubmit={(e) => { e.preventDefault(); save(); }}>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className={label}>Name<input aria-label="Name" className={input} value={form.name} maxLength={80} onChange={(e) => set({ name: e.target.value })} /></label>
        <label className={label}>Severity
          <select aria-label="Severity" className={input} value={form.severity} onChange={(e) => set({ severity: e.target.value as RuleSeverity })}>
            <option value="critical">Critical</option><option value="warning">Warning</option><option value="info">Info</option>
          </select>
        </label>
      </div>
      <div className="grid gap-3 sm:grid-cols-4">
        <label className={label}>Check
          <select aria-label="Check" className={input} value={form.type} onChange={(e) => set({ type: e.target.value as Form["type"] })}>
            {CHECK_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </label>
        {form.type === "field" && (
          <label className={label}>Field
            <select aria-label="Field" className={input} value={form.field} onChange={(e) => set({ field: e.target.value })}>
              {FIELD_OPTIONS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
            </select>
          </label>
        )}
        {form.type === "text" && (
          <label className={label}>Look in
            <select aria-label="Look in" className={input} value={form.scope} onChange={(e) => set({ scope: e.target.value as "visible" | "html" })}>
              <option value="visible">Visible text</option><option value="html">Raw HTML</option>
            </select>
          </label>
        )}
        {form.type === "selector" && (
          <label className={label}>CSS selector<input aria-label="CSS selector" className={`${input} font-mono`} value={form.selector} maxLength={200} onChange={(e) => set({ selector: e.target.value })} /></label>
        )}
        <label className={label}>Condition
          <select aria-label="Condition" className={input} value={form.op} onChange={(e) => set({ op: e.target.value })}>
            {ops.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
        {needsValue(form.op) && (
          <label className={label}>Value
            <input aria-label="Value" className={input} type={isNumeric(form.op) ? "number" : "text"} min={0} maxLength={200}
                   value={form.value} onChange={(e) => set({ value: e.target.value })} />
          </label>
        )}
      </div>
      {form.type === "text" && (
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.caseSensitive} onChange={(e) => set({ caseSensitive: e.target.checked })} />Case-sensitive</label>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className={label}>Only on URLs matching (optional)<input aria-label="URL pattern" className={`${input} font-mono`} placeholder="/blog/*" value={form.urlPattern} onChange={(e) => set({ urlPattern: e.target.value })} /></label>
        <label className={label}>Message (optional)<input aria-label="Message" className={input} maxLength={200} value={form.message} onChange={(e) => set({ message: e.target.value })} /></label>
      </div>

      <div className="space-y-2 rounded-xl border border-dashed p-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className={`${label} min-w-0 flex-1`}>Test on a URL<input aria-label="Test on a URL" className={input} placeholder="https://…" value={testUrl} onChange={(e) => setTestUrl(e.target.value)} /></label>
          <button type="button" onClick={runTest} disabled={!testUrl.trim()} className="h-9 rounded-full border px-4 text-sm active:scale-95 disabled:opacity-50">Test</button>
        </div>
        {testError && <p className="text-sm text-rose-700 dark:text-rose-400">{testError}</p>}
        {test && (
          <p className="text-sm">
            {!test.applies ? "Doesn't apply to this URL (outside the URL pattern)."
              : <>{test.passed ? <span className="font-medium text-emerald-700 dark:text-emerald-400">Passed</span>
                               : <span className="font-medium text-rose-700 dark:text-rose-400">Failed</span>}
                 <span className="text-muted-foreground"> · saw: {String(test.observed)}</span></>}
          </p>
        )}
      </div>

      {error && <p role="alert" className="text-sm text-rose-700 dark:text-rose-400">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={saving || !form.name.trim()} className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95 disabled:opacity-50">Save rule</button>
        <button type="button" onClick={onCancel} className="rounded-full border px-4 py-2 text-sm active:scale-95">Cancel</button>
      </div>
    </form>
  );
}
```

In the "save error" test, the name is "X" and the default check is title `contains` with value "abc". The mocked `createRule` rejects. The test only checks that the server's message shows in `role="alert"`.

- [ ] **Step 4: `app/projects/[id]/rules/page.tsx`**

```tsx
"use client";

import { useState } from "react";
import type { CustomRule } from "@seo-auditor/shared";

import { AsyncState } from "@/components/platform/async-state";
import { PageHeader } from "@/components/platform/page-header";
import { RuleForm } from "@/components/platform/rule-form";
import { SeverityPill } from "@/components/platform/severity-pill";
import { EXAMPLE_RULE } from "@/lib/rules";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

export default function RulesPage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const rules = useApi(() => Platform.listRules(projectId), [projectId]);
  const latest = useApi(async () => {
    const audits = await Platform.listAudits(projectId, 1);
    return audits.items.length ? Platform.auditCustomRules(audits.items[0].id) : { audit_id: 0, items: [] };
  }, [projectId]);
  const [editing, setEditing] = useState<CustomRule | "new" | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const lastRun = new Map((latest.data?.items ?? []).map((s) => [s.rule_id, s]));

  const saved = () => { setEditing(null); rules.reload(); };
  const toggle = async (rule: CustomRule) => { await Platform.updateRule(rule.id, { enabled: !rule.enabled }); rules.reload(); };
  const remove = async (rule: CustomRule) => { await Platform.deleteRule(rule.id); setConfirming(null); rules.reload(); };
  const addExample = async () => { await Platform.createRule(projectId, EXAMPLE_RULE); rules.reload(); };

  return (
    <div className="space-y-6">
      <PageHeader title="Custom Rules" description="Your own checks, run on every page of every audit of this site."
                  actions={editing === null ? <button type="button" onClick={() => setEditing("new")} className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95">New rule</button> : undefined} />
      {editing !== null && (
        <RuleForm projectId={projectId} initial={editing === "new" ? undefined : editing} onSaved={saved} onCancel={() => setEditing(null)} />
      )}
      <AsyncState state={rules} isEmpty={(d) => d.items.length === 0} emptyTitle="No rules yet"
                  emptyText="Rules check every page for things that matter to this site, like a brand in the title or structured data on product pages."
                  emptyAction={<button type="button" onClick={addExample} className="rounded-full border px-4 py-2 text-sm active:scale-95">Add an example rule</button>}>
        {(d) => (
          <ul className="divide-y rounded-[18px] border bg-card">
            {d.items.map((rule) => {
              const run = lastRun.get(rule.id);
              return (
                <li key={rule.id} className="flex flex-wrap items-start gap-3 p-4">
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{rule.name}</span>
                      <SeverityPill severity={rule.severity} />
                      {rule.url_pattern && <span className="rounded border px-1.5 font-mono text-[11px] text-muted-foreground">{rule.url_pattern}</span>}
                    </div>
                    <p className="break-all text-sm text-muted-foreground">{rule.description}</p>
                    {run && <p className="text-xs text-muted-foreground">Last audit: failed on {run.pages_failed} of {run.pages_checked} pages</p>}
                  </div>
                  <div className="flex items-center gap-2">
                    <button type="button" role="switch" aria-checked={rule.enabled} aria-label={`Enable ${rule.name}`} onClick={() => toggle(rule)}
                            className={`relative h-6 w-11 rounded-full transition-colors ${rule.enabled ? "bg-primary" : "bg-muted"}`}>
                      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-background transition-all ${rule.enabled ? "left-[22px]" : "left-0.5"}`} />
                    </button>
                    <button type="button" onClick={() => setEditing(rule)} className="rounded-full border px-3 py-1 text-xs active:scale-95">Edit</button>
                    {confirming === rule.id ? (
                      <button type="button" onClick={() => remove(rule)} className="rounded-full border border-rose-300 px-3 py-1 text-xs text-rose-700 active:scale-95 dark:text-rose-400">Confirm delete</button>
                    ) : (
                      <button type="button" aria-label={`Delete ${rule.name}`} onClick={() => setConfirming(rule.id)} className="rounded-full border px-3 py-1 text-xs active:scale-95">Delete</button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </AsyncState>
    </div>
  );
}
```

Check `PageHeader`'s props in `components/platform/page-header.tsx`. If it has no `actions` prop, render the "New rule" button in a `div` right after it instead.

- [ ] **Step 5: `components/platform/severity-pill.tsx`, `components/platform/rules-summary.tsx`**, the tab and the Site Audit section

`components/platform/severity-pill.tsx`:

```tsx
import { AlertTriangle, Info, XCircle } from "lucide-react";
import type { RuleSeverity } from "@seo-auditor/shared";

const SEVERITY: Record<RuleSeverity, { label: string; className: string; Icon: typeof Info }> = {
  critical: { label: "Critical", Icon: XCircle, className: "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-400" },
  warning: { label: "Warning", Icon: AlertTriangle, className: "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-400" },
  info: { label: "Info", Icon: Info, className: "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400" },
};

export function SeverityPill({ severity }: { severity: RuleSeverity }) {
  const s = SEVERITY[severity];
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${s.className}`}><s.Icon className="h-3 w-3" aria-hidden />{s.label}</span>;
}
```

`components/platform/rules-summary.tsx`:

```tsx
import type { RuleSummary } from "@seo-auditor/shared";

import { SeverityPill } from "@/components/platform/severity-pill";

export function RulesSummary({ items }: { items: RuleSummary[] }) {
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No custom rules ran in this audit. Add rules in the Custom Rules tab.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-[13px]">
        <thead className="text-left text-xs text-muted-foreground">
          <tr className="border-b"><th className="py-2 pr-4 font-medium">Rule</th><th className="py-2 pr-4 font-medium">Severity</th>
            <th className="py-2 pr-4 font-medium">Failed / checked</th><th className="py-2 font-medium">Examples</th></tr>
        </thead>
        <tbody className="divide-y">
          {items.map((s) => (
            <tr key={s.rule_id} className="align-top">
              <td className="py-2 pr-4"><p className="font-medium">{s.name}</p><p className="text-muted-foreground">{s.description}</p></td>
              <td className="py-2 pr-4"><SeverityPill severity={s.severity} /></td>
              <td className="whitespace-nowrap py-2 pr-4 tabular-nums">{s.pages_failed} / {s.pages_checked}</td>
              <td className="py-2"><ul className="space-y-0.5">{s.example_urls.slice(0, 3).map((u) => <li key={u} className="break-all">{u}</li>)}</ul></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

`components/platform/project-tabs.tsx`: add `{ suffix: "/rules", label: "Custom Rules" },` to `TABS`.

`app/projects/[id]/audits/page.tsx`:
- Import `RulesSummary`.
- Add `const customRules = useApi(selected !== null ? () => Platform.auditCustomRules(selected) : null, [selected]);`.
- Add this section after the Accessibility section:

```tsx
            <section className="rounded-[18px] border bg-card p-5">
              <h2 className="mb-3 font-semibold tracking-tight">Custom rules</h2>
              <AsyncState state={customRules}>{(c) => <RulesSummary items={c.items} />}</AsyncState>
            </section>
```

If an existing project-tabs test lists the tabs exactly, add "Custom Rules" to its expectation.

- [ ] **Step 6: Run and pass, then commit**

```bash
npx vitest run && npx tsc --noEmit
(cd ../backend && python -m pytest -q)
git add apps/frontend
git commit -m "feat(frontend): Custom Rules tab (builder, live test, toggle) and Site Audit summary"
```

---

### Task 7: Docs and live check

- [ ] **Step 1: `docs/api.md`.** Append a section, "Custom rules". It should cover:
  - the rule shape and the three check types, with the operator table from the spec
  - the URL pattern and severity
  - issue codes (`CUSTOM_<id>`)
  - each endpoint, with one example request/response each (use the JSON from Task 4's tests)
  - the 50 cap, the test endpoint's domain rule, and the 422/409/400/502 meanings
- [ ] **Step 2: README.** Append a section, "Custom rules (Phase 5.4)". It should cover:
  - what they're for, the three check types, the tab and its live test
  - that rule failures are ordinary issues of the chosen severity
  - that editing rules re-checks pages on the next audit
  - a **How to verify** block:

```bash
cd apps/backend
python -m pytest tests/test_rules_engine.py tests/test_rules_store.py tests/test_rules_pipeline.py tests/test_rules_api.py -q
export SESSION_DIR=/tmp/seo-rules
python -m uvicorn app.main:app --port 5000 &
python -m app.cli https://books.toscrape.com/ --max-pages 10 --skip-external-links   # creates project 1
curl -s -X POST -H 'Content-Type: application/json' localhost:5000/api/projects/1/rules \
  -d '{"name":"Long enough","severity":"warning","check":{"type":"field","field":"word_count","op":"gte","value":500}}'
curl -s -X POST -H 'Content-Type: application/json' localhost:5000/api/projects/1/rules/test \
  -d '{"url":"https://books.toscrape.com/","rule":{"name":"Price shown","check":{"type":"selector","selector":".price_color","op":"exists"}}}'
python -m app.cli https://books.toscrape.com/ --max-pages 10 --skip-external-links --json \
  | python -c "import sys,json; [print(r) for r in json.load(sys.stdin)['custom_rules']]"
```

- [ ] **Step 3: Commit the docs** (full backend suite first).
- [ ] **Step 4: Live check.**
  1. Run the README commands. The rule test should print `passed: true, observed: 20`.
  2. On a second audit, "Long enough" should fail on most pages and show in `custom_rules` and the issues.
  3. Add a scoped rule (`/catalogue/category/*`, title contains "Books"). Check its `pages_checked` excludes the homepage.
  4. Edit a rule and re-audit. Pages are re-analysed (the reuse counts drop to `analysed`).
  5. UI at 1440 and 390 px (Playwright screenshots if the Chrome extension isn't connected):
     - the Custom Rules tab: list, the form with dependent inputs, a live test, toggle, delete-confirm
     - the Site Audit "Custom rules" section
     - no sideways page scroll
  6. Fix anything found (with a test when it's behaviour), commit, and stop the servers.
