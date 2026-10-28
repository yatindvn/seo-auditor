"""axe results -> violations, a 0-100 score, and audit issues.

axe runs inside the page's own JavaScript world, so a hostile page could
tamper with what it returns. Everything read here is treated as untrusted:
impacts are whitelisted, strings are cut short, and only Deque's help links
are kept."""

from __future__ import annotations

from typing import Any, Dict, List

from app.accessibility.model import IMPACTS, A11yResult
from app.auditor.checks import issue

PENALTY = {"critical": 10, "serious": 7, "moderate": 3, "minor": 1}
# Already reported on every page by the raw HTML checks (A11Y_IMG_NO_ALT_ATTR,
# A11Y_UNLABELED_FORM_FIELD, A11Y_MISSING_LANG): kept in the scan, not re-raised.
COVERED_BY_RAW_CHECKS = {"image-alt", "label", "html-has-lang"}
MAX_TARGETS = 5
HELP_HOST = "https://dequeuniversity.com/"


def _text(value: Any, limit: int) -> str:
    return str(value or "")[:limit]


def _flatten(target: Any) -> List[str]:
    if isinstance(target, list):
        return [part for item in target for part in _flatten(item)]
    return [str(target)]


def _violation(raw: Dict[str, Any]) -> Dict[str, Any]:
    impact = raw.get("impact") if raw.get("impact") in PENALTY else "minor"
    nodes = raw.get("nodes") if isinstance(raw.get("nodes"), list) else []
    help_url = raw.get("helpUrl")
    rule = _text(raw.get("id"), 100)
    return {
        "id": rule,
        "impact": impact,
        "help": _text(raw.get("help") or rule, 300),
        "help_url": help_url if isinstance(help_url, str) and help_url.startswith(HELP_HOST) else None,
        "wcag": [t for t in (raw.get("tags") or []) if isinstance(t, str) and t.startswith("wcag")][:10],
        "nodes_count": len(nodes),
        "targets": [_text(" ".join(_flatten((n or {}).get("target") or [])), 200) for n in nodes[:MAX_TARGETS]],
    }


def summarize(url: str, raw: Dict[str, Any]) -> A11yResult:
    violations = [_violation(v) for v in (raw.get("violations") or []) if isinstance(v, dict)]
    violations.sort(key=lambda v: (IMPACTS.index(v["impact"]), v["id"]))
    counts = {i: 0 for i in IMPACTS}
    for v in violations:
        counts[v["impact"]] += 1
    score = max(0, 100 - sum(PENALTY[v["impact"]] for v in violations))
    return A11yResult(url=url, score=score, counts=counts, violations=violations)


def a11y_issues(result: A11yResult) -> List[Dict[str, str]]:
    if result.status != "scanned":
        return []
    out = []
    for v in result.violations:
        if v["id"] in COVERED_BY_RAW_CHECKS:
            continue
        n = v["nodes_count"]
        severity = "warning" if v["impact"] in ("critical", "serious") else "info"
        found = issue(severity, "A11Y_" + v["id"].upper().replace("-", "_"),
                      f"{v['help']} ({n} element{'' if n == 1 else 's'}, {v['impact']})")
        # The overall health score counts axe findings like info (see
        # report.compute_health_score); they stay warnings everywhere else.
        found["source"] = "axe"
        out.append(found)
    return out
