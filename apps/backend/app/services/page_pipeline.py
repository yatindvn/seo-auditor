"""Stage 2 of the audit pipeline: everything that happens to one page's HTML.

`analyze_page` is deliberately **pure** -- it takes a payload of plain values and
returns plain values, touching no config, no network, no module-level state and
nothing belonging to the crawler. That is what lets it run in a process pool
while the crawl is still fetching, turning the checks from a phase appended to
the crawl into work that overlaps it.

Three things stay in the orchestrator rather than moving here, because they are
network-bound and quota-limited and must not be multiplied across worker
processes: rank checking, keyword suggestions, and PageSpeed Insights.
"""

from __future__ import annotations

import urllib.parse as up
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from app.analysis import analysis, minhash
from app.rules import engine as rules_engine
from app.auditor import checks
from app.crawler.crawler import normalize_url, same_registrable_domain
from app.seo import keyword_extraction
from app.utils import performance


@dataclass
class PagePayload:
    """One fetched page, as plain picklable values.

    Mirrors the fields of `PageResult` that the checks read. It is a separate
    type because `PageResult` carries crawler-owned state (referrers, fetch
    timing) that a worker has no business seeing.
    """

    url: str
    final_url: str
    status_code: Optional[int]
    headers: Dict[str, Any]
    html: str
    depth: int = 0
    redirect_chain: List[Dict] = field(default_factory=list)
    response_time_ms: Optional[float] = None
    content_type: str = ""
    error: Optional[str] = None
    enable_keyword_analysis: bool = True
    target_keywords: Optional[List[str]] = None
    compute_signature: bool = False
    custom_rules: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class HtmlAnalysis:
    """Everything derived from a page's HTML alone.

    This is the half worth caching across audits: it is the expensive half
    (one parse, ~20 checks), and it stays true for as long as the HTML is
    unchanged. Nothing here may read headers, status, or timing -- those
    belong to analyze_response, which runs fresh every audit.
    """
    issues: List[Dict] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    weight: Dict[str, Any] = field(default_factory=dict)
    meta_robots_content: str = ""
    dupe_row: Dict[str, Any] = field(default_factory=dict)
    keyword_data: List[Dict] = field(default_factory=list)
    internal_links: List[str] = field(default_factory=list)
    external_links: List[str] = field(default_factory=list)
    signature: Optional[bytes] = None

    def to_json(self) -> Dict[str, Any]:
        """JSON-safe form. The signature is bytes and is stored separately."""
        data = asdict(self)
        data.pop("signature")
        return data

    @classmethod
    def from_json(cls, data: Dict[str, Any], signature: Optional[bytes] = None) -> "HtmlAnalysis":
        return cls(**data, signature=signature)


@dataclass
class PageAnalysis:
    url: str
    issues: List[Dict] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    dupe_row: Dict[str, Any] = field(default_factory=dict)
    keyword_data: List[Dict] = field(default_factory=list)
    signature: Optional[bytes] = None
    internal_links: List[str] = field(default_factory=list)
    external_links: List[str] = field(default_factory=list)
    failed: bool = False
    # The cacheable half this analysis was built from; None for a failure.
    html_part: Optional[HtmlAnalysis] = None


def resolve_keyword_data(
    target_keywords: Optional[List[str]],
    enable_keyword_analysis: bool,
    page_meta_entry: Dict[str, Any],
    content_stats: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Decide what `keyword_data` should be for a page.

    `target_keywords` is an explicit manual override and always wins,
    regardless of `enable_keyword_analysis`. Otherwise, `enable_keyword_analysis`
    is the master switch for the whole feature: when False, extraction is
    skipped and an empty list is returned.
    """
    if target_keywords:
        return [{"phrase": k, "score": None, "found_in": []} for k in target_keywords]
    if not enable_keyword_analysis:
        return []
    return keyword_extraction.extract_keywords(page_meta_entry, content_stats)


def _extract_links(final_url: str, soup) -> tuple:
    """Split the page's anchors into internal and external, deduplicated.

    Lives here rather than in the crawler so each page's HTML is parsed once:
    the crawler would otherwise build its own soup to find links and the worker
    would build a second one to run the checks.
    """
    if soup is None:
        return [], []

    root_netloc = up.urlsplit(final_url).netloc
    internal: List[str] = []
    external: List[str] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = normalize_url(up.urljoin(final_url, href))
        if absolute in seen:
            continue
        seen.add(absolute)
        if same_registrable_domain(absolute, root_netloc):
            internal.append(absolute)
        else:
            external.append(absolute)
    return internal, external


def failed_analysis(url: str, exc: Exception) -> PageAnalysis:
    """The result for a page whose checks raised.

    A blank row would read as "audited, nothing wrong" -- worse than the crash,
    because it is wrong quietly -- so the failure is carried in the report.
    """
    return PageAnalysis(
        url=url,
        issues=[checks.issue(
            "critical", "AUDIT_ERROR", f"This page could not be audited: {exc}"
        )],
        meta={},
        dupe_row={},
        failed=True,
    )


def analyze_html(payload: PagePayload) -> HtmlAnalysis:
    page = payload  # the checks read .html/.headers/.status_code/.url off this
    page_url = payload.url

    issues: List[Dict] = []
    issues += checks.check_mixed_content(page)
    canon_issues, canonical = checks.check_canonical(page, page_url)
    issues += canon_issues

    title_issues, title = checks.check_title(page)
    issues += title_issues
    desc_issues, desc = checks.check_meta_description(page)
    issues += desc_issues
    heading_issues, h1 = checks.check_headings(page)
    issues += heading_issues
    issues += checks.check_images(page)
    issues += checks.check_links(page)
    issues += checks.check_structured_data(page)
    issues += checks.check_open_graph_twitter(page)
    issues += checks.check_url_structure(page_url)

    content_issues, content_stats = checks.check_content(page)
    issues += content_issues

    issues += checks.check_mobile(page)
    issues += checks.check_accessibility(page)
    issues += checks.check_hreflang(page)
    issues += checks.check_media(page)
    issues += checks.check_js_rendering_signal(page)

    weight = performance.html_weight(page)

    soup = checks._soup(payload.html)
    meta_robots = None
    lang = None
    open_graph: Dict[str, str] = {}
    twitter_cards: Dict[str, str] = {}
    h2_count = 0
    h3_count = 0
    heading_hierarchy: List[Dict] = []
    images_count = 0
    missing_alt_count = 0
    structured_data: List[Dict] = []

    if soup:
        html_el = soup.find("html")
        lang = html_el.get("lang") if html_el else None
        robots_tag = soup.find("meta", attrs={"name": "robots"})
        meta_robots = robots_tag.get("content") if robots_tag else None

        for meta_tag in soup.find_all("meta"):
            prop = meta_tag.get("property", "")
            name = meta_tag.get("name", "")
            content = meta_tag.get("content", "")
            if prop.startswith("og:"):
                open_graph[prop] = content
            if name.startswith("twitter:"):
                twitter_cards[name] = content

        h2_count = len(soup.find_all("h2"))
        h3_count = len(soup.find_all("h3"))

        for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            text = heading.get_text(strip=True)
            if text:
                heading_hierarchy.append({"level": int(heading.name[1]), "text": text[:100]})

        imgs = soup.find_all("img")
        images_count = len(imgs)
        missing_alt_count = sum(1 for img in imgs if not img.get("alt", "").strip())

        for script in soup.find_all("script", type="application/ld+json"):
            if script.string:
                structured_data.append({"type": "JSON-LD", "raw": script.string.strip()[:500]})

    internal_links, external_links = _extract_links(payload.final_url or page_url, soup)
    word_cnt = content_stats.get("word_count", 0)

    meta = {
        "title": title,
        "meta_description": desc,
        "h1": h1,
        "word_count": word_cnt,
        "canonical": canonical,
        "meta_robots": meta_robots,
        "lang": lang,
        "open_graph": open_graph,
        "twitter_cards": twitter_cards,
        "h2_count": h2_count,
        "h3_count": h3_count,
        "heading_hierarchy": heading_hierarchy,
        "char_count": len(content_stats.get("text", "")),
        "reading_time_mins": max(1, round(word_cnt / 200)) if word_cnt else 0,
        "internal_links_count": len(internal_links),
        # Counted from the page's own anchors. This was previously derived from
        # the crawler's inbound_links, which is only ever populated for internal
        # pages it fetched -- so the intersection was empty and every page
        # reported 0 external links.
        "external_links_count": len(external_links),
        "images_count": images_count,
        "missing_alt_count": missing_alt_count,
        "structured_data": structured_data,
    }

    keyword_data = resolve_keyword_data(
        payload.target_keywords, payload.enable_keyword_analysis, meta, content_stats
    )

    text = content_stats.get("text") or ""
    dupe_row = {
        "url": page_url,
        "title": title,
        "meta_description": desc,
        "h1": h1,
        "canonical": canonical,
        "content_hash": analysis.content_hash(text) if text else None,
        "text": text,
    }

    # Custom rules (Phase 5.4), on this parse: cached with the HTML half, so a
    # rule edit changes the analyzer fingerprint and re-analyses the page.
    rule_issues, rules_checked = rules_engine.evaluate(payload.custom_rules, rules_engine.PageFacts(
        url=page_url, meta=meta, text=text, html=payload.html or "", soup=soup), "html")
    issues += rule_issues
    if payload.custom_rules:
        meta["custom_rules_checked"] = rules_checked

    return HtmlAnalysis(
        issues=issues,
        meta=meta,
        weight=weight,
        meta_robots_content=checks.meta_robots_content(page),
        dupe_row=dupe_row,
        keyword_data=keyword_data,
        internal_links=internal_links,
        external_links=external_links,
        signature=minhash.signature(text) if payload.compute_signature else None,
    )


def analyze_response(payload: PagePayload, html_part: HtmlAnalysis) -> PageAnalysis:
    """The checks that read the response rather than the HTML, merged with an
    HTML analysis -- fresh or cached.

    Never parses HTML, so it runs on a 304's empty body: it is what makes
    status, redirects, security headers, compression, caching and TTFB current
    on every audit while the HTML half is reused.
    """
    page = payload
    issues: List[Dict] = []
    issues += checks.check_status_and_https(page, {})
    robots_header = page.headers.get("X-Robots-Tag", "") if page.headers else ""
    issues += checks.robots_issues(robots_header, html_part.meta_robots_content)
    issues += html_part.issues
    issues += checks.check_security_headers(page)

    weight = performance.analyze_page_weight(page, html_part.weight)
    issues += performance.check_performance_proxies(page, weight)

    security_headers: Dict[str, Any] = {}
    if payload.headers:
        headers_lower = {k.lower(): v for k, v in payload.headers.items()}
        for header in ("strict-transport-security", "content-security-policy",
                       "x-frame-options", "x-content-type-options", "referrer-policy"):
            security_headers[header] = headers_lower.get(header, False)

    response_issues, response_checked = rules_engine.evaluate(payload.custom_rules, rules_engine.PageFacts(
        url=payload.url, status=payload.status_code, response_time_ms=payload.response_time_ms), "response")
    issues += response_issues

    meta = {**html_part.meta, "performance": weight, "security_headers": security_headers}
    # Only with rules, so an audit without any keeps byte-identical output.
    if payload.custom_rules:
        meta["custom_rules_checked"] = [*html_part.meta.get("custom_rules_checked", []), *response_checked]

    return PageAnalysis(
        url=payload.url,
        issues=issues,
        meta=meta,
        dupe_row=html_part.dupe_row,
        keyword_data=html_part.keyword_data,
        signature=html_part.signature,
        internal_links=html_part.internal_links,
        external_links=html_part.external_links,
        html_part=html_part,
    )


def analyze_page(payload: PagePayload) -> PageAnalysis:
    return analyze_response(payload, analyze_html(payload))
