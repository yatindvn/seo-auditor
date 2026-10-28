"""Google PageSpeed Insights v5: lab data from Lighthouse in Google's cloud,
plus page-level field data (CrUX) when Google has enough real-user traffic."""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from app.providers.serp import ProviderSkipped
from app.providers.spend import reserve
from app.vitals.model import VitalsResult, rate

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

_FIELD_METRICS = {
    "lcp_ms": "LARGEST_CONTENTFUL_PAINT_MS",
    "inp_ms": "INTERACTION_TO_NEXT_PAINT",
    "cls": "CUMULATIVE_LAYOUT_SHIFT_SCORE",
    "fcp_ms": "FIRST_CONTENTFUL_PAINT_MS",
    "ttfb_ms": "EXPERIMENTAL_TIME_TO_FIRST_BYTE",
}


def _number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_lab(lhr: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Numbers from a Lighthouse result (PSI's lighthouseResult, or the local
    CLI's JSON): numericValue, never the display strings."""
    audits = lhr.get("audits") or {}
    score = _number(((lhr.get("categories") or {}).get("performance") or {}).get("score"))

    def audit(key: str) -> Optional[float]:
        return _number((audits.get(key) or {}).get("numericValue"))

    return {
        "performance_score": round(score * 100, 1) if score is not None else None,
        "lcp_ms": audit("largest-contentful-paint"),
        "cls": audit("cumulative-layout-shift"),
        "fcp_ms": audit("first-contentful-paint"),
        "tbt_ms": audit("total-blocking-time"),
        "ttfb_ms": audit("server-response-time"),
    }


def parse_field(loading_experience: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """This page's 75th-percentile field values, or {} when Google has none
    for it. Origin-wide data (origin_fallback) is not this page's, so it is
    ignored."""
    if not loading_experience or loading_experience.get("origin_fallback"):
        return {}
    metrics = loading_experience.get("metrics") or {}
    out: Dict[str, float] = {}
    for key, name in _FIELD_METRICS.items():
        value = _number((metrics.get(name) or {}).get("percentile"))
        if value is not None:
            out[key] = value / 100 if key == "cls" else value   # CLS arrives x100
    return out if any(k in out for k in ("lcp_ms", "inp_ms", "cls")) else {}


def parse_psi(url: str, strategy: str, data: Dict[str, Any]) -> VitalsResult:
    lhr = data.get("lighthouseResult") or {}
    runtime = lhr.get("runtimeError")
    if runtime:
        return VitalsResult(url=url, strategy=strategy, source="psi",
                            error=f"PSI: {runtime.get('message') or runtime.get('code')}")
    field = parse_field(data.get("loadingExperience"))
    result = VitalsResult(url=url, strategy=strategy, source="psi",
                          data_kind="field" if field else "lab", **parse_lab(lhr))
    for key, value in field.items():    # field values replace lab ones where present
        setattr(result, key, value)
    result.rating = rate(result)
    return result


class PsiProvider:
    name = "psi"

    def __init__(self, api_key: str, cap: int, timeout: int = 60) -> None:
        self.api_key = api_key
        self.cap = cap
        self.timeout = timeout

    def _redact(self, text: str) -> str:
        return text.replace(self.api_key, "***") if self.api_key else text

    def measure(self, url: str, strategy: str = "mobile") -> VitalsResult:
        def failed(message: str) -> VitalsResult:
            return VitalsResult(url=url, strategy=strategy, source="psi", error=self._redact(message))

        try:
            reserve(self.name, self.cap)
        except ProviderSkipped as exc:
            return failed(str(exc))
        try:
            resp = requests.get(PSI_ENDPOINT, timeout=self.timeout, params={
                "url": url, "key": self.api_key, "strategy": strategy, "category": "performance",
            })
        except requests.RequestException as exc:
            # The type only: str(exc) carries the request URL, key included.
            return failed(f"PSI request failed: {type(exc).__name__}")
        if resp.status_code != 200:
            try:
                detail = (resp.json() or {}).get("error", {}).get("message") or ""
            except ValueError:
                detail = resp.text
            return failed(f"PSI returned {resp.status_code}: {detail[:200]}")
        try:
            data = resp.json()
        except ValueError:
            return failed("PSI returned invalid JSON")
        return parse_psi(url, strategy, data or {})
