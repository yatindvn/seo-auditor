"""
performance.py — Performance auditing.

Full Core Web Vitals (LCP/CLS/INP/FCP/TBT) require a real browser (Lighthouse /
Chrome DevTools Protocol) which isn't available in a lightweight CLI without a
Chrome install. This module:

1. Always computes lightweight proxy metrics from the raw response: TTFB
   (response time), transfer size, DOM size, counts of render-blocking
   resources, JS/CSS byte counts, compression + cache header checks.
2. Optionally calls the Google PageSpeed Insights API (if --psi-key is
   supplied) to fetch real lab + field Core Web Vitals data.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from app.auditor.checks import issue

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def analyze_page_weight(page) -> Dict:
    soup = None
    if page.html:
        try:
            soup = BeautifulSoup(page.html, "lxml")
        except Exception:
            soup = None

    dom_nodes = len(soup.find_all(True)) if soup else 0
    scripts = soup.find_all("script") if soup else []
    styles = soup.find_all("link", rel="stylesheet") if soup else []
    render_blocking_css = [s for s in styles if not s.get("media") or s.get("media") == "all"]
    render_blocking_js = [s for s in scripts if s.get("src") and not (s.get("async") or s.get("defer"))]

    html_bytes = len(page.html.encode("utf-8")) if page.html else 0
    content_length_header = page.headers.get("Content-Length") if page.headers else None

    return {
        "ttfb_ms": page.response_time_ms,
        "html_size_bytes": html_bytes,
        "content_length_header": content_length_header,
        "dom_node_count": dom_nodes,
        "script_tag_count": len(scripts),
        "stylesheet_count": len(styles),
        "render_blocking_css_count": len(render_blocking_css),
        "render_blocking_js_count": len(render_blocking_js),
    }


def check_performance_proxies(page, weight: Dict) -> List[Dict]:
    out = []
    if weight["ttfb_ms"] and weight["ttfb_ms"] > 800:
        out.append(issue("warning", "SLOW_TTFB", f"Slow response time: {weight['ttfb_ms']}ms"))
    if weight["dom_node_count"] > 1500:
        out.append(issue("warning", "LARGE_DOM", f"Large DOM: {weight['dom_node_count']} nodes"))
    if weight["render_blocking_css_count"] > 4:
        out.append(issue("info", "RENDER_BLOCKING_CSS", f"{weight['render_blocking_css_count']} render-blocking stylesheets"))
    if weight["render_blocking_js_count"] > 4:
        out.append(issue("info", "RENDER_BLOCKING_JS", f"{weight['render_blocking_js_count']} render-blocking scripts"))
    if weight["html_size_bytes"] > 300_000:
        out.append(issue("info", "LARGE_HTML", f"HTML document is {weight['html_size_bytes'] // 1024}KB"))

    headers = page.headers or {}
    headers_lower = {k.lower(): v for k, v in headers.items()}
    if "content-encoding" not in headers_lower:
        out.append(issue("info", "NO_COMPRESSION", "Response is not compressed (no Content-Encoding header)"))
    if "cache-control" not in headers_lower:
        out.append(issue("info", "NO_CACHE_HEADER", "No Cache-Control header set"))
    return out


def fetch_psi_metrics(url: str, api_key: str, strategy: str = "mobile", timeout: int = 30) -> Optional[Dict]:
    """Call Google PageSpeed Insights API for real Core Web Vitals data (lab + field)."""
    try:
        resp = requests.get(
            PSI_ENDPOINT,
            params={"url": url, "key": api_key, "strategy": strategy, "category": "performance"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return {"error": f"PSI API returned {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        lighthouse = data.get("lighthouseResult", {})
        audits = lighthouse.get("audits", {})
        categories = lighthouse.get("categories", {})
        field = data.get("loadingExperience", {}).get("metrics", {})

        def audit_val(key):
            a = audits.get(key, {})
            return a.get("displayValue") or a.get("numericValue")

        return {
            "performance_score": (categories.get("performance", {}).get("score") or 0) * 100,
            "lab_lcp": audit_val("largest-contentful-paint"),
            "lab_cls": audit_val("cumulative-layout-shift"),
            "lab_fcp": audit_val("first-contentful-paint"),
            "lab_tbt": audit_val("total-blocking-time"),
            "lab_speed_index": audit_val("speed-index"),
            "field_lcp": field.get("LARGEST_CONTENTFUL_PAINT_MS", {}).get("percentile"),
            "field_cls": field.get("CUMULATIVE_LAYOUT_SHIFT_SCORE", {}).get("percentile"),
            "field_inp": field.get("INTERACTION_TO_NEXT_PAINT", {}).get("percentile"),
            "field_fcp": field.get("FIRST_CONTENTFUL_PAINT_MS", {}).get("percentile"),
        }
    except requests.RequestException as exc:
        return {"error": str(exc)}
