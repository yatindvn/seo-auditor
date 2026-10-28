"""The Core Web Vitals result type, Google's thresholds, and the issues a
measurement raises."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Protocol, Tuple

from app.auditor.checks import issue

# (good at or under, poor over) -- Google's published Core Web Vitals
# thresholds. TBT is Lighthouse's own scale: lab runs have no INP, and TBT is
# the lab measure Google points to in its place.
THRESHOLDS: Dict[str, Tuple[float, float]] = {
    "lcp_ms": (2500, 4000),
    "inp_ms": (200, 500),
    "cls": (0.1, 0.25),
    "tbt_ms": (200, 600),
}
_LABELS = {"lcp_ms": "LCP", "inp_ms": "INP", "cls": "CLS", "tbt_ms": "TBT"}
_ORDER = ["good", "needs_improvement", "poor"]


@dataclass
class VitalsResult:
    url: str
    strategy: str = "mobile"
    source: str = "not_measured"          # psi | lighthouse | not_measured
    data_kind: Optional[str] = None       # field | lab: which data the rating used
    performance_score: Optional[float] = None
    lcp_ms: Optional[float] = None
    inp_ms: Optional[float] = None
    cls: Optional[float] = None
    fcp_ms: Optional[float] = None
    ttfb_ms: Optional[float] = None
    tbt_ms: Optional[float] = None
    rating: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {**asdict(self), "metric_ratings": metric_ratings(self)}


class VitalsProvider(Protocol):
    name: str

    def measure(self, url: str, strategy: str = "mobile") -> VitalsResult: ...


def rate_metric(metric: str, value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    good, poor = THRESHOLDS[metric]
    if value <= good:
        return "good"
    return "needs_improvement" if value <= poor else "poor"


def _rated(result) -> List[str]:
    """Field data is rated on LCP, INP and CLS. Lab data has no INP, so TBT
    stands in for it."""
    return ["lcp_ms", "inp_ms", "cls"] if result.data_kind == "field" else ["lcp_ms", "tbt_ms", "cls"]


def rate(result) -> Optional[str]:
    """The page's rating: its worst rated metric. Missing metrics are ignored."""
    ratings = [r for r in (rate_metric(m, getattr(result, m)) for m in _rated(result)) if r]
    return max(ratings, key=_ORDER.index) if ratings else None


def metric_ratings(obj) -> Dict[str, Optional[str]]:
    """Per-metric ratings for any object with the metric attributes (a
    VitalsResult or a stored row), so the UI never re-implements thresholds."""
    return {m: rate_metric(m, getattr(obj, m, None)) for m in THRESHOLDS}


def _fmt(metric: str, value: float) -> str:
    if metric == "cls":
        return f"{value:.2f}"
    if metric == "lcp_ms":
        return f"{value / 1000:.1f} s"
    return f"{round(value)} ms"


def vitals_issues(result) -> List[Dict[str, str]]:
    if result.error or result.source == "not_measured":
        return []
    out = []
    for metric in _rated(result):
        value = getattr(result, metric)
        rating = rate_metric(metric, value)
        if rating in (None, "good"):
            continue
        good, poor = THRESHOLDS[metric]
        label = _LABELS[metric]
        if rating == "poor":
            out.append(issue("warning", f"CWV_{label}_POOR",
                             f"{label} {_fmt(metric, value)} ({result.data_kind}) — poor, over {_fmt(metric, poor)}"))
        else:
            out.append(issue("info", f"CWV_{label}_NEEDS_IMPROVEMENT",
                             f"{label} {_fmt(metric, value)} ({result.data_kind}) — needs improvement, over {_fmt(metric, good)}"))
    return out
