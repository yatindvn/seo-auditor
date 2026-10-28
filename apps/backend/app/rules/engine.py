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
        if op in ("exists", "not_exists"):
            return (seen > 0) is (op == "exists")
        limit = int(value)
        return seen == limit if op == "count_eq" else (seen >= limit if op == "count_gte" else seen <= limit)
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
