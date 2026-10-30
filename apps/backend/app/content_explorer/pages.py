"""Each top result fetched once and run through the audit's own page analysis."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from app.auditor import checks
from app.crawler.crawler import Crawler, PageResult
from app.providers.serp import SerpItem
from app.services import page_pipeline

WORKERS = 4
MAX_OUTLINE = 30
MAX_HEADING = 120
MAX_SCHEMA = 10


def empty_row(item: SerpItem) -> Dict[str, Any]:
    return {"position": item.position, "url": item.url, "domain": item.domain, "title": item.title or None,
            "status": None, "error": None, "word_count": None, "h1": None, "outline": [], "schema_types": [],
            "images": None, "internal_links": None, "external_links": None, "readability": None, "issues": None,
            "backlinks": None, "referring_domains": None}


def schema_types(structured_data) -> List[str]:
    found: List[str] = []

    def walk(node) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            kind = node.get("@type")
            for value in kind if isinstance(kind, list) else [kind]:
                if isinstance(value, str) and value and value not in found:
                    found.append(value)
            if "@graph" in node:
                walk(node["@graph"])

    for block in structured_data or []:
        if not isinstance(block, dict) or block.get("type") != "JSON-LD":
            continue
        try:
            walk(json.loads(block.get("raw") or ""))
        except (ValueError, TypeError):
            continue
    return found[:MAX_SCHEMA]


def fetch_page(url: str) -> PageResult:
    """One page, fetched the way an audit fetches it."""
    crawler = Crawler(start_url=url, max_pages=1, max_depth=0, timeout=15, retries=1)
    return crawler._fetch(url, conditional=False)


def _round(value: Optional[float]) -> Optional[float]:
    return round(float(value), 1) if value is not None else None


def page_facts(item: SerpItem, page: PageResult) -> Dict[str, Any]:
    row = empty_row(item)
    row["status"] = page.status_code
    if page.error or page.status_code is None:
        row["error"] = page.error or "no response"
        return row
    if page.status_code >= 400:
        row["error"] = f"HTTP {page.status_code}"
        return row
    analysis = page_pipeline.analyze_page(page_pipeline.PagePayload(
        url=item.url, final_url=page.final_url or item.url, status_code=page.status_code, headers=page.headers or {},
        html=page.html or "", response_time_ms=page.response_time_ms, content_type=page.content_type or "",
        enable_keyword_analysis=False))
    meta = analysis.meta
    outline = [{"level": h["level"], "text": (h.get("text") or "")[:MAX_HEADING]}
               for h in meta.get("heading_hierarchy") or [] if h.get("level") in (2, 3)]
    row.update(title=meta.get("title") or item.title or None, word_count=meta.get("word_count"), h1=meta.get("h1"),
               outline=outline[:MAX_OUTLINE], schema_types=schema_types(meta.get("structured_data")),
               images=meta.get("images_count"), internal_links=meta.get("internal_links_count"),
               external_links=meta.get("external_links_count"),
               readability=_round(checks.readability_flesch(analysis.dupe_row.get("text") or "")),
               issues=sum(1 for i in analysis.issues if i.get("severity") in ("error", "warning")))
    return row


def fetch_results(items: List[SerpItem], fetch=None) -> List[Dict[str, Any]]:
    fetch = fetch or fetch_page

    def one(item: SerpItem) -> Dict[str, Any]:
        try:
            return page_facts(item, fetch(item.url))
        except Exception as exc:
            row = empty_row(item)
            row["error"] = f"fetch failed ({type(exc).__name__})"
            return row

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(one, items))


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


_SCHEMAS = ["Article", "Product", "FAQPage", "BreadcrumbList", "Organization", "Review", "HowTo"]
_H2 = ["What is", "Best", "How to choose", "Prices of", "Reviews of", "Where to buy", "History of", "FAQ about"]


class DryRunPages:
    """Stable made-up facts: the dry-run SERP's URLs can't be fetched."""

    def results(self, items: List[SerpItem], topic: str) -> List[Dict[str, Any]]:
        rows = []
        for item in items:
            s = _seed(item.url)
            row = empty_row(item)
            if s % 10 == 7:
                row.update(status=403, error="HTTP 403")
                rows.append(row)
                continue
            outline = []
            for n in range(3 + s % 6):
                outline.append({"level": 2, "text": f"{_H2[(s + n) % len(_H2)]} {topic}"})
                if (s >> n) % 3 == 0:
                    outline.append({"level": 3, "text": f"Tips {n + 1}"})
            types = list(dict.fromkeys(_SCHEMAS[(s >> k) % len(_SCHEMAS)] for k in (0, 4, 8)[: 1 + s % 3]))
            row.update(status=200, title=item.title or None, word_count=600 + s % 2400, h1=(item.title or topic),
                       outline=outline[:MAX_OUTLINE], schema_types=types, images=2 + s % 20, internal_links=20 + s % 80,
                       external_links=s % 15, readability=round(40 + (s % 400) / 10, 1), issues=s % 6)
            rows.append(row)
        return rows
